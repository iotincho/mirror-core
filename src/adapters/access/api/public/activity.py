"""Foreground observations use verified session ownership, with no client-selected ID."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from src.core.auth.identity import AuthenticatedUser
from src.use_cases.administration.record_access import RecordAccess


def build_router(get_authenticated_user, get_record_access, require_same_origin):
    router = APIRouter(prefix="/activity", tags=["activity"])

    @router.post("", status_code=204, dependencies=[Depends(require_same_origin)])
    async def activity(
        user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
        service: Annotated[RecordAccess, Depends(get_record_access)],
    ):
        await service.execute(user.id)
        return Response(status_code=204)

    return router
