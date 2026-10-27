"""Owner-scoped accepted definitions through the persistence port."""

from src.core.extractors.personal_axes.ports import AxisDefinitions as DefinitionsPort


class AxisDefinitions:
    def __init__(self, store: DefinitionsPort, owner):
        self.store, self.owner = store, owner

    async def get(self, axis_id):
        return await self.store.get(self.owner, axis_id)

    async def list(self, offset=0, limit=50):
        return await self.store.list(self.owner, offset, limit)

    async def version(self, axis_id, version_id):
        return await self.store.version(self.owner, axis_id, version_id)

    async def set_enabled(self, axis_id, enabled):
        return await self.store.set_enabled(self.owner, axis_id, enabled)
