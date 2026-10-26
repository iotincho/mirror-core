"""Coordinate verified cleanup across independent graph and file ports."""

from src.core.maintenance.ports import MigrationFiles, MigrationGraph


class LegacyExtractionCleanup:
    def __init__(self, graph: MigrationGraph, files: MigrationFiles):
        self.graph, self.files = graph, files

    async def inventory(self):
        files = await self.files.inventory()
        return {**await self.graph.inventory(), **files}

    async def apply(self, backup, expected, operational_history=None, *, resume=False):
        current = await self.inventory()
        expected = await self.files.prepare_backup(
            backup, current, expected, operational_history, resume=resume
        )
        async with self.graph.remove_derived(expected):
            await self.files.assert_sources(expected["sources"])
        await self.files.remove_derived(expected)
        after = await self.inventory()
        if after["sources"] != expected["sources"] or after["files"]:
            raise ValueError("Post-cleanup filesystem verification failed")
        if after["records"].get("Document", []) != expected["records"].get("Document", []):
            raise ValueError("Post-cleanup graph verification failed")
        await self.files.complete(backup)
        return after
