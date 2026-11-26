"""Bounded aggregation over the ledger in the administration read transaction."""

from datetime import UTC, datetime, time, timedelta

from sqlalchemy import Date, Numeric, cast, func, or_, select

from src.adapters.storage.postgres.accounts import User
from src.adapters.storage.postgres.administration_models import MetricCoverage
from src.adapters.storage.postgres.ai_usage_models import AiUsageCoverage, AiUsageReceipt
from src.core.administration.ai_usage_queries import (
    AI_USAGE_RETENTION_CUTOFF,
    UsageAmounts,
    UsageDay,
    UsageFeature,
    UsageModel,
    UsageRanking,
    UsageSummary,
    UsageUser,
    amounts_for,
    coverage_for,
)
from src.core.administration.rules import ZONE, period_start

receipt = AiUsageReceipt


def usage_columns():
    total = func.coalesce(
        receipt.total_tokens, cast(receipt.input_tokens, Numeric) + receipt.output_tokens
    )
    return (
        func.count().label("attempts"),
        func.count()
        .filter(total.is_(None), receipt.duration_seconds.is_(None))
        .label("unmeasured_attempts"),
        func.sum(receipt.input_tokens).label("input_tokens"),
        func.sum(receipt.output_tokens).label("output_tokens"),
        func.sum(total).label("total_tokens"),
        func.sum(receipt.duration_seconds).label("duration_seconds"),
    )


class PostgresAiUsageQueries:
    def __init__(self, session, retention_days, now=None):
        self.session = session
        self.retention_days = retention_days
        self.now = now or datetime.now(UTC)

    async def _bounds(self, days):
        start = period_start(self.now, days)
        cutoff = self.now - timedelta(days=self.retention_days)
        purged = await self.session.scalar(
            select(MetricCoverage.since).where(MetricCoverage.name == AI_USAGE_RETENTION_CUTOFF)
        )
        return start, max(start, cutoff, purged or cutoff)

    async def summary(self, days, user_id):
        if user_id is not None:
            user_exists = await self.session.scalar(select(User.id).where(User.id == user_id))
            if user_exists is None:
                return None
        start, retained = await self._bounds(days)
        predicates = [receipt.started_at >= retained, receipt.started_at < self.now]
        if user_id is not None:
            predicates.append(receipt.user_id == user_id)

        periods = await self.session.execute(
            select(AiUsageCoverage.started_at, AiUsageCoverage.ended_at)
            .where(
                AiUsageCoverage.started_at < self.now,
                or_(AiUsageCoverage.ended_at.is_(None), AiUsageCoverage.ended_at > retained),
            )
            .order_by(AiUsageCoverage.started_at)
        )
        intervals = [(max(lower, retained), upper or self.now) for lower, upper in periods]

        totals_row = (
            await self.session.execute(
                select(*usage_columns()).select_from(receipt).where(*predicates)
            )
        ).one()
        totals = UsageAmounts.model_validate(totals_row._mapping)
        coverage = coverage_for(start, self.now, intervals, totals)
        day = cast(func.timezone(str(ZONE), receipt.started_at), Date).label("day")
        rows = await self.session.execute(
            select(day, *usage_columns()).where(*predicates).group_by(day)
        )
        by_day = {row.day: UsageAmounts.model_validate(row._mapping) for row in rows}
        daily = []
        first_day = start.astimezone(ZONE).date()
        for offset in range(days):
            date = first_day + timedelta(days=offset)
            lower = datetime.combine(date, time.min, ZONE)
            upper = min(datetime.combine(date + timedelta(days=1), time.min, ZONE), self.now)
            usage = by_day.get(date, UsageAmounts())
            state = coverage_for(lower, upper, intervals, usage)
            daily.append(
                UsageDay(date=date, coverage=state, **amounts_for(state, usage).model_dump())
            )

        model = func.coalesce(receipt.effective_model, receipt.requested_model).label("model")
        models = await self.session.execute(
            select(receipt.provider, model, *usage_columns())
            .where(*predicates)
            .group_by(receipt.provider, model)
            .order_by(receipt.provider, model)
        )
        features = await self.session.execute(
            select(receipt.feature, *usage_columns())
            .where(*predicates)
            .group_by(receipt.feature)
            .order_by(receipt.feature)
        )
        return UsageSummary(
            period_days=days,
            user_id=user_id,
            updated_at=self.now,
            coverage=coverage,
            totals=amounts_for(coverage, totals),
            daily=daily,
            by_model=[UsageModel.model_validate(row._mapping) for row in models],
            by_feature=[UsageFeature.model_validate(row._mapping) for row in features],
        )

    async def ranking(self, days, page, per_page):
        _, retained = await self._bounds(days)
        grouped = (
            select(receipt.user_id, *usage_columns())
            .where(
                receipt.started_at >= retained,
                receipt.started_at < self.now,
                receipt.user_id.is_not(None),
            )
            .group_by(receipt.user_id)
            .cte()
        )
        total = await self.session.scalar(select(func.count()).select_from(grouped))
        rows = await self.session.execute(
            select(*grouped.c, User.email)
            .join(User, User.id == grouped.c.user_id)
            .order_by(grouped.c.total_tokens.desc().nulls_last(), grouped.c.user_id)
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        return UsageRanking(
            period_days=days,
            page=page,
            per_page=per_page,
            total=total,
            items=[UsageUser.model_validate(row._mapping) for row in rows],
        )
