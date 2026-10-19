"""Idempotent daily access observations; no request paths, payloads or addresses."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert

from src.administration.models import MetricCoverage, UserActivity


async def record_access(sessions, user_id, now=None):
    now = now or datetime.now(UTC)
    day = now.astimezone(ZoneInfo("America/Argentina/Buenos_Aires")).date()
    async with sessions.begin() as session:
        coverage = insert(MetricCoverage).values(name="app_access", since=now)
        await session.execute(coverage.on_conflict_do_nothing())
        statement = insert(UserActivity).values(user_id=user_id, day=day, last_seen_at=now)
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[UserActivity.user_id, UserActivity.day],
                set_={
                    "last_seen_at": func.greatest(
                        UserActivity.last_seen_at, statement.excluded.last_seen_at
                    )
                },
            )
        )
        await session.execute(
            delete(UserActivity).where(UserActivity.day < day - timedelta(days=90))
        )
