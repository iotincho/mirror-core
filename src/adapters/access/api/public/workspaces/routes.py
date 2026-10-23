"""Authenticated workspace setup; ownership comes exclusively from the session."""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.core.auth.identity import AuthenticatedUser
from src.use_cases.workspaces.access import WorkspaceAccess

logger = logging.getLogger(__name__)


class WorkspaceSetupRead(BaseModel):
    status: Literal["pending", "provisioning", "active", "failed", "suspended", "unavailable"]


def build_router(get_authenticated_user, get_workspace_access):
    router = APIRouter(prefix="/workspace", tags=["workspace"])

    @router.get("/status", response_model=WorkspaceSetupRead)
    async def workspace_status(
        user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
        access: Annotated[WorkspaceAccess, Depends(get_workspace_access)],
    ):
        return WorkspaceSetupRead(status=await access.status(user.id))

    @router.post("/prepare", response_model=WorkspaceSetupRead)
    async def prepare_workspace(
        user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
        access: Annotated[WorkspaceAccess, Depends(get_workspace_access)],
    ):
        try:
            return WorkspaceSetupRead(status=await access.prepare(user.id))
        except Exception as error:
            logger.exception("workspace_setup_retry_failed user_id=%s", user.id)
            raise HTTPException(503, detail="Personal workspace is unavailable") from error

    return router
