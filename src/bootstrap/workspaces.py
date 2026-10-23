"""Compose owner-scoped workspace resolution, provisioning and runtime lifetime."""

from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.access.api.public.workspaces.routes import build_router
from src.adapters.providers.security.workspaces import WorkspaceSecretCipher as Cipher
from src.adapters.storage.arcadedb.provisioning import ArcadeDBProvisioning
from src.adapters.storage.arcadedb.schema import migration_version
from src.adapters.storage.filesystem.audio_notes import FileAudioNoteStore
from src.adapters.storage.filesystem.documents import FileDocumentStore
from src.adapters.storage.postgres.workspaces import PostgresWorkspaces
from src.bootstrap.auth import get_authenticated_user
from src.bootstrap.database import get_async_session, get_session_maker
from src.bootstrap.graph import build_graph_store
from src.config import get_settings
from src.core.auth.identity import AuthenticatedUser
from src.core.workspaces.context import UserWorkspaceContext, WorkspaceBinding, WorkspaceRuntime
from src.core.workspaces.models import WorkspaceUnavailable
from src.use_cases.workspaces.access import WorkspaceAccess
from src.use_cases.workspaces.provision import ReconcileWorkspaces, WorkspaceProvisioner


def WorkspaceSecretCipher(settings):
    return Cipher(settings.workspace_secret_key, session_secret=settings.auth_session_secret)


class ConfiguredCipher:
    """Validate encryption configuration when the workspace operation needs it."""

    def __init__(self, settings):
        self.settings = settings

    def encrypt(self, value):
        return WorkspaceSecretCipher(self.settings).encrypt(value)

    def decrypt(self, ciphertext):
        return WorkspaceSecretCipher(self.settings).decrypt(ciphertext)


def build_provisioner(session_maker, settings):
    return WorkspaceProvisioner(
        PostgresWorkspaces(session_maker),
        ArcadeDBProvisioning(
            settings.arcadedb_http_url,
            settings.arcadedb_username,
            settings.arcadedb_password,
        ),
        ConfiguredCipher(settings),
        instance_key=settings.arcadedb_instance_key,
        schema_version=migration_version(),
    )


async def provision_workspace_for_user(user_id):
    return await build_provisioner(get_session_maker(), get_settings()).provision(user_id)


async def reconcile_active_workspaces():
    sessions, settings = get_session_maker(), get_settings()
    await ReconcileWorkspaces(
        PostgresWorkspaces(sessions),
        build_provisioner(sessions, settings),
    ).execute()


def workspace_access(*, session=None, settings=None):
    settings = settings or get_settings()
    sessions = get_session_maker()
    return WorkspaceAccess(
        PostgresWorkspaces(sessions, session=session),
        ConfiguredCipher(settings),
        settings.arcadedb_instance_key,
        build_provisioner(sessions, settings),
    )


def get_workspace_access(session: Annotated[AsyncSession, Depends(get_async_session)]):
    return workspace_access(session=session)


def workspace_binding(resolved, settings):
    workspace = resolved.workspace
    return WorkspaceBinding(
        UserWorkspaceContext(
            user_id=workspace.user_id,
            arcadedb_instance_key=workspace.arcadedb_instance_key,
            database_name=workspace.database_name,
            graph_username=workspace.graph_username,
            filesystem_root=settings.workspaces_path / str(workspace.user_id),
        ),
        resolved.graph_secret,
    )


async def get_workspace_binding(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
):
    settings = get_settings()
    try:
        resolved = await workspace_access(session=session, settings=settings).resolve(user.id)
    except WorkspaceUnavailable as error:
        raise HTTPException(503, detail=error.detail) from error
    return workspace_binding(resolved, settings)


def build_workspace_runtime(binding, settings):
    root = binding.context.filesystem_root
    return WorkspaceRuntime(
        context=binding.context,
        document_store=FileDocumentStore(root / "documents"),
        audio_note_store=FileAudioNoteStore(root / "audio-notes"),
        graph_store=build_graph_store(
            settings.arcadedb_http_url,
            binding.context.database_name,
            binding.context.graph_username,
            binding.graph_secret,
        ),
    )


async def get_workspace_runtime(
    binding: Annotated[WorkspaceBinding, Depends(get_workspace_binding)],
):
    runtime = build_workspace_runtime(binding, get_settings())
    try:
        yield runtime
    finally:
        await runtime.graph_store.close()


router = build_router(get_authenticated_user, get_workspace_access)
