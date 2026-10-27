"""Explicit extraction commands use the same durable resource locks as jobs."""

from contextlib import asynccontextmanager

from src.adapters.storage.postgres.boundaries import database_call
from src.adapters.storage.postgres.state import database_errors


class CommandProcessing:
    def __init__(self, repository):
        self.repository = repository

    @asynccontextmanager
    async def resource_guard(self, owner, resource):
        async with database_errors(), self.repository.lock_resource(owner, resource) as acquired:
            yield acquired

    @database_call
    async def assert_inactive(self, owner, resource):
        await self.repository.assert_inactive(owner, resource)
