"""Explicit foreground activity from an already authenticated PWA session."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from src.administration.activity import record_access
from src.api.routes.exteriorization import require_same_origin
from src.bootstrap.auth import get_authenticated_user
from src.bootstrap.database import get_session_maker
from src.config import get_settings
from src.core.auth.identity import AuthenticatedUser

router = APIRouter(prefix="/activity", tags=["activity"])


@router.post("", status_code=204, dependencies=[Depends(require_same_origin)])
async def activity(user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)]):
    if get_settings().platform_activity_enabled:
        await record_access(get_session_maker(), user.id)
    return Response(status_code=204)
