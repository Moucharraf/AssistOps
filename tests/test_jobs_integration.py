import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from fastapi.testclient import TestClient
from test_events import PAYLOAD, SECRET, signed

from assistops.config import Connector
from assistops.events import EventInput, StatusQuery
from assistops.jobs import Exhausted, JobStore, Lease
from assistops.main import create_app
from assistops.storage import EventStore
from assistops.worker import demo_processor, run_once

pytestmark = pytest.mark.integration


def enqueue(settings):
    return EventStore(settings).accept(EventInput(**PAYLOAD), "demo", "worker-integration")


def query_for(receipt):
    return StatusQuery(
        receipt_id=str(receipt.receipt_id), tenant_id="demo", user_id="user-001", source="webhook"
    )


def expire(settings):
    with psycopg.connect(settings.database_url.get_secret_value()) as connection:
        connection.execute(
            "UPDATE event_jobs SET lease_expires_at = clock_timestamp() - interval '1 second'"
        )


def make_due(settings):
    with psycopg.connect(settings.database_url.get_secret_value()) as connection:
        connection.execute(
            "UPDATE event_jobs SET next_run_at = clock_timestamp() - interval '1 second'"
        )


def test_concurrent_workers_claim_one_lease(database):
    enqueue(database)
    with ThreadPoolExecutor(max_workers=8) as executor:
        claimed = list(executor.map(lambda _: JobStore(database).claim(), range(8)))
    assert sum(isinstance(job, Lease) for job in claimed) == 1
    assert sum(job is None for job in claimed) == 7


def test_worker_completes_demo_and_audits(database):
    receipt = enqueue(database)
    assert asyncio.run(run_once(JobStore(database), demo_processor)) is True
    status = EventStore(database).status(query_for(receipt), "demo")
    assert status.status == "completed"
    assert status.attempts == 1
    assert status.result["processor"] == "demo"
    assert status.result["business_action_executed"] is False
    assert JobStore(database).claim() is None
    with psycopg.connect(database.database_url.get_secret_value()) as connection:
        actions = connection.execute("SELECT action FROM event_audit ORDER BY id").fetchall()
    assert actions == [("event_received",), ("job_started",), ("job_completed",)]


def test_expired_worker_cannot_overwrite_new_worker(database):
    receipt = enqueue(database)
    old = JobStore(database).claim()
    expire(database)
    new_store = JobStore(database)
    new = new_store.claim()
    assert new.attempt == 2
    assert new.token != old.token
    assert new_store.finish(old, result={"obsolete": True}) is False
    assert new_store.finish(old, error="processor_error") is False
    assert new_store.finish(new, result={"processor": "demo"}) is True
    assert EventStore(database).status(query_for(receipt), "demo").result == {"processor": "demo"}


def test_expired_lease_cannot_finish_even_without_a_successor(database):
    enqueue(database)
    store = JobStore(database)
    lease = store.claim()
    expire(database)
    assert store.finish(lease, result={"late": True}) is False


def test_retries_wait_and_eventually_fail(database):
    receipt = enqueue(database)
    database.worker_retry_seconds = 60
    store = JobStore(database)
    for attempt in range(1, 4):
        lease = store.claim()
        assert lease.attempt == attempt
        assert store.finish(lease, error="processor_timeout") is True
        assert store.claim() is None
        make_due(database)
    status = EventStore(database).status(query_for(receipt), "demo")
    assert status.status == "failed"
    assert status.attempts == 3
    assert status.last_error == "processor_timeout"
    assert store.claim() is None


def test_repeated_crashes_exhaust_attempt_budget(database):
    receipt = enqueue(database)
    store = JobStore(database)
    for attempt in range(1, 4):
        assert store.claim().attempt == attempt
        expire(database)
    assert isinstance(store.claim(), Exhausted)
    assert store.claim() is None
    status = EventStore(database).status(query_for(receipt), "demo")
    assert status.status == "failed"
    assert status.last_error == "attempts_exhausted"


def test_completion_audit_failure_rolls_back_result(database):
    receipt = enqueue(database)
    store = JobStore(database)
    lease = store.claim()
    with psycopg.connect(database.database_url.get_secret_value()) as connection:
        connection.execute(
            "ALTER TABLE event_audit ADD CONSTRAINT no_complete CHECK (action <> 'job_completed')"
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        store.finish(lease, result={"processor": "demo"})
    status = EventStore(database).status(query_for(receipt), "demo")
    assert status.status == "processing"
    assert status.result is None


def test_status_requires_original_scope_and_signature(database):
    receipt = enqueue(database)
    query = query_for(receipt).model_dump()
    database.webhook_connectors["other"] = Connector(
        secret=SECRET, tenant_id="demo", allowed_user_ids={"user-001", "other"}
    )
    database.webhook_connectors["demo"].allowed_user_ids = frozenset({"user-001", "other"})
    with TestClient(create_app(database)) as client:
        body = json.dumps(query).encode()
        assert client.post("/v1/events/status", content=body).status_code == 401
        valid = client.post("/v1/events/status", content=body, headers=signed(body))
        assert valid.status_code == 200
        assert valid.json()["status"] == "pending"
        headers = {**signed(body), "X-AssistOps-Connector": "other"}
        assert client.post("/v1/events/status", content=body, headers=headers).status_code == 404
        body = json.dumps({**query, "user_id": "other"}).encode()
        assert (
            client.post("/v1/events/status", content=body, headers=signed(body)).status_code == 404
        )
        body = json.dumps({**query, "tenant_id": "other"}).encode()
        assert (
            client.post("/v1/events/status", content=body, headers=signed(body)).status_code == 403
        )


def test_processing_does_not_break_ingress_idempotency(database):
    receipt = enqueue(database)
    asyncio.run(run_once(JobStore(database), demo_processor))
    replay = enqueue(database)
    assert replay.duplicate is True
    assert replay.receipt_id == receipt.receipt_id
    assert JobStore(database).claim() is None
