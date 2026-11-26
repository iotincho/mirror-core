"""Write idempotent AI usage receipts and maintain collection coverage."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.adapters.storage.postgres.administration_models import MetricCoverage
from src.adapters.storage.postgres.ai_usage_models import AiUsageCoverage, AiUsageReceipt
from src.adapters.storage.postgres.boundaries import database_call
from src.core.administration.ai_usage import AiUsageAttempt, AiUsageResult
from src.core.administration.ai_usage_queries import AI_USAGE_RETENTION_CUTOFF


class PostgresAiUsage:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

    @database_call
    async def start(self, attempt: AiUsageAttempt) -> bool:
        """Reserve a receipt if collection is active. Replays keep the original attribution."""
        async with self.sessions.begin() as session:
            coverage = await session.scalar(
                select(AiUsageCoverage.started_at)
                .where(AiUsageCoverage.ended_at.is_(None))
                .with_for_update(read=True)
            )
            if coverage is None:
                return False
            created = await session.scalar(
                insert(AiUsageReceipt)
                .values(**attempt.model_dump(), started_at=func.clock_timestamp())
                .on_conflict_do_nothing(index_elements=[AiUsageReceipt.attempt_id])
                .returning(AiUsageReceipt.attempt_id)
            )
            return created is not None

    @database_call
    async def finish(self, attempt_id: UUID, result: AiUsageResult) -> bool:
        """Record the first outcome, including for attempts started before disabling collection."""
        async with self.sessions.begin() as session:
            finished = await session.scalar(
                update(AiUsageReceipt)
                .where(
                    AiUsageReceipt.attempt_id == attempt_id, AiUsageReceipt.finished_at.is_(None)
                )
                .values(
                    **result.model_dump(),
                    finished_at=func.greatest(func.clock_timestamp(), AiUsageReceipt.started_at),
                )
                .returning(AiUsageReceipt.attempt_id)
            )
            return finished is not None

    @database_call
    async def maintain(self, *, enabled: bool, retention_days: int) -> None:
        async with self.sessions.begin() as session:
            if enabled:
                await session.execute(
                    insert(AiUsageCoverage)
                    .values(started_at=func.clock_timestamp())
                    .on_conflict_do_nothing()
                )
            else:
                await session.execute(
                    update(AiUsageCoverage)
                    .where(AiUsageCoverage.ended_at.is_(None))
                    .values(
                        ended_at=func.greatest(func.clock_timestamp(), AiUsageCoverage.started_at)
                    )
                )

            cutoff = func.now() - timedelta(days=retention_days)
            expired = (
                select(AiUsageReceipt.attempt_id)
                .where(AiUsageReceipt.started_at < cutoff)
                .order_by(AiUsageReceipt.started_at, AiUsageReceipt.attempt_id)
                .limit(500)
                .with_for_update(skip_locked=True)
            )
            removed = await session.execute(
                delete(AiUsageReceipt).where(AiUsageReceipt.attempt_id.in_(expired))
            )
            if removed.rowcount > 0:
                marker = insert(MetricCoverage).values(name=AI_USAGE_RETENTION_CUTOFF, since=cutoff)
                await session.execute(
                    marker.on_conflict_do_update(
                        index_elements=[MetricCoverage.name],
                        set_={"since": func.greatest(MetricCoverage.since, marker.excluded.since)},
                    )
                )
