import asyncio
import json
from threading import Event
from unittest.mock import Mock
from uuid import uuid4

import pytest
import requests
from langsmith import Client
from pydantic import SecretStr, ValidationError
from requests.adapters import BaseAdapter
from test_worker import store_for

from assistops.config import Settings
from assistops.tracing import (
    TraceExporter,
    TraceSession,
    correlation_ref,
    record,
    safe_metadata,
    span,
    traced,
    tracing_session,
)
from assistops.worker import run_once


def enable(settings):
    settings.langsmith_enabled = True
    settings.langsmith_api_key = SecretStr("langsmith-secret-sentinel")
    return settings


def test_disabled_tracing_ignores_ambient_opt_in(settings, monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    client = Mock(side_effect=AssertionError("No client when disabled"))
    with tracing_session(settings, client), span("worker"):
        record({"message": "private"})
    client.assert_not_called()


def test_metadata_is_an_allowlist_of_values_not_only_names():
    data = safe_metadata(
        {
            "outcome": {"secret": "private"},
            "attempt": True,
            "input_tokens": -1,
            "ls_model_name": "private",
            "correlation_ref": "private",
            "event_id": "private",
            "estimated_cost_usd": float("nan"),
            "user_id": "private",
            "usage_metadata": {"input_tokens": 10, "output_tokens": 2, "secret": "private"},
        }
    )
    assert data == {
        "redaction_policy": "metrics-only-v1",
        "usage_metadata": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
    }


def test_redirect_does_not_forward_api_key():
    calls = []

    class Redirect(BaseAdapter):
        def send(self, request, **kwargs):
            calls.append(request.url)
            response = requests.Response()
            # Match a real adapter: requests inspects the original request even without redirects.
            response.request = request
            response.url = request.url
            response.status_code, response._content = 302, b""
            response.headers["Location"] = "https://untrusted.invalid/runs"
            return response

        def close(self):
            pass

    with TraceSession() as session:
        session.mount("https://", Redirect())
        with pytest.raises(requests.HTTPError, match="redirects"):
            session.post("https://configured.invalid/runs", headers={"x-api-key": "fake-secret"})
    assert calls == ["https://configured.invalid/runs"]


def test_nested_spans_propagate_across_asyncio_threads(settings):
    client = Mock()
    event_id = str(uuid4())

    @traced("retrieve")
    def read_secret():
        return {"documents": ["private document"]}

    @traced("rag")
    async def rag():
        await asyncio.to_thread(read_secret)
        return {
            "outcome": "answered",
            "message": "private answer",
            "usage": {
                "embedding_tokens": 12,
                "input_tokens": 30,
                "output_tokens": 5,
                "estimated_cost_usd": 0.00002,
            },
        }

    with (
        tracing_session(enable(settings), lambda **_: client),
        span("worker", event_id=event_id, correlation_ref=correlation_ref("private-id")),
    ):
        asyncio.run(rag())
    runs = {c.kwargs["name"]: c.kwargs for c in client.create_run.call_args_list}
    assert runs["retrieve"]["parent_run_id"] == runs["rag"]["id"]
    assert runs["rag"]["parent_run_id"] == runs["worker"]["id"]
    assert len({r["trace_id"] for r in runs.values()}) == 1
    assert all(r["extra"]["metadata"]["event_id"] == event_id for r in runs.values())
    assert "private" not in json.dumps(list(runs.values()), default=str)
    assert runs["rag"]["extra"]["metadata"]["embedding_tokens"] == 12


def test_concurrent_requests_have_distinct_trace_trees(settings):
    client = Mock()

    async def request():
        with span("worker"):
            await asyncio.sleep(0)
            with span("tools"):
                await asyncio.sleep(0)

    async def both():
        await asyncio.gather(request(), request())

    with tracing_session(enable(settings), lambda **_: client):
        asyncio.run(both())
    runs = [c.kwargs for c in client.create_run.call_args_list]
    roots = {r["id"] for r in runs if r["name"] == "worker"}
    assert len(roots) == 2
    assert {r["parent_run_id"] for r in runs if r["name"] == "tools"} == roots


@pytest.mark.parametrize("cancel", [False, True])
def test_error_and_cancellation_export_no_exception_text(settings, cancel):
    client = Mock()

    @traced("tools")
    async def broken():
        if cancel:
            raise asyncio.CancelledError("private cancellation")
        raise RuntimeError("private exception with token")

    with (
        tracing_session(enable(settings), lambda **_: client),
        pytest.raises(asyncio.CancelledError if cancel else RuntimeError),
    ):
        asyncio.run(broken())
    run = client.create_run.call_args.kwargs
    assert run["error"] == ("cancelled" if cancel else "operation_failed")
    assert "private" not in json.dumps(run, default=str)


def test_export_failure_does_not_fail_business_job(settings, capsys):
    store = store_for(settings)
    client = Mock()
    client.create_run.side_effect = RuntimeError("private token from transport")

    async def processor(_):
        return {"outcome": "acknowledged", "message": "private response"}

    with tracing_session(enable(settings), lambda **_: client) as exporter:
        assert asyncio.run(run_once(store, processor))
    assert store.finish.call_args.kwargs["result"]["message"] == "private response"
    assert exporter.failed == 1
    assert "private" not in capsys.readouterr().out


def test_queue_is_bounded_and_does_not_wait_for_slow_export(settings):
    started, release = Event(), Event()
    client = Mock()

    def slow(**_):
        started.set()
        assert release.wait(5)

    client.create_run.side_effect = slow
    exporter = TraceExporter(enable(settings), lambda **_: client)
    try:
        exporter.submit({"name": "worker"})
        assert started.wait(2)
        for _ in range(300):
            exporter.submit({"name": "worker"})
        assert exporter.queue.qsize() == 256
        assert exporter.dropped == 44
    finally:
        release.set()
        exporter.close()


def test_real_sdk_serializes_only_safe_content(settings, monkeypatch):
    monkeypatch.setenv("LANGSMITH_METADATA", '{"secret":"ambient-secret"}')
    monkeypatch.setenv("LANGCHAIN_PROJECT", "ambient-secret")
    payloads = []

    class Capture(BaseAdapter):
        def send(self, request, **kwargs):
            assert request.url == "https://api.smith.langchain.com/runs"
            payloads.append(json.loads(request.body))
            response = requests.Response()
            response.status_code, response._content = 200, b"{}"
            return response

        def close(self):
            pass

    def client_factory(**kwargs):
        session = kwargs["session"]
        client = Client(**kwargs)
        # The SDK installs its own adapters during construction.
        session.mount("https://", Capture())
        return client

    with tracing_session(enable(settings), client_factory), span("generation"):
        record(
            {
                "usage": {"input_tokens": 12, "output_tokens": 3},
                "output": "private model response",
                "secret": "private key",
            }
        )
    assert len(payloads) == 1
    encoded = json.dumps(payloads)
    assert "private" not in encoded and "ambient-secret" not in encoded
    assert "langsmith-secret-sentinel" not in encoded
    assert payloads[0]["inputs"] == payloads[0]["outputs"] == {}
    assert payloads[0]["extra"]["metadata"]["usage_metadata"]["total_tokens"] == 15
    assert "runtime" not in payloads[0]["extra"]


def test_self_hosted_endpoint_and_cloud_credentials_validation():
    local = Settings(
        _env_file=None, langsmith_enabled=True, langsmith_endpoint="http://localhost:1984/api"
    )
    assert local.langsmith_enabled
    with pytest.raises(ValidationError):
        Settings(_env_file=None, langsmith_enabled=True)
    for url in ("https://user:secret@example.org", "https://example.org?secret=key", "file:///tmp"):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, langsmith_endpoint=url)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="production", langsmith_endpoint="http://local:1984")


@pytest.mark.integration
def test_actual_supervisor_tree_excludes_graph_state(database, monkeypatch):
    import httpx
    from test_business import enable as enable_business
    from test_supervisor import plan, request

    from assistops.jobs import JobStore
    from assistops.storage import EventStore
    from assistops.supervisor import SupervisorProcessor

    enable(enable_business(database))
    database.openai_api_key = SecretStr("openai-secret-sentinel")
    database.worker_processor = "supervisor"
    processor = SupervisorProcessor(database)
    processor.router.transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "status": "completed",
                "usage": {"input_tokens": 15, "output_tokens": 12},
                "output": [
                    {"content": [{"type": "output_text", "text": plan().model_dump_json()}]}
                ],
            },
        )
    )
    event = request("Consulte INV-001. private-message-sentinel")
    EventStore(database).accept(event, "demo", "private-correlation-sentinel")
    client = Mock()
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    with tracing_session(database, lambda **_: client):
        assert asyncio.run(run_once(JobStore(database), processor))
    runs = {call.kwargs["name"]: call.kwargs for call in client.create_run.call_args_list}
    assert set(runs) == {"worker", "supervisor", "route", "generation", "tools"}
    assert runs["generation"]["parent_run_id"] == runs["route"]["id"]
    assert runs["route"]["parent_run_id"] == runs["supervisor"]["id"]
    assert runs["tools"]["parent_run_id"] == runs["supervisor"]["id"]
    assert runs["supervisor"]["parent_run_id"] == runs["worker"]["id"]
    encoded = json.dumps(runs, default=str)
    for secret in (
        "private-message",
        "private-correlation",
        "INV-001",
        "user-001",
        "openai-secret",
        "langsmith-secret",
        "amount_minor",
    ):
        assert secret not in encoded
    assert runs["generation"]["extra"]["metadata"]["usage_metadata"]["total_tokens"] == 27
    assert runs["worker"]["extra"]["metadata"]["job_saved"] is True
