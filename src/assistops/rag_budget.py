"""A shared, conservative admission limit that survives worker restarts."""

from assistops.config import Settings
from assistops.storage import connect


def reserve_attempt(settings: Settings) -> bool:
    if settings.rag_daily_attempts == 0:
        return False
    with connect(settings) as connection:
        row = connection.execute(
            """INSERT INTO rag_daily_budget (day, attempts)
               VALUES ((clock_timestamp() AT TIME ZONE 'UTC')::date, 1)
               ON CONFLICT (day) DO UPDATE SET attempts = rag_daily_budget.attempts + 1
               WHERE rag_daily_budget.attempts < %s RETURNING attempts""",
            (settings.rag_daily_attempts,),
        ).fetchone()
    return row is not None
