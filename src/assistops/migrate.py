from importlib.resources import files

import structlog

from assistops.config import Settings
from assistops.observability import configure_logging
from assistops.storage import connect

MIGRATIONS = [(1, "001_events.sql"), (2, "002_worker.sql"), (3, "003_rag_budget.sql")]
SCHEMA_VERSION = MIGRATIONS[-1][0]


def migrate(settings: Settings) -> None:
    with connect(settings) as connection:
        connection.execute("SELECT pg_advisory_xact_lock(74129301)")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
               version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"""
        )
        for version, filename in MIGRATIONS:
            if connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = %s", (version,)
            ).fetchone():
                continue
            sql = files("assistops").joinpath(f"migrations/{filename}").read_text(encoding="utf-8")
            connection.execute(sql)
            connection.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))


if __name__ == "__main__":
    configure_logging()
    try:
        migrate(Settings())
    except Exception as exc:
        structlog.get_logger().error("migration_failed", error_type=type(exc).__name__)
        raise SystemExit(1) from None
    structlog.get_logger().info("migration_completed", version=SCHEMA_VERSION)
