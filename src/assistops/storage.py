import hashlib
import json
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from assistops.config import Settings
from assistops.events import EventError, EventInput, JobStatus, Receipt, StatusQuery


def connect(settings: Settings):
    connection = psycopg.connect(
        settings.database_url.get_secret_value(),
        connect_timeout=3,
    )
    try:
        connection.isolation_level = psycopg.IsolationLevel.READ_COMMITTED
        connection.execute("SET statement_timeout = '5s'")
        connection.execute("SET lock_timeout = '3s'")
    except BaseException:
        connection.close()
        raise
    return connection


class EventStore:
    def __init__(self, settings: Settings):
        self.settings = settings

    def status(self, query: StatusQuery, connector_id: str) -> JobStatus | None:
        with connect(self.settings) as connection:
            row = connection.execute(
                """SELECT j.event_id, j.status, j.attempts, j.result, j.last_error
                   FROM event_jobs j JOIN inbound_events e ON e.id = j.event_id
                   WHERE e.id = %s AND e.tenant_id = %s AND e.source = %s
                     AND e.payload->>'user_id' = %s AND e.connector_id = %s""",
                (query.receipt_id, query.tenant_id, query.source, query.user_id, connector_id),
            ).fetchone()
        if row is None:
            return None
        return JobStatus(
            receipt_id=row[0], status=row[1], attempts=row[2], result=row[3], last_error=row[4]
        )

    def accept(self, event: EventInput, connector_id: str, correlation_id: str) -> Receipt:
        payload = event.model_dump()
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
        receipt_id = uuid4()
        with connect(self.settings) as connection:
            inserted = connection.execute(
                """INSERT INTO inbound_events
                   (id, tenant_id, source, event_id, payload_hash, payload,
                    connector_id, correlation_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (tenant_id, source, event_id) DO NOTHING RETURNING id""",
                (
                    receipt_id,
                    event.tenant_id,
                    event.source,
                    event.event_id,
                    fingerprint,
                    Jsonb(payload),
                    connector_id,
                    correlation_id,
                ),
            ).fetchone()
            duplicate = inserted is None
            if duplicate:
                # A separate statement sees the committed winner after a concurrent conflict.
                existing = connection.execute(
                    """SELECT id, payload_hash FROM inbound_events
                       WHERE tenant_id = %s AND source = %s AND event_id = %s""",
                    (event.tenant_id, event.source, event.event_id),
                ).fetchone()
                if existing is None:
                    raise psycopg.OperationalError("Event disappeared during acceptance")
                receipt_id, existing_hash = existing
                if existing_hash != fingerprint:
                    raise EventError(409, "event_id_conflict")
            else:
                connection.execute("INSERT INTO event_jobs (event_id) VALUES (%s)", (receipt_id,))
                connection.execute(
                    """INSERT INTO event_audit (event_id, action, connector_id, correlation_id)
                       VALUES (%s, 'event_received', %s, %s)""",
                    (receipt_id, connector_id, correlation_id),
                )
        # The context manager committed all three records before any 202 is returned.
        return Receipt(receipt_id=receipt_id, event_id=event.event_id, duplicate=duplicate)
