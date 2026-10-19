from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.administration.config import get_admin_settings
from src.administration.database import admin_session
from src.administration.repository import AdministrationRepository
from src.administration.schemas import ActivitySeries, DashboardSummary, UserList, UserRead

router = APIRouter(prefix="/api/admin", tags=["administration"])
Session = Annotated[AsyncSession, Depends(admin_session)]


def repository(session):
    return AdministrationRepository(session, get_admin_settings().inventory_max_age_seconds)


def period(days):
    if days not in (7, 30):
        raise HTTPException(422, "period_days must be 7 or 30")
    return days


@router.get("/users", response_model=UserList)
async def users(
    session: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 10,
    sort: Literal[
        "email", "id", "is_active", "created_at", "last_activity_at", "notes_count"
    ] = "email",
    order: Literal["asc", "desc"] = "asc",
    q: Annotated[str, Query(max_length=200)] = "",
    is_active: bool | None = None,
):
    return await repository(session).list_users(page, per_page, sort, order, q.strip(), is_active)


@router.get("/users/{user_id}", response_model=UserRead)
async def user(user_id: UUID, session: Session):
    result = await repository(session).user(user_id)
    if result is None:
        raise HTTPException(404, "user_not_found")
    return result


@router.get("/dashboard/summary", response_model=DashboardSummary)
async def summary(session: Session, period_days: int = 30):
    return await repository(session).summary(period(period_days))


@router.get("/dashboard/activity", response_model=ActivitySeries)
async def activity(session: Session, period_days: int = 30):
    return await repository(session).activity(period(period_days))
