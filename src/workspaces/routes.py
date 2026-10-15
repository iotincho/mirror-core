"""Authenticated setup status and explicit recovery for a personal workspace."""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.user_management.database import get_async_session
from src.user_management.dependencies import AuthenticatedUser, get_authenticated_user
from src.workspaces.models import UserWorkspace, WorkspaceStatus
from src.workspaces.provisioning import provision_workspace_for_user
from src.workspaces.repository import WorkspaceRepository
from src.workspaces.secrets import WorkspaceSecretCipher, WorkspaceSecretError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workspace", tags=["workspace"])


class WorkspaceSetupRead(BaseModel):
    status: Literal["pending", "provisioning", "active", "failed", "suspended", "unavailable"]


def setup_status(workspace: UserWorkspace | None) -> WorkspaceSetupRead:
    if workspace is None:
        return WorkspaceSetupRead(status="unavailable")
    if workspace.status == WorkspaceStatus.ACTIVE:
        settings = get_settings()
        if workspace.arcadedb_instance_key != settings.arcadedb_instance_key:
            return WorkspaceSetupRead(status="unavailable")
        try:
            WorkspaceSecretCipher(settings).decrypt(workspace.graph_secret_ciphertext)
        except WorkspaceSecretError:
            return WorkspaceSetupRead(status="unavailable")
    return WorkspaceSetupRead(status=workspace.status)


@router.get("/status", response_model=WorkspaceSetupRead)
async def workspace_status(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> WorkspaceSetupRead:
    return setup_status(await WorkspaceRepository(session).get(user.id))


@router.post("/prepare", response_model=WorkspaceSetupRead)
async def prepare_workspace(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> WorkspaceSetupRead:
    workspace = await WorkspaceRepository(session).get(user.id)
    if workspace is not None and workspace.status in {
        WorkspaceStatus.ACTIVE,
        WorkspaceStatus.PROVISIONING,
        WorkspaceStatus.SUSPENDED,
    }:
        return setup_status(workspace)
    try:
        # The provisioner serializes retries for an existing allocation and reuses
        # its database, principal and secret. Never accept a user ID from the client.
        return setup_status(await provision_workspace_for_user(user.id))
    except Exception as error:
        logger.exception("workspace_setup_retry_failed user_id=%s", user.id)
        raise HTTPException(status_code=503, detail="Personal workspace is unavailable") from error
