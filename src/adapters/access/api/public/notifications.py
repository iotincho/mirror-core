"""Owner-scoped inbox routes; persistence and visibility belong behind application ports."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from src.core.auth.identity import AuthenticatedUser
from src.core.notifications.models import NotificationList, ReadAll
from src.use_cases.notifications.center import NotificationCenter


def build_router(get_authenticated_user, get_notifications, require_same_origin):
    router = APIRouter(
        prefix="/notifications", tags=["notifications"], dependencies=[Depends(require_same_origin)]
    )
    User = Annotated[AuthenticatedUser, Depends(get_authenticated_user)]
    Service = Annotated[NotificationCenter, Depends(get_notifications)]

    @router.post("/bootstrap", status_code=204)
    async def bootstrap(user: User, service: Service):
        await service.bootstrap(user.id)

    @router.get("", response_model=NotificationList)
    async def notifications(
        user: User,
        service: Service,
        cursor: Annotated[str | None, Query(max_length=300)] = None,
        unread_only: bool = False,
        limit: Annotated[int, Query(ge=1, le=100)] = 30,
    ):
        return await service.list(user.id, cursor, unread_only, limit)

    @router.get("/summary")
    async def summary(user: User, service: Service):
        return await service.summary(user.id)

    @router.post("/read-all", status_code=204)
    async def read_all(payload: ReadAll, user: User, service: Service):
        await service.read_all(user.id, payload.through)

    @router.post("/{identifier}/read", status_code=204)
    async def read(identifier: UUID, user: User, service: Service):
        await service.mutate(user.id, identifier)

    @router.post("/{identifier}/dismiss", status_code=204)
    async def dismiss(identifier: UUID, user: User, service: Service):
        await service.mutate(user.id, identifier, dismiss=True)

    return router
