"""Preview projection and temporary bridge for historical readers (stages 3/4)."""

from src.bootstrap.personal_axes_reads import build_axis_exploration
from src.extractors.personal_axes.contracts import legacy_errors


class AxisExploration:
    def __init__(self, previews):
        self.case = build_axis_exploration(
            previews.processing.sessions, previews.runtime, owner=previews.owner
        )

    @legacy_errors
    async def coverage(self, *args, **kwargs):
        return await self.case.coverage(*args, **kwargs)

    @legacy_errors
    async def finding(self, *args, **kwargs):
        return await self.case.finding(*args, **kwargs)

    @legacy_errors
    async def findings(self, *args, **kwargs):
        return await self.case.findings(*args, **kwargs)

    @legacy_errors
    async def tags(self, *args, **kwargs):
        return await self.case.tags(*args, **kwargs)

    @legacy_errors
    async def neighbors(self, *args, **kwargs):
        return await self.case.neighbors(*args, **kwargs)
