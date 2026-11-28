"""Read-only administrative endpoints for model usage."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from src.adapters.access.api.administration.routes import respond
from src.core.administration.ai_usage_queries import UsageRanking, UsageSummary
from src.use_cases.administration.ai_usage import AiUsageAdministration


def build_router(get_ai_usage):
    router = APIRouter(prefix="/api/admin/usage", tags=["administration"])
    Service = Annotated[AiUsageAdministration, Depends(get_ai_usage)]

    @router.get("", response_model=UsageSummary)
    async def summary(service: Service, period_days: int = 30, user_id: UUID | None = None):
        return await respond(service.summary, period_days, user_id)

    @router.get("/users", response_model=UsageRanking)
    async def ranking(
        service: Service,
        period_days: int = 30,
        page: Annotated[int, Query(ge=1, le=1_000_000)] = 1,
        per_page: Annotated[int, Query(ge=1, le=100)] = 10,
    ):
        return await respond(service.ranking, period_days, page, per_page)

    return router
