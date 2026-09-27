"""Bounded routing context from completed, privately scoped conversation turns."""

import json

from assistops.storage import connect

MAX_TURNS = 4
MAX_CONTEXT_BYTES = 4000
REMEMBERED_OUTCOMES = {
    "answered",
    "read_completed",
    "clarification_required",
    "awaiting_approval",
    "ticket_created",
    "rejected",
    "expired",
}


def bounded_context(rows, access_scope):
    """Read newest first, keeping whole turns and stopping at a permission boundary."""
    turns = []
    for message, plan, result, scope in rows[:MAX_TURNS]:
        if scope != access_scope or result.get("outcome") not in REMEMBERED_OUTCOMES:
            break
        # Never replay generated answers, retrieved documents, profiles or invoice amounts.
        turn = {"message": message, "outcome": result["outcome"]}
        for key in ("invoice_id", "target_user_id", "document_question"):
            if plan.get(key) is not None:
                turn[key] = plan[key]
        if plan.get("clarification") != "none":
            turn["clarification"] = plan["clarification"]
        candidate = [turn, *turns]
        if len(json.dumps(candidate, ensure_ascii=False).encode("utf-8")) > MAX_CONTEXT_BYTES:
            break
        turns = candidate
    return turns


class ConversationMemory:
    def __init__(self, settings):
        self.settings = settings

    def load(self, event_id, access_scope):
        with connect(self.settings) as connection:
            rows = connection.execute(
                """SELECT previous.payload->>'message', p.plan, j.result, p.access_fingerprint
                   FROM inbound_events current
                   JOIN inbound_events previous
                     ON previous.tenant_id = current.tenant_id
                    AND previous.connector_id = current.connector_id
                    AND previous.source = current.source
                    AND previous.payload->>'user_id' = current.payload->>'user_id'
                    AND previous.payload->>'conversation_id' = current.payload->>'conversation_id'
                    AND (previous.received_at, previous.id) < (current.received_at, current.id)
                   JOIN supervisor_plans p ON p.event_id = previous.id
                   JOIN event_jobs j ON j.event_id = previous.id
                   WHERE current.id = %s AND j.status IN ('completed', 'awaiting_approval')
                     AND j.result->>'processor' = 'supervisor'
                   ORDER BY previous.received_at DESC, previous.id DESC LIMIT %s""",
                (event_id, MAX_TURNS),
            ).fetchall()
        return bounded_context(rows, access_scope)
