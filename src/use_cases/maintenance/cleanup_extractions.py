"""Explicit workspace cleanup policy with verified backups and processing cutover."""

from src.core.maintenance.ports import MigrationResources, MigrationStore
from src.use_cases.maintenance.extraction_cleanup import LegacyExtractionCleanup


class CleanupExtractions:
    def __init__(self, store: MigrationStore, resources: MigrationResources, instance_key):
        self.store, self.resources, self.instance_key = store, resources, instance_key

    async def execute(self, owner, instance, *, apply=False, services_stopped=False, backup=None):
        if instance != self.instance_key:
            raise ValueError("Instance does not match runtime configuration")
        workspace = next((w for w in await self.store.discover() if w.user_id == owner), None)
        if workspace is None:
            raise ValueError("Workspace is unavailable")
        history = await self.store.processing(workspace)
        records = history.records
        async with self.resources.open(workspace) as (graph, files):
            cleaner = LegacyExtractionCleanup(graph, files)
            inventory = await cleaner.inventory()
            documents = await files.documents()
            source_ids = {str(document.id) for document in documents}
            if any(row["id"] not in source_ids for row in inventory["records"].get("Document", [])):
                raise ValueError("Graph document missing its original file; cleanup refused")
            summary = {
                "instance": instance,
                "workspace": str(owner),
                "database": workspace.database_name,
                "graph_records": {
                    name: len(values) for name, values in inventory["records"].items()
                },
                "source_files": len(inventory["sources"]),
                "derived_files": len(inventory["files"]),
                "active_processing": sum(
                    r.status in {"running", "queued", "waiting", "retrying"} for r in records
                ),
                "applied": False,
            }
            if not apply:
                return summary
            if not services_stopped or not backup:
                raise ValueError("Apply requires --services-stopped and --backup outside workspace")
            if any(r.status == "running" for r in records):
                raise ValueError("Running jobs must be drained/recovered before cleanup")
            await cleaner.apply(backup, inventory, history.rows)
            await self.store.retire_legacy_jobs(owner)
            documents = await files.documents()
            for document in documents:
                await graph.persist_document(document)
            if inventory["sources"] != (await cleaner.inventory())["sources"]:
                raise ValueError("Original files changed during cutover")
            summary.update(applied=True, synchronized_documents=len(documents), backup=str(backup))
            return summary
