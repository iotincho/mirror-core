"""Idempotent daily activity metadata; never persist paths, payloads or addresses."""

from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert

from src.adapters.storage.postgres.administration_models import MetricCoverage, UserActivity
from src.adapters.storage.postgres.boundaries import database_call


class PostgresActivity:
    def __init__(self, sessions):
        self.sessions = sessions

    @database_call
    async def observe(self, user_id, day, now, cutoff):
        async with self.sessions.begin() as session:
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
            await session.execute(delete(UserActivity).where(UserActivity.day < cutoff))
