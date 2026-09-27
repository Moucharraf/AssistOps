from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_business import dispatch

from assistops.config import Connector, Settings
from assistops.main import create_app
from assistops.review.auth import disable, password_hash, provision, verify_password
from assistops.storage import connect

PASSWORD = "A long test-only passphrase!"
ORIGIN = "http://localhost:8000"
HEADERS = {"Origin": ORIGIN, "X-AssistOps-UI": "1"}


def sign_in(client):
    result = client.post(
        "/review/api/login",
        headers=HEADERS,
        json={"username": "reviewer", "password": PASSWORD},
    )
    assert result.status_code == 204, result.text
    session = client.get("/review/api/session")
    assert session.status_code == 200, session.text
    return {**HEADERS, "X-CSRF-Token": session.json()["csrf_token"]}


def proposal(settings):
    return dispatch(settings)[2].result["proposal"]


def decide(client, p, headers, choice="approved", **overrides):
    return client.post(
        f"/review/api/proposals/{p['id']}/decision",
        headers=headers,
        json={"decision": choice, "arguments_hash": p["arguments_hash"], **overrides},
    )


def test_password_hash_is_salted_and_verifiable():
    first, second = password_hash(PASSWORD), password_hash(PASSWORD)
    assert first != second and PASSWORD not in first
    assert verify_password(PASSWORD, first)
    assert not verify_password("wrong", first)
    with pytest.raises(ValueError):
        password_hash("too short")


def test_ui_opt_in_and_production_https(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/review").status_code == 404
    with pytest.raises(ValidationError, match="HTTPS"):
        Settings(_env_file=None, environment="production", review_ui_enabled=True)
    assert Settings(
        _env_file=None,
        environment="production",
        review_ui_enabled=True,
        review_ui_origin="https://review.example.com",
    )


@pytest.mark.parametrize(
    "origin", ["https://example.com/", "https://a:b@example.com", "//a", "https://a?q=b"]
)
def test_origin_is_a_fixed_origin(origin):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, review_ui_origin=origin)


def test_static_assets_have_restrictive_headers(settings):
    settings.review_ui_enabled = True
    with TestClient(create_app(settings)) as client:
        for path in ("/review", "/review/assets/app.js", "/review/assets/style.css"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["x-frame-options"] == "DENY"
            assert "unsafe-inline" not in response.headers["content-security-policy"]
        assert client.get("/review/assets/secret.env").status_code != 200
        assert client.get("/review/api/session").status_code == 401


@pytest.mark.integration
def test_login_cookie_logout_and_session_hash(review_db):
    with TestClient(create_app(review_db)) as client:
        headers = sign_in(client)
        token = client.cookies["assistops_review"]
        with connect(review_db) as connection:
            stored = connection.execute("SELECT token_hash FROM review_sessions").fetchone()[0]
        assert token not in stored
        me = client.get("/review/api/session").json()
        assert me["user_id"] == "reviewer-001" and "password_hash" not in me
        assert client.post("/review/api/logout", headers=headers, json={}).status_code == 204
        client.cookies.set("assistops_review", token)
        assert client.get("/review/api/session").status_code == 401


@pytest.mark.integration
def test_https_cookie_flags(review_db):
    review_db.review_ui_origin = "https://testserver"
    with TestClient(create_app(review_db), base_url="https://testserver") as client:
        response = client.post(
            "/review/api/login",
            headers={**HEADERS, "Origin": "https://testserver"},
            json={"username": "reviewer", "password": PASSWORD},
        )
        cookie = response.headers["set-cookie"]
        for flag in ("__Host-assistops_review=", "HttpOnly", "Secure", "SameSite=strict", "Path=/"):
            assert flag in cookie


@pytest.mark.integration
def test_auth_required_and_origin_checked_before_login(review_db):
    p = proposal(review_db)
    with TestClient(create_app(review_db)) as client:
        assert client.get("/review/api/proposals").status_code == 401
        assert client.get(f"/review/api/proposals/{p['id']}").status_code == 401
        assert decide(client, p, HEADERS).status_code == 401
        response = client.post(
            "/review/api/login",
            headers={**HEADERS, "Origin": "https://attacker.invalid"},
            json={"username": "reviewer", "password": PASSWORD},
        )
        assert response.status_code == 403
        with connect(review_db) as connection:
            assert connection.execute("SELECT count(*) FROM review_sessions").fetchone()[0] == 0


@pytest.mark.integration
def test_exact_approval_and_replay_have_one_side_effect_and_audit(review_db):
    p = proposal(review_db)
    with TestClient(create_app(review_db)) as client:
        headers = sign_in(client)
        listed = client.get("/review/api/proposals").json()
        assert listed["items"][0]["id"] == p["id"]
        detail = client.get(f"/review/api/proposals/{p['id']}").json()
        assert detail["can_decide"] is True
        assert detail["proposal"]["arguments"] == p["arguments"]
        assert decide(client, p, headers, arguments_hash="0" * 64).status_code == 409
        first = decide(client, p, headers)
        assert first.status_code == 200 and first.json()["outcome"] == "ticket_created"
        assert decide(client, p, headers).json()["ticket_id"] == first.json()["ticket_id"]
        assert client.get("/review/api/proposals").json()["items"] == []
        assert len(client.get("/review/api/proposals?status=all").json()["items"]) == 1
        assert decide(client, p, headers, "rejected").status_code == 409
    with connect(review_db) as connection:
        assert connection.execute("SELECT count(*) FROM synthetic_tickets").fetchone()[0] == 1
        assert (
            connection.execute(
                "SELECT count(*) FROM event_audit WHERE action = 'ticket_approved'"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.integration
@pytest.mark.parametrize("mode", ["csrf", "origin", "identity", "self", "role", "scope", "tenant"])
def test_forged_or_revoked_authority_cannot_decide(review_db, mode):
    p = proposal(review_db)
    with TestClient(create_app(review_db)) as client:
        headers = sign_in(client)
        extra = {}
        expected = 403
        if mode == "csrf":
            headers["X-CSRF-Token"] = "wrong"
        elif mode == "origin":
            headers["Origin"] = "https://attacker.invalid"
        elif mode == "identity":
            extra["user_id"] = "reviewer-001"
            expected = 422
        elif mode == "role":
            review_db.business_user_roles["demo"]["reviewer-001"] = frozenset()
        elif mode == "self":
            review_db.business_user_roles["demo"]["user-001"] |= {"ticket_approver"}
            with connect(review_db) as connection:
                connection.execute("UPDATE review_accounts SET user_id = 'user-001'")
            assert not client.get(f"/review/api/proposals/{p['id']}").json()["can_decide"]
        else:
            if mode == "tenant":
                review_db.webhook_connectors["demo"].tenant_id = "other"
            else:
                review_db.webhook_connectors.clear()
        assert decide(client, p, headers, **extra).status_code == expected
    with connect(review_db) as connection:
        assert connection.execute("SELECT status FROM ticket_proposals").fetchone()[0] == "pending"


@pytest.mark.integration
def test_connector_and_tenant_isolation(review_db):
    p = proposal(review_db)
    review_db.webhook_connectors["separate"] = Connector(
        secret="a" * 32,
        tenant_id="demo",
        allowed_user_ids={"user-001"},
    )
    provision(review_db, "reviewer", "demo", "reviewer-001", ["separate"], PASSWORD)
    with TestClient(create_app(review_db)) as client:
        headers = sign_in(client)
        assert client.get("/review/api/proposals?status=all").json()["items"] == []
        assert client.get(f"/review/api/proposals/{p['id']}").status_code == 404
        assert decide(client, p, headers).status_code == 404
        assert client.get(f"/review/api/proposals/{uuid4()}").status_code == 404
    with connect(review_db) as connection:
        connection.execute("UPDATE review_accounts SET connector_ids = ARRAY['demo']")
        connection.execute("UPDATE inbound_events SET tenant_id = 'another'")
    with TestClient(create_app(review_db)) as client:
        sign_in(client)
        assert client.get("/review/api/proposals?status=all").json()["items"] == []
        assert client.get(f"/review/api/proposals/{p['id']}").status_code == 404


@pytest.mark.integration
@pytest.mark.parametrize("change", ["expire", "disable", "reset"])
def test_sessions_are_revocable(review_db, change):
    with TestClient(create_app(review_db)) as client:
        sign_in(client)
        if change == "expire":
            with connect(review_db) as connection:
                connection.execute("UPDATE review_sessions SET expires_at = now() - interval '1s'")
        elif change == "disable":
            disable(review_db, "reviewer")
        else:
            provision(review_db, "reviewer", "demo", "reviewer-001", ["demo"], PASSWORD)
        assert client.get("/review/api/session").status_code == 401


@pytest.mark.integration
def test_failed_logins_are_limited_and_do_not_reveal_accounts(review_db):
    with TestClient(create_app(review_db)) as client:
        for name in ["unknown", "reviewer"]:
            response = client.post(
                "/review/api/login",
                headers=HEADERS,
                json={"username": name, "password": "incorrect"},
            )
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "invalid_credentials"
        with connect(review_db) as connection:
            connection.execute("UPDATE review_rate_limits SET attempts = 30")
        response = client.post(
            "/review/api/login",
            headers=HEADERS,
            json={"username": "reviewer", "password": PASSWORD},
        )
        assert response.status_code == 429 and response.headers["retry-after"] == "300"


@pytest.mark.integration
def test_expired_and_rejected_proposals_never_create_tickets(review_db):
    p = proposal(review_db)
    with TestClient(create_app(review_db)) as client:
        headers = sign_in(client)
        assert decide(client, p, headers, "rejected").json()["outcome"] == "rejected"
        p = proposal(review_db)
        with connect(review_db) as connection:
            connection.execute("UPDATE ticket_proposals SET expires_at = now() - interval '1s'")
        result = decide(client, p, headers)
        assert result.json()["outcome"] == "expired"
    with connect(review_db) as connection:
        assert connection.execute("SELECT count(*) FROM synthetic_tickets").fetchone()[0] == 0


@pytest.mark.integration
def test_jira_approval_only_enqueues_and_displays_uncertain_delivery(review_db):
    review_db.ticket_backend = "jira"
    review_db.jira_site = "https://example.atlassian.net"
    review_db.jira_tenant_id = "demo"
    review_db.jira_project_key = "OPS"
    review_db.jira_issue_type_id = "10001"
    p = proposal(review_db)
    with TestClient(create_app(review_db)) as client:
        headers = sign_in(client)
        result = decide(client, p, headers).json()
        assert result["outcome"] == "ticket_pending"
        assert result["proposal"]["arguments"]["ticket_target"]["project"] == "OPS"
        with connect(review_db) as connection:
            connection.execute("UPDATE ticket_deliveries SET status = 'uncertain'")
        detail = client.get(f"/review/api/proposals/{p['id']}").json()
        assert detail["outcome"] == "ticket_uncertain"
        assert not detail["can_decide"]
        assert decide(client, p, headers).json()["outcome"] == "ticket_uncertain"
        with connect(review_db) as connection:
            assert connection.execute("SELECT count(*) FROM ticket_deliveries").fetchone()[0] == 1
