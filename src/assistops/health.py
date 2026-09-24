import asyncio

import httpx
import psycopg
import structlog

from assistops.config import Settings

logger = structlog.get_logger()


async def check_postgres(settings: Settings) -> None:
    async with (
        await psycopg.AsyncConnection.connect(
            settings.database_url.get_secret_value(), autocommit=True
        ) as connection,
        connection.cursor() as cursor,
    ):
        await cursor.execute("SELECT 1")
        if await cursor.fetchone() != (1,):
            raise RuntimeError("Unexpected database health response")


async def check_qdrant(settings: Settings) -> None:
    headers = {}
    if settings.qdrant_api_key:
        headers["api-key"] = settings.qdrant_api_key.get_secret_value()
    async with httpx.AsyncClient(timeout=settings.dependency_timeout_seconds) as client:
        response = await client.get(f"{settings.qdrant_url.rstrip('/')}/readyz", headers=headers)
        response.raise_for_status()


async def dependency_status(settings: Settings) -> dict[str, str]:
    async def probe(name, check):
        try:
            async with asyncio.timeout(settings.dependency_timeout_seconds):
                await check(settings)
            return name, "ok"
        except Exception as exc:
            # Connection errors can contain credentials: log only their type.
            logger.warning("dependency_unavailable", dependency=name, error_type=type(exc).__name__)
            return name, "unavailable"

    results = await asyncio.gather(probe("postgres", check_postgres), probe("qdrant", check_qdrant))
    return dict(results)
