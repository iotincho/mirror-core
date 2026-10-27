"""Apply a reservation's typed write priority through the canonical extractor."""

from uuid import UUID

from src.core.extractors.personal_axes.ports import AxisWriteContexts


class PersistPersonalAxis:
    def __init__(self, contexts: AxisWriteContexts):
        self.contexts = contexts

    async def context_for(self, record):
        spec = record.config["extractor"]
        return await self.contexts.for_reservation(
            record.user_id, record.id, UUID(spec["axis_id"]), UUID(spec["version_id"])
        )

    async def execute(self, extractor, output, record):
        await extractor.persist(output, write_context=await self.context_for(record))
