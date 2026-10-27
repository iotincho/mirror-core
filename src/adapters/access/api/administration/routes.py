"""LAN administration routes; cases own queries and durable permission changes."""

from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.core.administration.models import (
    ActivitySeries,
    DashboardSummary,
    LaboratoryAccessUpdate,
    UserList,
    UserRead,
)
from src.use_cases.administration.query import Administration, AdministrationError


async def respond(action, *args):
    try:
        return await action(*args)
    except AdministrationError as error:
        status = 404 if error.code == "user_not_found" else 422
        raise HTTPException(status, error.code) from None


async def require_admin_same_origin(request: Request):
    # LAN administration has no public-app cookies. Restrict browser mutations
    # to this exact origin; never allow the public application's origin list.
    origin = request.headers.get("origin")
    if request.headers.get("sec-fetch-site") == "cross-site" or (
        origin
        and (urlsplit(origin).scheme, urlsplit(origin).netloc)
        != (request.url.scheme, request.url.netloc)
    ):
        raise HTTPException(403, "cross_origin_request")


def build_router(get_read_administration, get_write_administration):
    router = APIRouter(prefix="/api/admin", tags=["administration"])
    ReadService = Annotated[Administration, Depends(get_read_administration)]
    WriteService = Annotated[Administration, Depends(get_write_administration)]

    @router.get("/users", response_model=UserList)
    async def users(
        service: ReadService,
        page: Annotated[int, Query(ge=1)] = 1,
        per_page: Annotated[int, Query(ge=1, le=100)] = 10,
        sort: Literal[
            "email", "id", "is_active", "created_at", "last_activity_at", "notes_count"
        ] = "email",
        order: Literal["asc", "desc"] = "asc",
        q: Annotated[str, Query(max_length=200)] = "",
        is_active: bool | None = None,
    ):
        return await respond(service.list_users, page, per_page, sort, order, q, is_active)

    @router.get("/users/{user_id}", response_model=UserRead)
    async def user(user_id: UUID, service: ReadService):
        return await respond(service.user, user_id)

    @router.patch(
        "/users/{user_id}/laboratory",
        response_model=UserRead,
        dependencies=[Depends(require_admin_same_origin)],
    )
    async def laboratory_access(user_id: UUID, body: LaboratoryAccessUpdate, service: WriteService):
        return await respond(service.set_laboratory_access, user_id, body.laboratory_enabled)

    @router.get("/dashboard/summary", response_model=DashboardSummary)
    async def summary(service: ReadService, period_days: int = 30):
        return await respond(service.summary, period_days)

    @router.get("/dashboard/activity", response_model=ActivitySeries)
    async def activity(service: ReadService, period_days: int = 30):
        return await respond(service.activity, period_days)

    return router
