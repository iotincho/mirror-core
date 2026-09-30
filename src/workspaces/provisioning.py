"""Idempotent provisioning of an isolated ArcadeDB workspace."""

from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import Settings, get_settings
from src.embeddings.contracts import EmbeddingSpec
from src.graph.arcadedb.schema import apply_schema, migration_version
from src.user_management.database import get_session_maker
from src.workspaces.arcade_admin import ArcadeDBAdminClient, ArcadeDBAdminError
from src.workspaces.models import UserWorkspace, WorkspaceStatus
from src.workspaces.repository import WorkspaceRepository
from src.workspaces.secrets import WorkspaceSecretCipher, WorkspaceSecretError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProvisioningTarget:
    user_id: UUID
    database_name: str
    graph_username: str
    graph_secret_ciphertext: str


class WorkspaceProvisioner:
    def __init__(
        self,
        session_maker: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._session_maker = session_maker
        self._settings = settings
        self._cipher = WorkspaceSecretCipher(settings)

    async def provision(self, user_id: UUID, *, force: bool = False) -> UserWorkspace:
        target, workspace = await self._start(user_id, force=force)
        if target is None:
            return workspace

        try:
            await asyncio.to_thread(self._provision_remote, target)
        except (ArcadeDBAdminError, WorkspaceSecretError) as error:
            logger.warning("workspace_provisioning_failed user_id=%s", user_id, exc_info=True)
            return await self._fail(user_id, code="arcadedb_provisioning_failed", detail=str(error))
        except Exception:
            logger.exception("workspace_provisioning_failed user_id=%s", user_id)
            return await self._fail(
                user_id,
                code="workspace_provisioning_failed",
                detail="Unexpected workspace provisioning failure",
            )

        return await self._activate(user_id)

    async def _start(
        self,
        user_id: UUID,
        *,
        force: bool,
    ) -> tuple[ProvisioningTarget | None, UserWorkspace]:
        async with self._session_maker() as session, session.begin():
            repository = WorkspaceRepository(session)
            workspace = await repository.get_or_create(
                user_id,
                arcadedb_instance_key=self._settings.arcadedb_instance_key,
                graph_secret_ciphertext=self._cipher.encrypt(secrets.token_urlsafe(32)),
            )
            if workspace.status == WorkspaceStatus.ACTIVE and not force:
                return None, workspace
            if workspace.status == WorkspaceStatus.PROVISIONING and not force:
                return None, workspace
            if workspace.status == WorkspaceStatus.SUSPENDED:
                return None, workspace

            repository.mark_provisioning(workspace)
            return (
                ProvisioningTarget(
                    user_id=workspace.user_id,
                    database_name=workspace.database_name,
                    graph_username=workspace.graph_username,
                    graph_secret_ciphertext=workspace.graph_secret_ciphertext,
                ),
                workspace,
            )

    def _provision_remote(self, target: ProvisioningTarget) -> None:
        secret = self._cipher.decrypt(target.graph_secret_ciphertext)
        admin = ArcadeDBAdminClient(
            self._settings.arcadedb_http_url,
            self._settings.arcadedb_username,
            self._settings.arcadedb_password,
        )
        admin.ensure_database(target.database_name)

        spec = EmbeddingSpec(
            provider=self._settings.embedding_provider,
            model=self._settings.openai_embedding_model,
            dimensions=self._settings.openai_embedding_dimensions,
        )
        from src.graph.arcadedb.client import ArcadeDBHTTPClient

        schema_client = ArcadeDBHTTPClient(
            self._settings.arcadedb_http_url,
            target.database_name,
            self._settings.arcadedb_username,
            self._settings.arcadedb_password,
        )
        apply_schema(schema_client, spec)
        admin.ensure_runtime_principal(
            database_name=target.database_name,
            username=target.graph_username,
            password=secret,
        )
        admin.verify_runtime_principal(
            database_name=target.database_name,
            username=target.graph_username,
            password=secret,
        )

    async def _activate(self, user_id: UUID) -> UserWorkspace:
        spec = EmbeddingSpec(
            provider=self._settings.embedding_provider,
            model=self._settings.openai_embedding_model,
            dimensions=self._settings.openai_embedding_dimensions,
        )
        async with self._session_maker() as session, session.begin():
            repository = WorkspaceRepository(session)
            workspace = await self._required_workspace(repository, user_id, for_update=True)
            repository.mark_active(workspace, schema_version=migration_version(spec))
            return workspace

    async def _fail(self, user_id: UUID, *, code: str, detail: str) -> UserWorkspace:
        async with self._session_maker() as session, session.begin():
            repository = WorkspaceRepository(session)
            workspace = await self._required_workspace(repository, user_id, for_update=True)
            repository.mark_failed(workspace, code=code, detail=detail)
            return workspace

    @staticmethod
    async def _required_workspace(
        repository: WorkspaceRepository,
        user_id: UUID,
        *,
        for_update: bool,
    ) -> UserWorkspace:
        workspace = await repository.get(user_id, for_update=for_update)
        if workspace is None:
            raise RuntimeError("workspace disappeared during provisioning")
        return workspace


async def provision_workspace_for_user(user_id: UUID) -> UserWorkspace:
    """Registration hook. Failures are persisted as workspace state, not raised to auth."""
    provisioner = WorkspaceProvisioner(get_session_maker(), get_settings())
    return await provisioner.provision(user_id)


async def reconcile_active_workspaces() -> None:
    """Refresh the server-owned ArcadeDB principal for every active workspace.

    Group definitions are not stored in PostgreSQL, so this repairs permission policy
    changes for workspaces that predate the currently running application version.
    """
    session_maker = get_session_maker()
    async with session_maker() as session:
        user_ids = await WorkspaceRepository(session).list_active_user_ids()

    provisioner = WorkspaceProvisioner(session_maker, get_settings())
    for user_id in user_ids:
        await provisioner.provision(user_id, force=True)
