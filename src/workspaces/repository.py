"""Persistence operations for workspace allocation and state transitions."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.workspaces.models import UserWorkspace, WorkspaceStatus


def workspace_database_name(user_id: UUID) -> str:
    return f"es_{user_id.hex}"


def workspace_graph_username(user_id: UUID) -> str:
    return f"es_u_{user_id.hex}"


class WorkspaceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UUID, *, for_update: bool = False) -> UserWorkspace | None:
        statement = select(UserWorkspace).where(UserWorkspace.user_id == user_id)
        if for_update:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    async def get_or_create(
        self,
        user_id: UUID,
        *,
        arcadedb_instance_key: str,
        graph_secret_ciphertext: str,
    ) -> UserWorkspace:
        workspace = await self.get(user_id, for_update=True)
        if workspace is not None:
            return workspace

        workspace = UserWorkspace(
            user_id=user_id,
            arcadedb_instance_key=arcadedb_instance_key,
            database_name=workspace_database_name(user_id),
            graph_username=workspace_graph_username(user_id),
            graph_secret_ciphertext=graph_secret_ciphertext,
            status=WorkspaceStatus.PENDING,
        )
        self._session.add(workspace)
        await self._session.flush()
        return workspace

    @staticmethod
    def mark_provisioning(workspace: UserWorkspace) -> None:
        workspace.status = WorkspaceStatus.PROVISIONING
        workspace.last_error_code = None
        workspace.last_error = None
        workspace.updated_at = datetime.now(UTC)

    @staticmethod
    def mark_active(workspace: UserWorkspace, *, schema_version: str) -> None:
        now = datetime.now(UTC)
        workspace.status = WorkspaceStatus.ACTIVE
        workspace.schema_version = schema_version
        workspace.provisioned_at = now
        workspace.updated_at = now
        workspace.last_error_code = None
        workspace.last_error = None

    @staticmethod
    def mark_failed(workspace: UserWorkspace, *, code: str, detail: str) -> None:
        workspace.status = WorkspaceStatus.FAILED
        workspace.updated_at = datetime.now(UTC)
        workspace.last_error_code = code
        workspace.last_error = detail[:500]
