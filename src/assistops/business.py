"""Deterministic business tools with a synthetic backend and persistent approval state."""

import asyncio
import hashlib
import json
from importlib.resources import files
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from assistops.config import Settings
from assistops.events import CreateTicket, EventError, EventInput, GetUser
from assistops.jobs import audit
from assistops.storage import connect


def fingerprint(event_id, tenant, requester, connector, arguments):
    bound = [str(event_id), tenant, requester, connector, "create_ticket", arguments]
    return hashlib.sha256(
        json.dumps(bound, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def tool_result(outcome, **data):
    return {
        "processor": "tools",
        "outcome": outcome,
        "origin": "synthetic",
        "business_action_executed": False,
        **data,
    }


class BusinessTools:
    def __init__(self, settings: Settings):
        self.settings = settings

    def enabled(self):
        if (
            self.settings.business_backend != "synthetic"
            or self.settings.environment == "production"
        ):
            raise EventError(503, "business_backend_disabled")

    def roles(self, tenant, user):
        return self.settings.business_user_roles.get(tenant, {}).get(user, frozenset())

    def can_request(self, tenant, user):
        if not self.roles(tenant, user) & {"customer", "support_agent"}:
            raise EventError(403, "business_access_denied")

    def record(self, kind, tenant, user, identifier):
        self.enabled()
        self.can_request(tenant, user)
        fixture = json.loads(
            files("assistops").joinpath("business_fixture.json").read_text("utf-8")
        )
        key = "user_id" if kind == "users" else "invoice_id"
        owner = "user_id" if kind == "users" else "customer_id"
        for item in fixture[kind]:
            if (
                item["tenant_id"] == tenant
                and item[key] == identifier
                and (item[owner] == user or "support_agent" in self.roles(tenant, user))
            ):
                return {**item, "origin": "synthetic"}
        # Unknown and inaccessible records have the same outward behavior.
        raise EventError(404, "business_record_not_found")

    def execute(self, event: EventInput):
        self.enabled()
        self.can_request(event.tenant_id, event.user_id)
        call = event.tool_call
        if call is None:
            raise EventError(422, "tool_call_required")
        if isinstance(call, GetUser):
            data = self.record(
                "users", event.tenant_id, event.user_id, call.target_user_id or event.user_id
            )
        else:
            data = self.record("invoices", event.tenant_id, event.user_id, call.invoice_id)
        with connect(self.settings) as connection:
            row = connection.execute(
                """SELECT id, connector_id FROM inbound_events
                   WHERE tenant_id = %s AND source = %s AND event_id = %s
                     AND payload->>'user_id' = %s""",
                (event.tenant_id, event.source, event.event_id, event.user_id),
            ).fetchone()
            if row is None:
                raise EventError(404, "event_not_found")
            event_id, connector = row
            if not isinstance(call, CreateTicket):
                audit(connection, event_id, "business_read", {"tool": call.name})
                return tool_result("read_completed", data=data)
            # Serialize proposals for this private conversation and invoice, across event IDs.
            # A model repeating an earlier request must not create another approval candidate.
            scope = json.dumps(
                [
                    event.tenant_id,
                    connector,
                    event.source,
                    event.user_id,
                    event.conversation_id,
                    call.invoice_id,
                ]
            )
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (scope,))
            existing = connection.execute(
                "SELECT 1 FROM ticket_proposals WHERE event_id = %s", (event_id,)
            ).fetchone()
            pending = connection.execute(
                """SELECT 1 FROM ticket_proposals p JOIN inbound_events e ON e.id = p.event_id
                   WHERE e.tenant_id = %s AND e.connector_id = %s AND e.source = %s
                     AND e.payload->>'user_id' = %s AND e.payload->>'conversation_id' = %s
                     AND p.arguments->>'invoice_id' = %s AND p.event_id <> %s
                     AND p.status = 'pending' AND p.expires_at > clock_timestamp() LIMIT 1""",
                (
                    event.tenant_id,
                    connector,
                    event.source,
                    event.user_id,
                    event.conversation_id,
                    call.invoice_id,
                    event_id,
                ),
            ).fetchone()
            if pending and not existing:
                audit(
                    connection, event_id, "ticket_proposal_blocked", {"reason": "approval_pending"}
                )
                return tool_result(
                    "clarification_required",
                    reason="approval_pending",
                    message="Une proposition pour cette facture attend déjà une décision. "
                    "Utilisez le canal de validation pour l'approuver ou la refuser.",
                )
            arguments = {
                "invoice_id": call.invoice_id,
                "customer_id": data["customer_id"],
                "subject": call.subject,
                "description": call.description,
            }
            digest = fingerprint(event_id, event.tenant_id, event.user_id, connector, arguments)
            inserted = connection.execute(
                """INSERT INTO ticket_proposals
                   (id, event_id, arguments, arguments_hash, expires_at)
                   VALUES (%s, %s, %s, %s, clock_timestamp() + %s * interval '1 second')
                   ON CONFLICT (event_id) DO NOTHING RETURNING id""",
                (uuid4(), event_id, Jsonb(arguments), digest, self.settings.approval_ttl_seconds),
            ).fetchone()
            with connection.cursor(row_factory=dict_row) as cursor:
                proposal = cursor.execute(
                    "SELECT * FROM ticket_proposals WHERE event_id = %s", (event_id,)
                ).fetchone()
            if proposal["arguments_hash"] != digest:
                raise EventError(409, "proposal_conflict")
            if inserted:
                audit(connection, event_id, "ticket_proposed", {"proposal_id": str(proposal["id"])})
            return self.proposal_result(connection, proposal)

    @staticmethod
    def proposal_result(connection, proposal):
        ticket = connection.execute(
            "SELECT id FROM synthetic_tickets WHERE proposal_id = %s", (proposal["id"],)
        ).fetchone()
        status = proposal["status"]
        result = tool_result(
            {
                "pending": "awaiting_approval",
                "approved": "ticket_created",
                "rejected": "rejected",
                "expired": "expired",
            }[status],
            simulated_action_executed=bool(ticket),
            proposal={
                "id": str(proposal["id"]),
                "status": status,
                "arguments": proposal["arguments"],
                "arguments_hash": proposal["arguments_hash"],
                "expires_at": proposal["expires_at"].isoformat(),
                "decided_by": proposal["decided_by"],
            },
            ticket_id=str(ticket[0]) if ticket else None,
        )
        previous = connection.execute(
            "SELECT result FROM event_jobs WHERE event_id = %s", (proposal["event_id"],)
        ).fetchone()
        if previous and previous[0] and "supervisor" in previous[0]:
            # Keep documentary evidence and routing usage when a human decision completes the job.
            result.update(processor="supervisor", supervisor=previous[0]["supervisor"])
            result["message"] = {
                "pending": "Le ticket est proposé et attend une validation humaine.",
                "approved": "Le ticket simulé a été créé après approbation.",
                "rejected": "La proposition a été refusée. Aucun ticket n’a été créé.",
                "expired": "La proposition a expiré. Aucun ticket n’a été créé.",
            }[status]
        return result

    def review(self, query, connector, correlation_id, decision=None):
        self.enabled()
        roles = self.roles(query.tenant_id, query.user_id)
        if not roles:
            raise EventError(403, "business_access_denied")
        with connect(self.settings) as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                proposal = cursor.execute(
                    """SELECT p.*, e.tenant_id, e.payload->>'user_id' AS requester_id
                       FROM ticket_proposals p JOIN inbound_events e ON e.id = p.event_id
                       WHERE p.id = %s AND e.tenant_id = %s AND e.source = %s
                         AND e.connector_id = %s FOR UPDATE OF p""",
                    (query.proposal_id, query.tenant_id, query.source, connector),
                ).fetchone()
            if proposal is None:
                raise EventError(404, "proposal_not_found")
            requester = proposal["requester_id"]
            if decision is None:
                if "ticket_approver" not in roles and not (
                    query.user_id == requester and roles & {"customer", "support_agent"}
                ):
                    raise EventError(404, "proposal_not_found")
            elif "ticket_approver" not in roles or query.user_id == requester:
                raise EventError(403, "approval_not_allowed")

            # Approval must refer to the exact immutable proposal displayed to the reviewer.
            if decision is not None:
                expected = fingerprint(
                    proposal["event_id"],
                    query.tenant_id,
                    requester,
                    connector,
                    proposal["arguments"],
                )
                if expected != proposal["arguments_hash"] or query.arguments_hash != expected:
                    raise EventError(409, "proposal_changed")
            job = connection.execute(
                "SELECT status FROM event_jobs WHERE event_id = %s FOR UPDATE",
                (proposal["event_id"],),
            ).fetchone()
            if proposal["status"] == "pending":
                if job[0] != "awaiting_approval":
                    raise EventError(409, "proposal_not_ready")
                expired = connection.execute(
                    "SELECT expires_at <= clock_timestamp() FROM ticket_proposals WHERE id = %s",
                    (proposal["id"],),
                ).fetchone()[0]
                status = "expired" if expired else decision
                if status is not None:
                    if status == "approved":
                        # Recheck the requester's current permissions immediately before execution.
                        invoice = self.record(
                            "invoices",
                            query.tenant_id,
                            requester,
                            proposal["arguments"]["invoice_id"],
                        )
                        if invoice["customer_id"] != proposal["arguments"]["customer_id"]:
                            raise EventError(409, "proposal_changed")
                        args = proposal["arguments"]
                        connection.execute(
                            """INSERT INTO synthetic_tickets
                               (id, proposal_id, tenant_id, customer_id,
                                invoice_id, subject, description)
                               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                            (
                                uuid4(),
                                proposal["id"],
                                query.tenant_id,
                                args["customer_id"],
                                args["invoice_id"],
                                args["subject"],
                                args["description"],
                            ),
                        )
                    connection.execute(
                        """UPDATE ticket_proposals SET status = %s, decided_by = %s,
                           decided_at = clock_timestamp() WHERE id = %s""",
                        (status, query.user_id if status != "expired" else None, proposal["id"]),
                    )
                    proposal.update(
                        status=status, decided_by=query.user_id if status != "expired" else None
                    )
                    answer = self.proposal_result(connection, proposal)
                    # Simulator ticket, decision, job result and audit commit atomically.
                    connection.execute(
                        """UPDATE event_jobs SET status = 'completed', result = %s,
                           updated_at = clock_timestamp() WHERE event_id = %s""",
                        (Jsonb(answer), proposal["event_id"]),
                    )
                    audit(
                        connection,
                        proposal["event_id"],
                        "ticket_" + status,
                        {
                            "proposal_id": str(proposal["id"]),
                            "actor_id": query.user_id,
                            "decision_correlation_id": correlation_id,
                            "ticket_id": answer["ticket_id"],
                            "origin": "synthetic",
                        },
                    )
            elif decision is not None and proposal["status"] not in (decision, "expired"):
                raise EventError(409, "decision_conflict")
            return self.proposal_result(connection, proposal)


class ToolsProcessor:
    def __init__(self, settings: Settings):
        self.tools = BusinessTools(settings)

    async def __call__(self, event: EventInput):
        try:
            return await asyncio.to_thread(self.tools.execute, event)
        except EventError as exc:
            return tool_result("unavailable" if exc.status == 503 else "denied", reason=exc.code)
