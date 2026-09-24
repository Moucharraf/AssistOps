from dataclasses import dataclass
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from assistops.config import Settings
from assistops.storage import connect


@dataclass(frozen=True)
class Lease:
    event_id: UUID
    token: UUID
    attempt: int
    payload: dict
    correlation_id: str


@dataclass(frozen=True)
class Exhausted:
    event_id: UUID


def audit(connection, event_id, action, details):
    connection.execute(
        """INSERT INTO event_audit (event_id, action, connector_id, correlation_id, details)
           SELECT id, %s, connector_id, correlation_id, %s FROM inbound_events WHERE id = %s""",
        (action, Jsonb(details), event_id),
    )


class JobStore:
    def __init__(self, settings: Settings):
        self.settings = settings

    def claim(self) -> Lease | Exhausted | None:
        with connect(self.settings) as connection:
            row = connection.execute(
                """SELECT j.event_id, j.attempts, e.payload, e.correlation_id, j.status
                   FROM event_jobs j JOIN inbound_events e ON e.id = j.event_id
                   WHERE (j.status = 'pending' AND j.next_run_at <= clock_timestamp())
                      OR (j.status = 'processing' AND j.lease_expires_at <= clock_timestamp())
                   ORDER BY j.next_run_at, j.created_at, j.event_id
                   LIMIT 1 FOR UPDATE OF j SKIP LOCKED"""
            ).fetchone()
            if row is None:
                return None
            event_id, attempts, payload, correlation_id, previous_status = row
            if attempts >= self.settings.worker_max_attempts:
                connection.execute(
                    """UPDATE event_jobs SET status = 'failed', lease_token = NULL,
                       lease_expires_at = NULL, last_error = 'attempts_exhausted',
                       updated_at = clock_timestamp() WHERE event_id = %s""",
                    (event_id,),
                )
                audit(
                    connection,
                    event_id,
                    "job_failed",
                    {"attempt": attempts, "error": "attempts_exhausted"},
                )
                return Exhausted(event_id)
            token = uuid4()
            connection.execute(
                """UPDATE event_jobs SET status = 'processing', attempts = attempts + 1,
                   lease_token = %s,
                   lease_expires_at = clock_timestamp() + %s * interval '1 second',
                   updated_at = clock_timestamp() WHERE event_id = %s""",
                (token, self.settings.worker_lease_seconds, event_id),
            )
            audit(
                connection,
                event_id,
                "job_reclaimed" if previous_status == "processing" else "job_started",
                {"attempt": attempts + 1},
            )
        return Lease(event_id, token, attempts + 1, payload, correlation_id)

    def finish(self, lease: Lease, *, result: dict | None = None, error: str | None = None) -> bool:
        if (result is None) == (error is None):
            raise ValueError("Provide exactly one result or error")
        if error not in (None, "processor_error", "processor_timeout", "invalid_event"):
            raise ValueError("Unsupported error code")
        status = (
            "completed"
            if error is None
            else (
                "failed"
                if lease.attempt >= self.settings.worker_max_attempts or error == "invalid_event"
                else "pending"
            )
        )
        delay = min(60, self.settings.worker_retry_seconds * 2 ** (lease.attempt - 1))
        with connect(self.settings) as connection:
            changed = connection.execute(
                """UPDATE event_jobs SET status = %s, result = %s, last_error = %s,
                   next_run_at = clock_timestamp() + %s * interval '1 second',
                   lease_token = NULL, lease_expires_at = NULL, updated_at = clock_timestamp()
                   WHERE event_id = %s AND status = 'processing' AND lease_token = %s
                     AND lease_expires_at > clock_timestamp() RETURNING event_id""",
                (
                    status,
                    Jsonb(result) if result is not None else None,
                    error,
                    delay,
                    lease.event_id,
                    lease.token,
                ),
            ).fetchone()
            if changed is None:
                return False
            action = {
                "pending": "job_retry_scheduled",
                "completed": "job_completed",
                "failed": "job_failed",
            }[status]
            audit(connection, lease.event_id, action, {"attempt": lease.attempt, "error": error})
        return True
