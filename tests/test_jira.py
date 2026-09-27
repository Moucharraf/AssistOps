import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import httpx
import pytest
from pydantic import SecretStr, ValidationError
from test_business import decision, dispatch, enable

from assistops.business import BusinessTools
from assistops.config import Settings
from assistops.events import EventError
from assistops.jira import JiraClient, JiraError
from assistops.storage import EventStore, connect
from assistops.ticket_delivery import deliver_once, reconcile


def configure(settings):
    settings.ticket_backend = "jira"
    settings.jira_site = "https://example.atlassian.net"
    settings.jira_project_key = "OPS"
    settings.jira_issue_type_id = "10001"
    settings.jira_tenant_id = "demo"
    settings.jira_email = "operator@example.invalid"
    settings.jira_api_token = SecretStr("test-secret")
    return settings


@pytest.fixture
def jira_db(database):
    return configure(enable(database))


def approved(settings):
    _, query, job = dispatch(settings)
    review = decision(job.result["proposal"])
    answer = BusinessTools(settings).review(review, "demo", "test-jira", "approved")
    assert answer["outcome"] == "ticket_pending"
    return query, review


def factory(handler):
    return lambda settings: JiraClient(settings, transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    "site",
    ["http://example.atlassian.net", "https://evil.test", "https://x.atlassian.net@evil.test"],
)
def test_jira_site_restricted(site):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jira_site=site)


def test_jira_requires_explicit_destination():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ticket_backend="jira")


@pytest.mark.integration
def test_approval_only_enqueues_and_concurrent_workers_send_once(jira_db):
    query, review = approved(jira_db)
    requests = []

    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        assert body["fields"]["project"] == {"key": "OPS"}
        assert body["fields"]["issuetype"] == {"id": "10001"}
        assert "synthétiques" in body["fields"]["description"]["content"][0]["content"][0]["text"]
        assert body["properties"][0]["value"]["id"] == review.proposal_id
        assert body["properties"][0]["value"]["arguments_hash"] == review.arguments_hash
        return httpx.Response(201, json={"key": "OPS-42"})

    assert EventStore(jira_db).status(query, "demo").status == "awaiting_delivery"
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: deliver_once(jira_db, factory(handler)), range(4)))
    assert sum(results) == 1 and len(requests) == 1
    job = EventStore(jira_db).status(query, "demo")
    assert job.status == "completed"
    assert job.result["ticket_url"] == "https://example.atlassian.net/browse/OPS-42"
    assert job.result["business_action_executed"] is True
    assert BusinessTools(jira_db).review(review, "demo", "replay", "approved") == job.result
    with connect(jira_db) as connection:
        assert connection.execute("SELECT count(*) FROM synthetic_tickets").fetchone()[0] == 0


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["timeout", "server_error", "malformed_success", "wrong_project"])
def test_ambiguous_write_never_retried(jira_db, kind):
    query, _ = approved(jira_db)
    calls = []

    def handler(request):
        calls.append(request)
        if kind == "timeout":
            raise httpx.ReadTimeout("secret transport details", request=request)
        if kind == "server_error":
            return httpx.Response(503, text="private error")
        if kind == "wrong_project":
            return httpx.Response(201, json={"key": "OTHER-42"})
        return httpx.Response(201, text="not JSON")

    assert deliver_once(jira_db, factory(handler))
    assert not deliver_once(jira_db, factory(handler))
    job = EventStore(jira_db).status(query, "demo")
    assert job.status == "delivery_uncertain" and len(calls) == 1
    assert job.result["business_action_executed"] is None
    assert "secret transport details" not in json.dumps(job.result)


@pytest.mark.integration
def test_interrupted_delivery_recovered_without_http(jira_db):
    query, _ = approved(jira_db)
    with connect(jira_db) as connection:
        connection.execute("""UPDATE ticket_deliveries SET status = 'sending',
                           started_at = now() - interval '3 minutes'""")
    client_factory = Mock(side_effect=AssertionError("Must not repeat an uncertain write"))
    assert deliver_once(jira_db, client_factory)
    client_factory.assert_not_called()
    assert EventStore(jira_db).status(query, "demo").status == "delivery_uncertain"


@pytest.mark.integration
def test_jira_rate_limit_honored_and_bounded(jira_db):
    query, _ = approved(jira_db)
    handler = Mock(return_value=httpx.Response(429, headers={"Retry-After": "120"}))
    for _ in range(3):
        assert deliver_once(jira_db, factory(handler))
        assert not deliver_once(jira_db, factory(handler))
        with connect(jira_db) as connection:
            connection.execute("UPDATE ticket_deliveries SET next_run_at = now()")
    assert handler.call_count == 3
    assert EventStore(jira_db).status(query, "demo").status == "failed"


@pytest.mark.integration
@pytest.mark.parametrize("change", ["project", "tenant", "requester", "reviewer"])
def test_revocation_or_destination_change_prevents_delivery(jira_db, change):
    query, _ = approved(jira_db)
    if change == "project":
        jira_db.jira_project_key = "OTHER"
    elif change == "tenant":
        jira_db.jira_tenant_id = "other"
    elif change == "requester":
        jira_db.business_user_roles["demo"]["user-001"] = frozenset()
    else:
        jira_db.business_user_roles["demo"]["reviewer-001"] = frozenset()
    client_factory = Mock(side_effect=AssertionError("No external call allowed"))
    assert deliver_once(jira_db, client_factory)
    client_factory.assert_not_called()
    assert EventStore(jira_db).status(query, "demo").status == "failed"


@pytest.mark.integration
def test_destination_bound_to_human_approval(jira_db):
    _, _, job = dispatch(jira_db)
    review = decision(job.result["proposal"])
    jira_db.jira_project_key = "OTHER"
    with pytest.raises(EventError) as error:
        BusinessTools(jira_db).review(review, "demo", "changed", "approved")
    assert error.value.code == "jira_destination_changed"


@pytest.mark.integration
@pytest.mark.parametrize("valid", [False, True])
def test_reconciliation_checks_remote_marker_and_never_posts(jira_db, valid):
    query, review = approved(jira_db)
    with connect(jira_db) as connection:
        connection.execute("UPDATE ticket_deliveries SET status = 'uncertain'")
    calls = []

    def handler(request):
        assert request.method == "GET"
        calls.append(request)
        if "properties" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "value": {
                        "id": review.proposal_id,
                        "arguments_hash": review.arguments_hash if valid else "wrong",
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "key": "OPS-42",
                "fields": {"project": {"key": "OPS"}, "issuetype": {"id": "10001"}},
            },
        )

    if valid:
        reconcile(jira_db, review.proposal_id, "OPS-42", factory(handler))
        assert EventStore(jira_db).status(query, "demo").status == "completed"
    else:
        with pytest.raises(JiraError, match="jira_issue_mismatch"):
            reconcile(jira_db, review.proposal_id, "OPS-42", factory(handler))
    assert len(calls) == 2


def test_scoped_token_uses_gateway_and_no_redirect(settings):
    configure(settings)
    settings.jira_cloud_id = "aa87df51-5d85-4447-b39a-4fdbf02f97d6"
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.host == "api.atlassian.com"
        assert request.url.path.startswith("/ex/jira/" + settings.jira_cloud_id + "/rest/api/3/")
        return httpx.Response(302, headers={"Location": "https://untrusted.test"})

    client = JiraClient(settings, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(JiraError, match="jira_http_302"):
            client.request("GET", "mypermissions")
    finally:
        client.close()
    assert len(calls) == 1


@pytest.mark.integration
def test_modified_approved_arguments_never_sent(jira_db):
    query, _ = approved(jira_db)
    with connect(jira_db) as connection:
        connection.execute("""UPDATE ticket_proposals SET arguments =
                           jsonb_set(arguments, '{subject}', '\"Changed after approval\"')""")
    client_factory = Mock(side_effect=AssertionError("Modified arguments must not be sent"))
    assert deliver_once(jira_db, client_factory)
    client_factory.assert_not_called()
    assert EventStore(jira_db).status(query, "demo").last_error == "jira_proposal_changed"


@pytest.mark.integration
def test_rejected_jira_proposal_has_no_delivery(jira_db):
    _, _, job = dispatch(jira_db)
    review = decision(job.result["proposal"], choice="rejected")
    result = BusinessTools(jira_db).review(review, "demo", "test-rejection", "rejected")
    assert result["outcome"] == "rejected"
    client_factory = Mock(side_effect=AssertionError("Rejected proposals must not be sent"))
    assert not deliver_once(jira_db, client_factory)
    client_factory.assert_not_called()
    with connect(jira_db) as connection:
        assert connection.execute("SELECT count(*) FROM ticket_deliveries").fetchone()[0] == 0
