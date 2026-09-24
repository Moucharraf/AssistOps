import os
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

from assistops.config import Settings
from assistops.main import create_app
from assistops.migrate import migrate


@pytest.fixture
def settings():
    return Settings(_env_file=None, environment="test", dependency_timeout_seconds=0.1)


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def database():
    from test_events import SECRET

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
