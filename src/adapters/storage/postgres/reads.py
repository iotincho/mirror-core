"""Translate read-only repository results to detached processing jobs."""

from src.adapters.storage.postgres.boundaries import database_call
from src.adapters.storage.postgres.state import snapshot


class PostgresProcessingReads:
    def __init__(self, repository):
        self.repository = repository

    @database_call
    async def list_for_owner(self, owner, **page):
        return [snapshot(row) for row in await self.repository.list_for_owner(owner, **page)]

    @database_call
    async def get(self, processing_id, owner):
        return snapshot(await self.repository.get(processing_id, owner))

    @database_call
    async def extractor_children(self, parent, owner):
        return [snapshot(row) for row in await self.repository.extractor_children(parent, owner)]

    @database_call
    async def latest(self, owner, resource, workflow):
        return snapshot(await self.repository.latest(owner, resource, workflow))
