"""Legacy dictionary facade for previews/history until stages 3/4."""

from src.adapters.access.api.public.personal_axes.responses import axis_response
from src.adapters.storage.postgres.personal_axes.definitions import PostgresAxisDefinitions
from src.extractors.personal_axes.contracts import legacy_errors


class AxisRepository:
    def __init__(self, sessions):
        self.store = PostgresAxisDefinitions(sessions)

    @legacy_errors
    async def get(self, *args):
        return axis_response(await self.store.get(*args))

    @legacy_errors
    async def version(self, *args):
        return axis_response(await self.store.version(*args))

    @legacy_errors
    async def list(self, *args):
        result = await self.store.list(*args)
        return {
            "items": [axis_response(item) for item in result.items],
            "next_offset": result.next_offset,
        }

    @legacy_errors
    async def set_enabled(self, *args):
        return axis_response(await self.store.set_enabled(*args))

    @legacy_errors
    async def accept(self, *args):
        return axis_response(await self.store.accept(*args))
