"""Durable Jira delivery: ambiguous writes are reconciled, never blindly replayed."""

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from assistops.business import BusinessTools, fingerprint
from assistops.events import EventError
from assistops.jira import JiraClient, JiraError
from assistops.jobs import audit
from assistops.storage import connect


def save_result(connection, proposal, state, *, key=None, error=None, delay=0):
    connection.execute(
        """UPDATE ticket_deliveries SET status = %s, issue_key = %s, error_code = %s,
           next_run_at = clock_timestamp() + %s * interval '1 second',
           updated_at = clock_timestamp() WHERE proposal_id = %s""",
        (state, key, error, delay, proposal["id"]),
    )
    result = BusinessTools.proposal_result(connection, proposal)
    status = {
        "pending": "awaiting_delivery",
        "sending": "awaiting_delivery",
        "succeeded": "completed",
        "failed": "failed",
        "uncertain": "delivery_uncertain",
    }[state]
    connection.execute(
        """UPDATE event_jobs SET status = %s, result = %s, last_error = %s,
           updated_at = clock_timestamp() WHERE event_id = %s""",
        (status, Jsonb(result), error, proposal["event_id"]),
    )
    audit(
        connection,
        proposal["event_id"],
        "jira_delivery_" + state,
        {"proposal_id": str(proposal["id"]), "issue_key": key, "error_code": error},
    )


def verify_destination(settings, proposal):
    target = proposal["arguments"]["ticket_target"]
    if proposal["tenant_id"] != settings.jira_tenant_id or target != {
        "provider": "jira",
        "site": settings.jira_site,
        "cloud_id": settings.jira_cloud_id,
        "project": settings.jira_project_key,
        "issue_type_id": settings.jira_issue_type_id,
    }:
        raise JiraError("jira_destination_changed")


def deliver_once(settings, client_factory=JiraClient):
    if settings.ticket_backend != "jira":
        return False
    with connect(settings) as connection:
        with connection.cursor(row_factory=dict_row) as cursor:
            proposal = cursor.execute(
                """SELECT p.*, e.tenant_id, e.connector_id, e.payload->>'user_id' AS requester_id,
                          d.status AS delivery_status, d.attempts
                   FROM ticket_deliveries d JOIN ticket_proposals p ON p.id = d.proposal_id
                   JOIN inbound_events e ON e.id = p.event_id
                   WHERE (d.status = 'pending' AND d.next_run_at <= clock_timestamp())
                      OR (d.status = 'sending'
                          AND d.started_at < clock_timestamp() - interval '2 minutes')
                   ORDER BY d.next_run_at LIMIT 1 FOR UPDATE OF d SKIP LOCKED"""
            ).fetchone()
        if not proposal:
            return False
        if proposal["delivery_status"] == "sending":
            save_result(connection, proposal, "uncertain", error="jira_delivery_interrupted")
            return True
        try:
            verify_destination(settings, proposal)
            if proposal["status"] != "approved":
                raise JiraError("jira_approval_required")
            if proposal["arguments_hash"] != fingerprint(
                proposal["event_id"],
                proposal["tenant_id"],
                proposal["requester_id"],
                proposal["connector_id"],
                proposal["arguments"],
            ):
                raise JiraError("jira_proposal_changed")
            invoice = BusinessTools(settings).record(
                "invoices",
                proposal["tenant_id"],
                proposal["requester_id"],
                proposal["arguments"]["invoice_id"],
            )
            if invoice["customer_id"] != proposal["arguments"]["customer_id"]:
                raise JiraError("jira_proposal_changed")
            if "ticket_approver" not in BusinessTools(settings).roles(
                proposal["tenant_id"], proposal["decided_by"]
            ):
                raise JiraError("jira_approver_revoked")
            client = client_factory(settings)
        except (JiraError, EventError) as exc:
            save_result(connection, proposal, "failed", error=exc.code)
            return True
        connection.execute(
            """UPDATE ticket_deliveries SET status = 'sending', attempts = attempts + 1,
               started_at = clock_timestamp(), updated_at = clock_timestamp()
               WHERE proposal_id = %s""",
            (proposal["id"],),
        )
        audit(
            connection,
            proposal["event_id"],
            "jira_delivery_started",
            {"proposal_id": str(proposal["id"])},
        )
    # The sending marker must commit before the HTTP call, including across a worker crash.
    state, key, error, delay = "succeeded", None, None, 0
    try:
        key = client.create(proposal)
    except JiraError as exc:
        error = exc.code
        state = "uncertain" if exc.uncertain else "failed"
        if exc.retry_after is not None and proposal["attempts"] < 2:
            state, delay = "pending", exc.retry_after
    finally:
        client.close()
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT status FROM ticket_deliveries WHERE proposal_id = %s FOR UPDATE",
            (proposal["id"],),
        ).fetchone()
        # A late response cannot overwrite a reconciliation or recovered uncertain state.
        if row[0] == "sending":
            save_result(connection, proposal, state, key=key, error=error, delay=delay)
    return True


def reconcile(settings, proposal_id, issue_key, client_factory=JiraClient):
    """Operator recovery only: verify an existing Jira issue; never create a new one."""
    with connect(settings) as connection, connection.cursor(row_factory=dict_row) as cursor:
        proposal = cursor.execute(
            """SELECT p.*, e.tenant_id FROM ticket_proposals p
                   JOIN inbound_events e ON e.id = p.event_id
                   JOIN ticket_deliveries d ON d.proposal_id = p.id
                   WHERE p.id = %s AND d.status = 'uncertain'""",
            (proposal_id,),
        ).fetchone()
    if not proposal:
        raise JiraError("jira_reconciliation_not_allowed")
    verify_destination(settings, proposal)
    client = client_factory(settings)
    try:
        client.verify_issue(proposal, issue_key)
    finally:
        client.close()
    with connect(settings) as connection:
        row = connection.execute(
            "SELECT status FROM ticket_deliveries WHERE proposal_id = %s FOR UPDATE",
            (proposal_id,),
        ).fetchone()
        if row[0] != "uncertain":
            raise JiraError("jira_reconciliation_not_allowed")
        save_result(connection, proposal, "succeeded", key=issue_key)
        audit(
            connection,
            proposal["event_id"],
            "jira_delivery_reconciled",
            {"proposal_id": str(proposal_id), "issue_key": issue_key, "actor": "operator_cli"},
        )
