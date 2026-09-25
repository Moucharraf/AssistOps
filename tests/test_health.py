import asyncio
from unittest.mock import AsyncMock

from assistops.health import check_postgres, check_qdrant, dependency_status


def test_dependency_timeout_is_bounded(settings, monkeypatch):
    async def stuck(_settings):
        await asyncio.sleep(60)

    monkeypatch.setattr("assistops.health.check_postgres", stuck)
    monkeypatch.setattr("assistops.health.check_qdrant", AsyncMock())
    result = asyncio.run(dependency_status(settings))
    assert result == {"postgres": "unavailable", "qdrant": "ok"}


def test_postgres_runs_a_real_query(settings, monkeypatch):
    cursor = AsyncMock()
    cursor.fetchone.return_value = (3,)
    connection = AsyncMock()
    connection.cursor = lambda: cursor
    connection.__aenter__.return_value = connection
    cursor.__aenter__.return_value = cursor
    connect = AsyncMock(return_value=connection)
    monkeypatch.setattr("assistops.health.psycopg.AsyncConnection.connect", connect)
    asyncio.run(check_postgres(settings))
    cursor.execute.assert_awaited_once_with(
        "SELECT version FROM schema_migrations WHERE version = %s", (3,)
    )


def test_qdrant_checks_readyz(settings, monkeypatch):
    import httpx

    original_client = httpx.AsyncClient

    def handler(request):
        assert request.url.path == "/readyz"
        return httpx.Response(200)

    monkeypatch.setattr(
        "assistops.health.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    asyncio.run(check_qdrant(settings))
