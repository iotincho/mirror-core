"""Stage 4 bridge: historical orchestration still receives its old dependencies."""

from src.adapters.access.api.public.personal_axes.responses import axis_response
from src.bootstrap.personal_axes_previews import build_axis_previews
from src.extractors.personal_axes.contracts import legacy_errors
from src.extractors.personal_axes.repository import AxisRepository


class AxisPreviews:
    def __init__(self, processing, runtime, settings):
        self.processing, self.runtime, self.settings = processing, runtime, settings
        self.axes = AxisRepository(processing.sessions)
        self.case = build_axis_previews(processing, runtime, settings)

    @property
    def owner(self):
        return self.case.owner

    @owner.setter
    def owner(self, value):
        self.case.owner = value

    def store(self, preview_id):
        return self.case.store(preview_id)

    @legacy_errors
    async def request(self, *args):
        # Long-lived test/history compositions read the current injected configuration too.
        from src.bootstrap.personal_axes_previews import configuration

        self.case.configuration = configuration(self.settings)
        return await self.case.request(*args)

    @legacy_errors
    async def snapshot(self, *args):
        return await self.case.snapshot(*args)

    @legacy_errors
    async def results(self, *args):
        return await self.case.results(*args)

    @legacy_errors
    async def retry(self, *args):
        return await self.case.retry(*args)

    @legacy_errors
    async def accept(self, *args):
        return axis_response(await self.case.accept(*args))
