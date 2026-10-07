"""Request-scoped workspace resolution and storage composition."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, AsyncIterator

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings, get_settings
from src.graph.arcadedb.store import ArcadeDBGraphStore
from src.services.audio_note_store import FileAudioNoteStore
from src.services.document_store import FileDocumentStore
from src.user_management.database import get_async_session
from src.user_management.dependencies import AuthenticatedUser, get_authenticated_user
from src.workspaces.context import UserWorkspaceContext
from src.workspaces.models import WorkspaceStatus
from src.workspaces.repository import WorkspaceRepository
from src.workspaces.secrets import WorkspaceSecretCipher, WorkspaceSecretError


@dataclass(frozen=True)
class WorkspaceBinding:
    """Private result of resolving an active workspace; never returned by the API."""

    context: UserWorkspaceContext
    graph_secret: str


@dataclass(frozen=True)
class WorkspaceRuntime:
    """Stores already limited to one authenticated user's workspace."""

    context: UserWorkspaceContext
    document_store: FileDocumentStore
    audio_note_store: FileAudioNoteStore
    graph_store: ArcadeDBGraphStore


async def get_workspace_binding(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> WorkspaceBinding:
    workspace = await WorkspaceRepository(session).get(user.id)
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Personal workspace is unavailable",
        )
    if workspace.status != WorkspaceStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Personal workspace is preparing",
        )

    settings = get_settings()
    if workspace.arcadedb_instance_key != settings.arcadedb_instance_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Personal workspace is unavailable",
        )
    try:
        secret = WorkspaceSecretCipher(settings).decrypt(workspace.graph_secret_ciphertext)
    except WorkspaceSecretError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Personal workspace is unavailable",
        ) from error

    return WorkspaceBinding(
        context=UserWorkspaceContext(
            user_id=user.id,
            arcadedb_instance_key=workspace.arcadedb_instance_key,
            database_name=workspace.database_name,
            graph_username=workspace.graph_username,
            filesystem_root=settings.workspaces_path / str(user.id),
        ),
        graph_secret=secret,
    )


def build_workspace_runtime(binding: WorkspaceBinding, settings: Settings) -> WorkspaceRuntime:
    """Build stores only after their filesystem and graph boundary is fixed."""
    root = binding.context.filesystem_root
    return WorkspaceRuntime(
        context=binding.context,
        document_store=FileDocumentStore(root / "documents"),
        audio_note_store=FileAudioNoteStore(root / "audio-notes"),
        graph_store=ArcadeDBGraphStore(
            settings.arcadedb_http_url,
            binding.context.database_name,
            binding.context.graph_username,
            binding.graph_secret,
        ),
    )


async def get_workspace_runtime(
    binding: Annotated[WorkspaceBinding, Depends(get_workspace_binding)],
) -> AsyncIterator[WorkspaceRuntime]:
    runtime = build_workspace_runtime(binding, get_settings())
    try:
        yield runtime
    finally:
        await runtime.graph_store.close()
