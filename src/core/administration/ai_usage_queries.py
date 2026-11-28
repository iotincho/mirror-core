"""Read models and coverage rules for the administrative usage ledger."""

from datetime import date, datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel

UsageCoverage = Literal["complete", "partial", "unavailable"]
AI_USAGE_RETENTION_CUTOFF = "ai_usage_retention_cutoff"


class UsageAmounts(BaseModel):
    attempts: int = 0
    unmeasured_attempts: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    duration_seconds: float | None = None


class UsageDay(UsageAmounts):
    date: date
    coverage: UsageCoverage


class UsageModel(UsageAmounts):
    provider: str
    model: str


class UsageFeature(UsageAmounts):
    feature: str


class UsageSummary(BaseModel):
    period_days: int
    user_id: UUID | None
    timezone: Literal["America/Argentina/Buenos_Aires"] = "America/Argentina/Buenos_Aires"
    updated_at: datetime
    coverage: UsageCoverage
    totals: UsageAmounts
    daily: list[UsageDay]
    by_model: list[UsageModel]
    by_feature: list[UsageFeature]


class UsageUser(UsageAmounts):
    user_id: UUID
    email: str


class UsageRanking(BaseModel):
    period_days: int
    page: int
    per_page: int
    total: int
    items: list[UsageUser]


class AiUsageQueries(Protocol):
    async def summary(self, days: int, user_id: UUID | None) -> UsageSummary | None: ...

    async def ranking(self, days: int, page: int, per_page: int) -> UsageRanking: ...


def coverage_for(start, end, intervals, usage: UsageAmounts) -> UsageCoverage:
    cursor = start
    observed = False
    for lower, upper in intervals:
        lower, upper = max(start, lower), min(end, upper)
        if lower >= upper:
            continue
        observed = True
        if lower > cursor:
            break
        cursor = max(cursor, upper)
        if cursor == end:
            return "partial" if usage.unmeasured_attempts else "complete"
    return "partial" if observed or usage.attempts else "unavailable"


def amounts_for(coverage: UsageCoverage, usage: UsageAmounts) -> UsageAmounts:
    if usage.attempts or coverage == "unavailable":
        return usage
    return UsageAmounts(input_tokens=0, output_tokens=0, total_tokens=0, duration_seconds=0)
