"""A PostgreSQL token bucket shared by API instances for each authenticated connector."""

from decimal import Decimal
from math import ceil

from assistops.config import Connector, Settings
from assistops.storage import connect


class ConnectorRateLimiter:
    def __init__(self, settings: Settings):
        self.settings = settings

    def consume(self, connector_id: str, connector: Connector) -> int | None:
        """Consume one token, or return the minimum whole seconds before retrying."""
        capacity = self.settings.api_rate_limit_requests
        rate = Decimal(capacity) / self.settings.api_rate_limit_period_seconds
        key = (connector_id, connector.tenant_id, connector.source)
        with connect(self.settings) as connection:
            connection.execute(
                """INSERT INTO connector_rate_limits
                   (connector_id, tenant_id, source, tokens, updated_at)
                   VALUES (%s, %s, %s, %s, clock_timestamp()) ON CONFLICT DO NOTHING""",
                (*key, capacity),
            )
            tokens, updated = connection.execute(
                """SELECT tokens, updated_at FROM connector_rate_limits
                   WHERE connector_id = %s AND tenant_id = %s AND source = %s FOR UPDATE""",
                key,
            ).fetchone()
            # Read database time after acquiring the lock, never an API server's clock.
            now = connection.execute("SELECT clock_timestamp()").fetchone()[0]
            elapsed = max(Decimal(0), Decimal(str((now - updated).total_seconds())))
            available = min(Decimal(capacity), tokens + elapsed * rate)
            retry_after = None if available >= 1 else max(1, ceil((1 - available) / rate))
            connection.execute(
                """UPDATE connector_rate_limits SET tokens = %s, updated_at = %s
                   WHERE connector_id = %s AND tenant_id = %s AND source = %s""",
                (available - 1 if retry_after is None else available, max(now, updated), *key),
            )
        # Commit before returning: a refused business request must not refund its admission.
        return retry_after
