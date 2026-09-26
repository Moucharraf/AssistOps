import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_events import PAYLOAD, SECRET, signed
from test_events import webhook_app as webhook_app

from assistops.config import Connector, Settings
from assistops.main import create_app
from assistops.rate_limits import ConnectorRateLimiter
from assistops.storage import connect


@pytest.mark.parametrize(
    "path", ["/v1/events", "/v1/events/status", "/v1/approvals/status", "/v1/approvals/decide"]
)
def test_all_signed_routes_return_retry_after_before_business_processing(webhook_app, path):
    webhook_app.state.rate_limiter.consume.return_value = 7
    body = json.dumps(PAYLOAD).encode()
    with TestClient(webhook_app) as client:
        response = client.post(
            path, content=body, headers={**signed(body), "X-Correlation-ID": "limit-test"}
        )
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "7"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json() == {"error": {"code": "rate_limited", "correlation_id": "limit-test"}}
    webhook_app.state.event_store.accept.assert_not_called()
    webhook_app.state.event_store.status.assert_not_called()


def test_invalid_signature_cannot_drain_bucket_and_health_is_exempt(webhook_app):
    body = json.dumps(PAYLOAD).encode()
    with TestClient(webhook_app) as client:
        assert (
            client.post(
                "/v1/events", content=body, headers=signed(body, secret="wrong")
            ).status_code
            == 401
        )
        assert client.get("/health/live").status_code == 200
    webhook_app.state.rate_limiter.consume.assert_not_called()


def test_storage_failure_fails_closed_without_exposing_secrets(webhook_app, capsys):
    webhook_app.state.rate_limiter.consume.side_effect = psycopg.OperationalError("secret-dsn")
    body = json.dumps(PAYLOAD).encode()
    with TestClient(webhook_app) as client:
        response = client.post("/v1/events", content=body, headers=signed(body))
    assert response.status_code == 503 and response.headers["Retry-After"] == "1"
    assert response.json()["error"]["code"] == "rate_limit_unavailable"
    assert "secret-dsn" not in response.text + capsys.readouterr().out
    webhook_app.state.event_store.accept.assert_not_called()


@pytest.mark.parametrize(
    "values",
    [
        {"api_rate_limit_requests": 0},
        {"api_rate_limit_requests": -1},
        {"api_rate_limit_period_seconds": 0},
        {"api_rate_limit_period_seconds": 3601},
    ],
)
def test_invalid_rate_limit_configuration_rejected(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


@pytest.mark.integration
def test_concurrent_instances_share_one_atomic_bucket(database):
    database.api_rate_limit_requests = 3
    database.api_rate_limit_period_seconds = 3600
    connector = database.webhook_connectors["demo"]
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(
            pool.map(lambda _: ConnectorRateLimiter(database).consume("demo", connector), range(18))
        )
    assert results.count(None) == 3
    assert all(1 <= result <= 1200 for result in results if result is not None)
    assert ConnectorRateLimiter(database).consume("demo", connector) is not None
    with connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM connector_rate_limits").fetchone()[0] == 1


@pytest.mark.integration
def test_refill_uses_database_time_and_caps_idle_credit(database):
    database.api_rate_limit_requests = 2
    database.api_rate_limit_period_seconds = 60
    limiter = ConnectorRateLimiter(database)
    connector = database.webhook_connectors["demo"]
    assert limiter.consume("demo", connector) is None
    assert limiter.consume("demo", connector) is None
    assert limiter.consume("demo", connector) == 30
    with connect(database) as connection:
        connection.execute(
            """UPDATE connector_rate_limits
               SET updated_at = clock_timestamp() - interval '31 seconds'"""
        )
    assert limiter.consume("demo", connector) is None
    assert 1 <= limiter.consume("demo", connector) <= 30
    with connect(database) as connection:
        connection.execute(
            "UPDATE connector_rate_limits SET updated_at = clock_timestamp() - interval '1 day'"
        )
    assert limiter.consume("demo", connector) is None
    assert limiter.consume("demo", connector) is None
    assert limiter.consume("demo", connector) is not None


@pytest.mark.integration
def test_isolation_includes_connector_tenant_and_source(database):
    database.api_rate_limit_requests = 1
    database.api_rate_limit_period_seconds = 3600
    limiter = ConnectorRateLimiter(database)
    connector = database.webhook_connectors["demo"]
    assert limiter.consume("demo", connector) is None
    assert limiter.consume("demo", connector) is not None
    for name, config in [
        ("other", connector),
        ("demo", connector.model_copy(update={"tenant_id": "other"})),
        ("demo", connector.model_copy(update={"source": "email"})),
    ]:
        assert limiter.consume(name, config) is None


@pytest.mark.integration
def test_restart_http_rejection_and_idempotent_retry(database):
    database.api_rate_limit_requests = 1
    database.api_rate_limit_period_seconds = 60
    body = json.dumps(PAYLOAD).encode()
    with TestClient(create_app(database)) as first:
        receipt = first.post("/v1/events", content=body, headers=signed(body)).json()
    # A new API instance must not reset the connector's balance.
    with TestClient(create_app(database)) as second:
        rejected = second.post("/v1/events", content=body, headers=signed(body))
        assert rejected.status_code == 429
        assert 1 <= int(rejected.headers["Retry-After"]) <= 60
        with connect(database) as connection:
            assert connection.execute("SELECT count(*) FROM inbound_events").fetchone()[0] == 1
            assert connection.execute("SELECT count(*) FROM event_jobs").fetchone()[0] == 1
            connection.execute(
                """UPDATE connector_rate_limits
                   SET updated_at = clock_timestamp() - interval '61 seconds'"""
            )
        replay = second.post("/v1/events", content=body, headers=signed(body))
        assert replay.status_code == 202
        assert replay.json()["duplicate"] and replay.json()["receipt_id"] == receipt["receipt_id"]


@pytest.mark.integration
def test_signed_invalid_requests_consume_capacity_and_do_not_allocate_event(database):
    database.api_rate_limit_requests = 1
    database.api_rate_limit_period_seconds = 3600
    with TestClient(create_app(database)) as client:
        body = b"bad json"
        assert client.post("/v1/events", content=body, headers=signed(body)).status_code == 422
        body = json.dumps(PAYLOAD).encode()
        assert client.post("/v1/events", content=body, headers=signed(body)).status_code == 429
    with connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM inbound_events").fetchone()[0] == 0


@pytest.mark.integration
def test_real_database_error_cannot_bypass_admission(database):
    with connect(database) as connection:
        connection.execute("ALTER TABLE connector_rate_limits RENAME TO unavailable_limits")
    app = create_app(database)
    app.state.event_store = Mock()
    body = json.dumps(PAYLOAD).encode()
    with TestClient(app) as client:
        response = client.post("/v1/events", content=body, headers=signed(body))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "rate_limit_unavailable"
    app.state.event_store.accept.assert_not_called()


@pytest.mark.integration
def test_http_connectors_are_independent_and_polling_shares_their_bucket(database):
    database.api_rate_limit_requests = 1
    database.api_rate_limit_period_seconds = 3600
    database.webhook_connectors["other"] = Connector(
        secret=SECRET, tenant_id="demo", allowed_user_ids={"user-001"}
    )
    with TestClient(create_app(database)) as client:
        body = json.dumps(PAYLOAD).encode()
        assert client.post("/v1/events", content=body, headers=signed(body)).status_code == 202
        query = json.dumps(
            {
                "tenant_id": "demo",
                "user_id": "user-001",
                "source": "webhook",
                "receipt_id": str(uuid4()),
            }
        ).encode()
        assert (
            client.post("/v1/events/status", content=query, headers=signed(query)).status_code
            == 429
        )
        body = json.dumps({**PAYLOAD, "event_id": "other-event"}).encode()
        assert (
            client.post(
                "/v1/events",
                content=body,
                headers={**signed(body), "X-AssistOps-Connector": "other"},
            ).status_code
            == 202
        )


def test_openapi_documents_throttling(client):
    schema = client.get("/openapi.json").json()
    for path in ("/v1/events", "/v1/events/status", "/v1/approvals/status", "/v1/approvals/decide"):
        response = schema["paths"][path]["post"]["responses"]["429"]
        assert response["headers"]["Retry-After"]["schema"]["minimum"] == 1
