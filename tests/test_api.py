import json
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from assistops.main import create_app


def test_liveness_does_not_need_dependencies(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "assistops"}
    UUID(response.headers["X-Correlation-ID"])


def test_correlation_id_propagated(client):
    response = client.get("/health/live", headers={"X-Correlation-ID": "test-123"})
    assert response.headers["X-Correlation-ID"] == "test-123"


@pytest.mark.parametrize("value", ["x" * 65, "invalid value", ""])
def test_invalid_correlation_id_replaced(client, value):
    response = client.get("/health/live", headers={"X-Correlation-ID": value})
    UUID(response.headers["X-Correlation-ID"])


@pytest.mark.parametrize("failed", [None, "postgres", "qdrant"])
def test_readiness_reflects_dependencies(client, monkeypatch, failed):
    for name in ("postgres", "qdrant"):
        mock = AsyncMock(side_effect=RuntimeError("secret-dsn") if name == failed else None)
        monkeypatch.setattr(f"assistops.health.check_{name}", mock)
    response = client.get("/health/ready")
    assert response.status_code == (503 if failed else 200)
    assert response.json()["dependencies"] == {
        name: "unavailable" if name == failed else "ok" for name in ("postgres", "qdrant")
    }
    assert "secret-dsn" not in response.text


def test_unhandled_error_is_sanitized(app, capsys):
    @app.get("/broken")
    async def broken():
        raise RuntimeError("sensitive-password")

    with TestClient(app) as client:
        response = client.get("/broken", headers={"X-Correlation-ID": "error-test"})
    assert response.status_code == 500
    assert response.json() == {"error": {"code": "internal_error", "correlation_id": "error-test"}}
    assert response.headers["X-Correlation-ID"] == "error-test"
    assert "sensitive-password" not in capsys.readouterr().out


def test_unknown_route_does_not_log_sensitive_url(client, capsys):
    response = client.get("/private-value?token=secret", headers={"Authorization": "Bearer secret"})
    assert response.status_code == 404
    logs = capsys.readouterr().out
    assert "private-value" not in logs
    assert "secret" not in logs
    events = [json.loads(line) for line in logs.splitlines() if line.strip()]
    completed = next(event for event in events if event["event"] == "request_completed")
    assert completed["correlation_id"] == response.headers["X-Correlation-ID"]


def test_validation_error_does_not_echo_input(app):
    @app.get("/number")
    async def number(value: int):
        return value

    with TestClient(app) as client:
        response = client.get("/number?value=private-value")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert "private-value" not in response.text


def test_production_disables_api_documentation(settings):
    settings.environment = "production"
    with TestClient(create_app(settings)) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
