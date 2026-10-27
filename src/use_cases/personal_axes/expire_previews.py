"""Expire temporary work and recover orphan inputs without filesystem or SQL knowledge."""

from datetime import datetime

from src.core.extractors.personal_axes.preview_ports import PreviewMaintenance, PreviewRoots


class ExpireAxisPreviews:
    def __init__(self, persistence: PreviewMaintenance, artifacts: PreviewRoots, clock):
        self.persistence, self.artifacts, self.clock = persistence, artifacts, clock

    async def execute(self):
        for record in await self.persistence.expired(50):
            async with self.persistence.guard(record.user_id, record.resource_id) as locked:
                if not locked:
                    continue
                await (
                    self.artifacts.for_owner(record.user_id)
                    .for_preview(record.resource_id)
                    .delete()
                )
                await self.persistence.remove(record.user_id, record.id)
        for location in await self.artifacts.candidates(200):
            store = self.artifacts.for_owner(location.owner).for_preview(location.preview_id)
            value = await store.read("input")
            if value is None or datetime.fromisoformat(value["expires_at"]) > self.clock():
                continue
            async with self.persistence.guard(location.owner, location.preview_id) as locked:
                if (
                    locked
                    and await self.persistence.get(location.owner, location.preview_id) is None
                ):
                    await store.delete()
