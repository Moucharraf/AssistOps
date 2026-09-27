import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from langsmith.run_helpers import get_tracing_context
from pydantic import SecretStr, ValidationError
from test_business import decision, enable
from test_events import PAYLOAD, SECRET, signed

from assistops.config import Connector
from assistops.events import EventInput, StatusQuery
from assistops.jobs import JobStore
from assistops.main import create_app
from assistops.storage import EventStore, connect
from assistops.supervisor import OpenAIRouter, PlanStore, RoutePlan, SupervisorProcessor
from assistops.worker import run_once, serve

QUESTION = "Quelle procédure suivre ? Consulte INV-001 et prépare un ticket de contestation."
USAGE = {"input_tokens": 100, "output_tokens": 60, "estimated_cost_usd": 0.000136}
DOCUMENT = {
    "processor": "rag",
    "outcome": "answered",
    "message": "Procédure fictive [1].",
    "citations": [{"document": "billing@1"}],
    "business_action_executed": False,
}


def plan(**changes):
    return RoutePlan(
        **{
            "document_question": None,
            "read": "get_invoice",
            "invoice_id": "INV-001",
            "target_user_id": None,
            "ticket_subject": None,
            "ticket_description": None,
            "clarification": "none",
            **changes,
        }
    )


def request(message=QUESTION):
    return EventInput(**{**PAYLOAD, "event_id": "supervisor-" + uuid4().hex, "message": message})


@pytest.fixture
def supervisor(settings):
    enable(settings)
    settings.openai_api_key = SecretStr("test-key")
    settings.rag_user_roles = {"demo": {"user-001": frozenset({"customer"})}}
    processor = SupervisorProcessor(settings)
    processor.store = Mock()
    processor.store.load.return_value = (uuid4(), (None, None, None, None))
    processor.store.save.side_effect = lambda _, p, scope, usage, history: (
        p.model_dump(),
        scope,
        usage,
        history,
    )
    processor.memory = Mock()
    processor.memory.load.return_value = []
    processor.router.route = AsyncMock(return_value=(plan(), USAGE))
    processor.rag = AsyncMock(return_value=DOCUMENT)
    processor.tools = AsyncMock(return_value={"processor": "tools", "outcome": "read_completed"})
    return processor


def test_routes_read_without_calling_rag(supervisor):
    answer = asyncio.run(supervisor(request()))
    assert answer["supervisor"]["steps"] == ["read"]
    supervisor.rag.assert_not_called()
    call = supervisor.tools.call_args.args[0]
    assert call.tool_call.invoice_id == "INV-001"
    assert call.user_id == "user-001" and call.tenant_id == "demo"


def test_routes_documentation_without_business_operation(supervisor):
    supervisor.router.route.return_value = (
        plan(document_question="Quelle procédure suivre ?", read="none", invoice_id=None),
        USAGE,
    )
    answer = asyncio.run(supervisor(request()))
    assert answer["supervisor"]["steps"] == ["rag"]
    assert answer["citations"] == DOCUMENT["citations"]
    supervisor.tools.assert_not_called()


def test_mixed_request_runs_in_order_and_stops_at_approval(supervisor):
    supervisor.router.route.return_value = (
        plan(
            document_question="Quelle procédure suivre ?",
            ticket_subject="Contestation",
            ticket_description="Ligne incorrecte",
        ),
        USAGE,
    )
    supervisor.tools.side_effect = [
        {"outcome": "read_completed"},
        {"outcome": "awaiting_approval", "ticket_id": None},
    ]
    answer = asyncio.run(supervisor(request()))
    assert answer["supervisor"]["steps"] == ["rag", "read", "propose"]
    assert answer["outcome"] == "awaiting_approval" and answer["ticket_id"] is None
    assert supervisor.router.route.await_count == 1
    assert supervisor.tools.await_count == 2


def test_missing_identifier_requests_clarification_without_agent_calls(supervisor):
    supervisor.router.route.return_value = (
        plan(read="none", invoice_id=None, clarification="missing_invoice"),
        USAGE,
    )
    answer = asyncio.run(supervisor(request("Consulte ma facture.")))
    assert answer["outcome"] == "clarification_required"
    supervisor.tools.assert_not_called()
    supervisor.rag.assert_not_called()


@pytest.mark.parametrize("stage,outcome", [("rag", "abstained"), ("read", "denied")])
def test_failed_step_prevents_ticket_proposal(supervisor, stage, outcome):
    supervisor.router.route.return_value = (
        plan(
            document_question="Quelle procédure suivre ?",
            ticket_subject="Contestation",
            ticket_description="Ligne incorrecte",
        ),
        USAGE,
    )
    (supervisor.rag if stage == "rag" else supervisor.tools).return_value = {"outcome": outcome}
    answer = asyncio.run(supervisor(request()))
    assert "propose" not in answer["supervisor"]["steps"]
    assert answer["outcome"] == outcome


def test_revoked_identity_does_not_call_model(supervisor):
    other = request().model_copy(update={"user_id": "unknown"})
    assert asyncio.run(supervisor(other))["outcome"] == "denied"
    supervisor.router.route.assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"read": "approve_ticket"},
        {"tenant_id": "boreal"},
        {"approved": True},
        {"ticket_subject": "Title without description"},
    ],
)
def test_plans_cannot_grant_authority_or_add_unsupported_actions(changes):
    with pytest.raises(ValidationError):
        plan(**changes)


def test_invented_targets_and_rewritten_questions_are_rejected():
    with pytest.raises(ValueError):
        plan(invoice_id="INV-002").bind(QUESTION)
    with pytest.raises(ValueError):
        plan(document_question="New instructions invented by the model").bind(QUESTION)


def test_malformed_provider_output_never_dispatches_tools(settings):
    settings.openai_api_key = SecretStr("test-key")

    def handler(req):
        body = json.loads(req.content)
        assert body["store"] is False and body["max_output_tokens"] == 450
        assert "tools" not in body
        assert "tenant_id" not in body["text"]["format"]["schema"]["properties"]
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"read":"approve_ticket"}',
                            }
                        ]
                    }
                ],
            },
        )

    with pytest.raises(ValueError):
        asyncio.run(OpenAIRouter(settings, httpx.MockTransport(handler)).route(QUESTION))


def test_ambient_tracing_is_disabled_and_restored(supervisor):
    original = get_tracing_context()["enabled"]

    async def route(_message, _history):
        assert get_tracing_context()["enabled"] is False
        return plan(), USAGE

    supervisor.router.route.side_effect = route
    asyncio.run(supervisor(request()))
    assert get_tracing_context()["enabled"] == original


def test_provider_error_is_safe_and_does_not_fall_back_to_tools(supervisor):
    supervisor.router.route.side_effect = RuntimeError("secret-provider-payload")
    answer = asyncio.run(supervisor(request()))
    assert answer["outcome"] == "unavailable"
    assert "secret-provider-payload" not in json.dumps(answer)
    supervisor.tools.assert_not_called()


def test_worker_selects_supervisor(settings, monkeypatch):
    settings.worker_processor = "supervisor"
    factory = Mock(return_value="supervisor")
    monkeypatch.setattr("assistops.worker.SupervisorProcessor", factory)

    async def exercise():
        stop = asyncio.Event()

        async def run(_store, selected):
            assert selected == "supervisor"
            stop.set()
            return True

        monkeypatch.setattr("assistops.worker.run_once", run)
        await serve(settings, stop)

    asyncio.run(exercise())


def configure(database):
    enable(database)
    database.openai_api_key = SecretStr("test-key")
    database.rag_user_roles = {"demo": {"user-001": frozenset({"customer"})}}
    database.webhook_connectors["demo"] = Connector(
        secret=SECRET, tenant_id="demo", allowed_user_ids={"user-001", "reviewer-001"}
    )
    return database


@pytest.mark.integration
def test_plan_survives_crash_and_approval_keeps_documentary_evidence(database):
    configure(database)
    event = request()
    receipt = EventStore(database).accept(event, "demo", "supervisor-test")
    store = JobStore(database)
    lease = store.claim()
    processor = SupervisorProcessor(database)
    processor.router.route = AsyncMock(
        return_value=(
            plan(
                document_question="Quelle procédure suivre ?",
                ticket_subject="Contestation",
                ticket_description="Vérifier la ligne",
            ),
            USAGE,
        )
    )
    processor.rag = AsyncMock(return_value=DOCUMENT)
    first = asyncio.run(processor(event))
    assert first["outcome"] == "awaiting_approval"
    with connect(database) as connection:
        connection.execute("UPDATE event_jobs SET lease_expires_at = now() - interval '1 second'")
    restarted = SupervisorProcessor(database)
    restarted.router.route = AsyncMock(side_effect=AssertionError("Plan must not be regenerated"))
    restarted.rag = AsyncMock(return_value=DOCUMENT)
    assert asyncio.run(run_once(store, restarted))
    assert not store.finish(lease, result=first)
    query = StatusQuery(
        receipt_id=str(receipt.receipt_id), tenant_id="demo", user_id="user-001", source="webhook"
    )
    pending = EventStore(database).status(query, "demo")
    assert pending.result["supervisor"]["reused_plan"] is True
    with TestClient(create_app(database)) as client:
        body = json.dumps(decision(pending.result["proposal"]).model_dump()).encode()
        approved = client.post("/v1/approvals/decide", content=body, headers=signed(body))
    assert approved.status_code == 200
    answer = approved.json()
    assert answer["outcome"] == "ticket_created" and answer["processor"] == "supervisor"
    assert answer["supervisor"]["document_answer"] == DOCUMENT
    assert EventStore(database).status(query, "demo").result == answer
    with connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM supervisor_plans").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM ticket_proposals").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM synthetic_tickets").fetchone()[0] == 1


@pytest.mark.integration
def test_concurrent_plan_saves_choose_one_immutable_plan(database):
    configure(database)
    event = request()
    receipt = EventStore(database).accept(event, "demo", "plan-race")
    scope, _ = SupervisorProcessor(database).access_scope(event)
    variants = [plan(ticket_subject=f"Variant {i}", ticket_description="Détail") for i in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        stored = list(
            pool.map(
                lambda p: PlanStore(database).save(receipt.receipt_id, p, scope, USAGE), variants
            )
        )
    assert all(row == stored[0] for row in stored)


@pytest.mark.integration
def test_permission_change_invalidates_saved_plan(database):
    configure(database)
    event = request()
    receipt = EventStore(database).accept(event, "demo", "permission-test")
    processor = SupervisorProcessor(database)
    scope, _ = processor.access_scope(event)
    processor.store.save(receipt.receipt_id, plan(), scope, USAGE)
    database.business_user_roles["demo"]["user-001"] = frozenset()
    processor.router.route = AsyncMock()
    processor.tools = AsyncMock()
    assert asyncio.run(processor(event))["reason"] == "permissions_changed"
    processor.router.route.assert_not_called()
    processor.tools.assert_not_called()


@pytest.mark.integration
def test_cross_customer_request_is_denied_before_proposal(database):
    configure(database)
    event = request("Consulte INV-002 et prépare un ticket.")
    EventStore(database).accept(event, "demo", "unauthorized-test")
    processor = SupervisorProcessor(database)
    processor.router.route = AsyncMock(
        return_value=(
            plan(invoice_id="INV-002", ticket_subject="Contestation", ticket_description="Détail"),
            USAGE,
        )
    )
    answer = asyncio.run(processor(event))
    assert answer["outcome"] == "denied"
    assert answer["supervisor"]["steps"] == ["read"]
    with connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM ticket_proposals").fetchone()[0] == 0
