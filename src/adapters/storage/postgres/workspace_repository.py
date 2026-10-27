"""Persistence operations for workspace allocation and state transitions."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.storage.postgres.workspace_models import UserWorkspace, WorkspaceStatus


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

    async def list_active_user_ids(self) -> list[UUID]:
        statement = select(UserWorkspace.user_id).where(
            UserWorkspace.status == WorkspaceStatus.ACTIVE
        )
        return list((await self._session.scalars(statement)).all())

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

