import json
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo
from test_events import PAYLOAD, SECRET, signed

from assistops.config import Settings
from assistops.events import EventError, EventInput
from assistops.main import create_app
from assistops.migrate import migrate
from assistops.storage import EventStore

pytestmark = pytest.mark.integration


@pytest.fixture
def database():
    dsn = os.environ.get("ASSISTOPS_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set ASSISTOPS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    dsn = make_conninfo(dsn, connect_timeout=3)
    schema = "test_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=make_conninfo(dsn, options=f"-csearch_path={schema}"),
        webhook_connectors={
            "demo": {"secret": SECRET, "tenant_id": "demo", "allowed_user_ids": ["user-001"]}
        },
    )
    try:
        migrate(settings)
        yield settings
    finally:
        # Only the randomly generated schema belonging to this test is removed.
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def counts(settings):
    with psycopg.connect(settings.database_url.get_secret_value()) as connection:
        return tuple(
            connection.execute(
                sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
            ).fetchone()[0]
            for table in ("inbound_events", "event_jobs", "event_audit")
        )


def test_migration_can_run_twice(database):
    migrate(database)
    assert counts(database) == (0, 0, 0)


def test_concurrent_deliveries_create_one_job_and_audit(database):
    store = EventStore(database)
    event = EventInput(**PAYLOAD)
    with ThreadPoolExecutor(max_workers=8) as executor:
        receipts = list(executor.map(lambda _: store.accept(event, "demo", "concurrent"), range(8)))
    assert len({receipt.receipt_id for receipt in receipts}) == 1
    assert sum(not receipt.duplicate for receipt in receipts) == 1
    assert counts(database) == (1, 1, 1)


def test_conflicting_payload_is_not_overwritten(database):
    store = EventStore(database)
    store.accept(EventInput(**PAYLOAD), "demo", "first")
    with pytest.raises(EventError) as error:
        store.accept(EventInput(**{**PAYLOAD, "message": "changed"}), "demo", "second")
    assert error.value.status == 409
    assert counts(database) == (1, 1, 1)


def test_audit_failure_rolls_back_event_and_job(database):
    with psycopg.connect(database.database_url.get_secret_value()) as connection:
        connection.execute("ALTER TABLE event_audit ADD CONSTRAINT reject_audit CHECK (false)")
    with pytest.raises(psycopg.errors.CheckViolation):
        EventStore(database).accept(EventInput(**PAYLOAD), "demo", "rollback")
    assert counts(database) == (0, 0, 0)


def test_receipt_survives_new_app_and_json_formatting(database):
    body = json.dumps(PAYLOAD).encode()
    with TestClient(create_app(database)) as client:
        first = client.post("/v1/events", content=body, headers=signed(body))
    # New application and database connection; no in-memory idempotency state.
    reformatted = json.dumps(PAYLOAD, sort_keys=True, indent=2).encode()
    with TestClient(create_app(database)) as client:
        second = client.post("/v1/events", content=reformatted, headers=signed(reformatted))
    assert first.status_code == second.status_code == 202
    assert first.json()["receipt_id"] == second.json()["receipt_id"]
    assert second.json()["duplicate"] is True
    assert counts(database) == (1, 1, 1)


def test_idempotency_is_scoped_to_tenant(database):
    store = EventStore(database)
    first = store.accept(EventInput(**PAYLOAD), "demo", "first")
    second = store.accept(EventInput(**{**PAYLOAD, "tenant_id": "other"}), "other", "second")
    assert first.receipt_id != second.receipt_id
    assert counts(database) == (2, 2, 2)
