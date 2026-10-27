"""Detached workspace state within the allocation/state-transition transaction."""

from contextlib import asynccontextmanager

from src.adapters.storage.postgres.snapshots import SnapshotTracker
from src.adapters.storage.postgres.state import database_errors
from src.adapters.storage.postgres.workspace_repository import WorkspaceRepository
from src.core.workspaces.models import Workspace


class WorkspaceTransaction(SnapshotTracker):
    def __init__(self, session):
        super().__init__()
        self.repository = WorkspaceRepository(session)

    async def get(self, user_id, *, for_update=False):
        return self.track(await self.repository.get(user_id, for_update=for_update), Workspace)

    async def get_or_create(self, user_id, **allocation):
        return self.track(await self.repository.get_or_create(user_id, **allocation), Workspace)


class PostgresWorkspaces:
    def __init__(self, sessions, *, session=None):
        self.sessions, self.session = sessions, session

    async def read(self, user_id):
        async with database_errors():
            if self.session is not None:
                row = await WorkspaceRepository(self.session).get(user_id)
                return SnapshotTracker().track(row, Workspace)
            async with self.sessions() as session:
                row = await WorkspaceRepository(session).get(user_id)
                return SnapshotTracker().track(row, Workspace)

    async def active_user_ids(self):
        async with database_errors(), self.sessions() as session:
            return await WorkspaceRepository(session).list_active_user_ids()

    @asynccontextmanager
    async def transaction(self):
        async with database_errors(), self.sessions() as session, session.begin():
            transaction = WorkspaceTransaction(session)
            yield transaction
            transaction.synchronize()
