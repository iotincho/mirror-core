"""Resumable deployment migration policy through durable state and storage ports."""

from src.core.maintenance.models import MIGRATION_ID
from src.core.maintenance.ports import MigrationResources, MigrationStore
from src.use_cases.maintenance.extraction_cleanup import LegacyExtractionCleanup


class DataMigrations:
    def __init__(
        self, store: MigrationStore, resources: MigrationResources, instance_key, backup_path
    ):
        self.store, self.resources = store, resources
        self.instance_key, self.backup_path = instance_key, backup_path

    def lock(self):
        return self.store.lock()

    async def state(self, target):
        return await self.store.state(target)

    async def save(self, target, status, details):
        return await self.store.save(target, status, details)

    async def discover(self):
        return await self.store.discover()

    async def migrate_workspace(self, workspace, *, apply):
        history = await self.store.processing(workspace)
        records = history.records
        if apply:
            await self.store.assert_writers_stopped(workspace, records)
        if not await self.resources.exists(workspace):
            files = self.resources.files(workspace)
            empty = await files.empty() and not records
            if workspace.status not in ("pending", "provisioning", "failed") or not empty:
                raise ValueError(f"Workspace {workspace.user_id} has a missing graph database")
            return {"workspace": str(workspace.user_id), "status": "unprovisioned_empty"}
        async with self.resources.open(workspace) as (graph, files):
            if not await files.exists():
                if apply:
                    await files.prepare()
                else:
                    if not await graph.empty() or records:
                        raise ValueError(
                            f"Workspace {workspace.user_id} has missing original files"
                        )
                    return {"workspace": str(workspace.user_id), "status": "empty"}
            cleaner = LegacyExtractionCleanup(graph, files)
            inventory = await cleaner.inventory()
            documents = await files.documents()
            source_ids = {str(document.id) for document in documents}
            if any(row["id"] not in source_ids for row in inventory["records"].get("Document", [])):
                raise ValueError(
                    f"Workspace {workspace.user_id} has graph documents without originals"
                )
            summary = {
                "workspace": str(workspace.user_id),
                "status": "inventoried",
                "source_files": len(inventory["sources"]),
                "derived_files": len(inventory["files"]),
                "graph_records": {
                    name: len(values) for name, values in inventory["records"].items()
                },
            }
            if not apply:
                return summary
            if "Document" not in inventory["records"]:
                await graph.ensure_documents()
                inventory = await cleaner.inventory()
            backup = self.backup_path(workspace)
            await cleaner.apply(backup, inventory, history.rows, resume=True)
            await self.store.reconcile_processing(workspace)
            for document in documents:
                await graph.persist_document(document)
            after = await cleaner.inventory()
            if after["sources"] != inventory["sources"] or after["files"]:
                raise ValueError("Source verification failed after migration")
            if any(values for name, values in after["records"].items() if name != "Document"):
                raise ValueError("Derived graph data remains after migration")
            summary.update(status="completed", backup=str(backup), documents=len(documents))
            return summary

    async def run(self, *, apply=False, services_stopped=False):
        if apply and not services_stopped:
            raise ValueError("Apply requires stopped API, workers and dispatcher")
        async with self.lock():
            previous = await self.state("__all__")
            if previous and previous.status == "completed":
                return {"migration": MIGRATION_ID, "status": "already_applied", "workspaces": []}
            workspaces = await self.discover()
            manifest = [
                {"user_id": str(w.user_id), "database": w.database_name} for w in workspaces
            ]
            if apply:
                if previous and previous.details.get("targets") != manifest:
                    raise ValueError(
                        "Workspace registry changed during migration; deployment refused"
                    )
                await self.save("__all__", "running", {"targets": manifest})
            result = []
            for workspace in workspaces:
                state = await self.state(workspace.user_id)
                if state and state.status == "completed":
                    result.append(
                        {"workspace": str(workspace.user_id), "status": "already_applied"}
                    )
                    continue
                if apply:
                    await self.save(
                        workspace.user_id, "running", {"database": workspace.database_name}
                    )
                summary = await self.migrate_workspace(workspace, apply=apply)
                if apply:
                    await self.save(workspace.user_id, "completed", summary)
                result.append(summary)
            if apply:
                if [
                    {"user_id": str(w.user_id), "database": w.database_name}
                    for w in await self.discover()
                ] != manifest:
                    raise ValueError(
                        "Workspace registry changed during migration; deployment refused"
                    )
                await self.save("__all__", "completed", {"targets": manifest})
            return {
                "migration": MIGRATION_ID,
                "status": "completed" if apply else "inventory",
                "workspaces": result,
            }
