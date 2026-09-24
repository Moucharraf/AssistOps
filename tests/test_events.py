import asyncio
import hashlib
import hmac
import json
import time
from unittest.mock import Mock
from uuid import uuid4

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from assistops.config import Connector
from assistops.events import EventError, Receipt

SECRET = "test-only-secret-with-at-least-32-characters"
PAYLOAD = {
    "event_id": "evt-001",
    "tenant_id": "demo",
    "user_id": "user-001",
    "conversation_id": "conversation-001",
    "source": "webhook",
    "message": "Facture INV-001",
}


def signed(body, timestamp=None, secret=SECRET):
    timestamp = str(int(time.time())) if timestamp is None else str(timestamp)
    signature = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return {
        "Content-Type": "application/json",
        "X-AssistOps-Connector": "demo",
        "X-AssistOps-Timestamp": timestamp,
        "X-AssistOps-Signature": "v1=" + signature.hexdigest(),
    }


@pytest.fixture
def webhook_app(app):
    app.state.settings.webhook_connectors = {
        "demo": Connector(secret=SECRET, tenant_id="demo", allowed_user_ids={"user-001"})
    }
    app.state.event_store = Mock()
    app.state.event_store.accept.return_value = Receipt(
        receipt_id=uuid4(), event_id="evt-001", duplicate=False
    )
    return app


def test_signed_event_returns_receipt_after_storage(webhook_app):
    body = json.dumps(PAYLOAD).encode()
    with TestClient(webhook_app) as client:
        response = client.post("/v1/events", content=body, headers=signed(body))
    assert response.status_code == 202
    assert response.json()["status"] == "received"
    assert response.json()["duplicate"] is False
    event, connector, correlation = webhook_app.state.event_store.accept.call_args.args
    assert event.model_dump() == PAYLOAD
    assert connector == "demo"
    assert correlation == response.headers["X-Correlation-ID"]


@pytest.mark.parametrize(
    "case", ["missing", "wrong", "expired", "future", "tampered", "unknown", "timestamp"]
)
def test_invalid_auth_never_reaches_storage(webhook_app, case):
    body = json.dumps(PAYLOAD).encode()
    headers = signed(body)
    if case == "missing":
        del headers["X-AssistOps-Signature"]
    elif case == "wrong":
        headers = signed(body, secret="wrong-secret")
    elif case in ("expired", "future"):
        headers = signed(body, timestamp=int(time.time()) + (600 if case == "future" else -600))
    elif case == "tampered":
        body += b" "
    elif case == "unknown":
        headers["X-AssistOps-Connector"] = "unknown"
    elif case == "timestamp":
        headers["X-AssistOps-Timestamp"] = "invalid"
    with TestClient(webhook_app) as client:
        assert client.post("/v1/events", content=body, headers=headers).status_code == 401
    webhook_app.state.event_store.accept.assert_not_called()


@pytest.mark.parametrize(
    "field,value", [("tenant_id", "other"), ("user_id", "other"), ("source", "email")]
)
def test_connector_scope_enforced(webhook_app, field, value):
    body = json.dumps({**PAYLOAD, field: value}).encode()
    with TestClient(webhook_app) as client:
        assert client.post("/v1/events", content=body, headers=signed(body)).status_code == 403
    webhook_app.state.event_store.accept.assert_not_called()


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b"[]",
        b"\xff",
        b'{"event_id":"one","event_id":"two"}',
        json.dumps({**PAYLOAD, "message": " "}).encode(),
        json.dumps({**PAYLOAD, "unexpected": True}).encode(),
        json.dumps({**PAYLOAD, "event_id": 1}).encode(),
    ],
)
def test_invalid_json_or_schema_rejected(webhook_app, body):
    with TestClient(webhook_app) as client:
        response = client.post("/v1/events", content=body, headers=signed(body))
    assert response.status_code == 422
    webhook_app.state.event_store.accept.assert_not_called()


def test_chunked_body_size_is_bounded(webhook_app):
    body = b"x" * (65536 + 1)
    with TestClient(webhook_app) as client:
        response = client.post(
            "/v1/events", content=iter([body[:32768], body[32768:]]), headers=signed(body)
        )
    assert response.status_code == 413
    webhook_app.state.event_store.accept.assert_not_called()


def test_duplicate_auth_header_rejected(webhook_app):
    body = json.dumps(PAYLOAD).encode()
    headers = list(signed(body).items()) + [("X-AssistOps-Connector", "demo")]
    with TestClient(webhook_app) as client:
        assert client.post("/v1/events", content=body, headers=headers).status_code == 401
    webhook_app.state.event_store.accept.assert_not_called()


@pytest.mark.parametrize(
    "name,value", [("Content-Type", "text/plain"), ("Content-Encoding", "gzip")]
)
def test_unsupported_encoding_or_media_type(webhook_app, name, value):
    body = json.dumps(PAYLOAD).encode()
    headers = {**signed(body), name: value}
    with TestClient(webhook_app) as client:
        assert client.post("/v1/events", content=body, headers=headers).status_code == 415


@pytest.mark.parametrize(
    "exception,status",
    [
        (psycopg.OperationalError("secret-dsn"), 503),
        (EventError(409, "event_id_conflict"), 409),
    ],
)
def test_storage_failure_is_not_acknowledged(webhook_app, capsys, exception, status):
    webhook_app.state.event_store.accept.side_effect = exception
    body = json.dumps(PAYLOAD).encode()
    with TestClient(webhook_app) as client:
        response = client.post("/v1/events", content=body, headers=signed(body))
    assert response.status_code == status
    assert "secret-dsn" not in response.text + capsys.readouterr().out


def test_unconfigured_endpoint_fails_closed(client):
    assert client.post("/v1/events", json=PAYLOAD).status_code == 503


@pytest.mark.parametrize("message", ["bad\u0000text", "bad\ud800text"])
def test_unstorable_unicode_is_rejected(webhook_app, message):
    body = json.dumps({**PAYLOAD, "message": message}).encode()
    with TestClient(webhook_app) as client:
        response = client.post("/v1/events", content=body, headers=signed(body))
    assert response.status_code == 422
    webhook_app.state.event_store.accept.assert_not_called()


def test_slow_body_times_out(webhook_app):
    webhook_app.state.settings.webhook_body_timeout_seconds = 0.1

    async def slow_body():
        yield b"{"
        await asyncio.sleep(10)
        yield b"}"

    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=webhook_app), base_url="http://test"
        ) as client:
            return await client.post("/v1/events", content=slow_body(), headers=signed(b"{}"))

    assert asyncio.run(send()).status_code == 408
    webhook_app.state.event_store.accept.assert_not_called()
