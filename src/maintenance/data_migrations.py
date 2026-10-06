"""Run registered, resumable deployment data migrations for the configured instance."""

import argparse
import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import func, select

from src.config import get_settings
from src.graph.arcadedb.client import AsyncArcadeDBHTTPClient
from src.graph.arcadedb.store import ArcadeDBGraphStore
from src.maintenance.extraction_cleanup import (
    LegacyExtractionCleanup,
    retired_files,
    source_fingerprints,
)
from src.maintenance.models import DataMigration
from src.processing.models import ProcessingRecord
from src.processing.repository import ProcessingRepository
from src.services.document_store import FileDocumentStore
from src.user_management.database import close_database, get_session_maker
from src.workspaces.arcade_admin import ArcadeDBAdminClient
from src.workspaces.models import UserWorkspace

MIGRATION_ID = "20261006-retire-exploratory-extraction"


class DataMigrations:
    def __init__(self, sessions, settings, backup_root=None, *, admin=None):
        self.sessions, self.settings = sessions, settings
        self.repository = ProcessingRepository(sessions, settings.processing_lease_seconds)
        self.backup_root = Path(
            backup_root or settings.workspaces_path.parent / "migration-backups"
        )
        self.admin = admin or ArcadeDBAdminClient(
            settings.arcadedb_http_url, settings.arcadedb_username, settings.arcadedb_password
        )

    @asynccontextmanager
    async def lock(self):
        # Dedicated connection: no lease expiry can allow concurrent migration writers.
        async with self.sessions() as session:
            acquired = await session.scalar(
                select(
                    func.pg_try_advisory_lock(
                        func.hashtextextended(
                            f"data-migration:{self.settings.arcadedb_instance_key}", 0
                        )
                    )
                )
            )
            if not acquired:
                raise ValueError("Another data migration is running")
            try:
                yield
            finally:
                await session.execute(
                    select(
                        func.pg_advisory_unlock(
                            func.hashtextextended(
                                f"data-migration:{self.settings.arcadedb_instance_key}", 0
                            )
                        )
                    )
                )

    def key(self, target):
        return MIGRATION_ID, self.settings.arcadedb_instance_key, str(target)

    async def state(self, target):
        async with self.sessions() as session:
            return await session.get(DataMigration, self.key(target))

    async def save(self, target, status, details):
        async with self.sessions.begin() as session:
            record = await session.get(DataMigration, self.key(target), with_for_update=True)
            if record is None:
                record = DataMigration(
                    migration_id=MIGRATION_ID,
                    instance_key=self.settings.arcadedb_instance_key,
                    target=str(target),
                )
                session.add(record)
            record.status, record.details = status, details
            record.completed_at = (
                await session.scalar(select(func.clock_timestamp()))
                if status == "completed"
                else None
            )

    async def discover(self):
        async with self.sessions() as session:
            return list(
                (
                    await session.scalars(
                        select(UserWorkspace)
                        .where(
                            UserWorkspace.arcadedb_instance_key
                            == self.settings.arcadedb_instance_key
                        )
                        .order_by(UserWorkspace.user_id)
                    )
                ).all()
            )

    async def processing(self, workspace):
        async with self.sessions() as session:
            return list(
                (
                    await session.scalars(
                        select(ProcessingRecord).where(
                            ProcessingRecord.user_id == workspace.user_id
                        )
                    )
                ).all()
            )

    async def assert_writers_stopped(self, workspace, records):
        # The deploy command stops API/worker/dispatcher first. These checks also
        # catch running executors if someone invokes the migration incorrectly.
        resources = {
            record.resource_id
            for record in records
            if record.status in ("running", "queued", "waiting", "retrying")
        }
        for resource in resources:
            async with self.repository.lock_resource(workspace.user_id, resource) as acquired:
                if not acquired:
                    raise ValueError(f"Workspace {workspace.user_id} still has an active executor")

    async def reconcile_processing(self, workspace):
        async with self.sessions.begin() as session:
            records = list(
                (
                    await session.scalars(
                        select(ProcessingRecord)
                        .where(ProcessingRecord.user_id == workspace.user_id)
                        .with_for_update()
                    )
                ).all()
            )
            now = await session.scalar(select(func.clock_timestamp()))
            migrated_children = set()
            for record in records:
                legacy = record.workflow == "document" and record.workflow_version == 1
                interrupted = record.status == "running"
                if not legacy and not interrupted:
                    continue
                record.generation += 1
                record.fencing_token += 1
                record.lease_owner = record.lease_expires_at = None
                record.version += 1
                record.updated_at = now
                if legacy:
                    record.extraction_run_id = None
                    record.checkpoints = {}
                    if record.status != "completed" and not record.resource_deleted:
                        # Pending/failed documents now only need their original in graph.
                        record.workflow_version = 2
                        record.stage = "document_persistence"
                        record.config = {}
                        migrated_children.add(record.id)
                if record.status != "completed" and not record.resource_deleted:
                    record.status = "queued"
                    record.error_code = None
                    record.retryable = False
                    record.stage_attempts = 0
                    record.available_at = now
                    record.completed_at = None
                    self.repository.schedule(session, record)
                else:
                    record.retryable = False
                    if record.resource_deleted and record.status != "completed":
                        record.status, record.error_code = "failed", "resource_deleted"
                self.repository.event(session, record)
                await self.repository.wake_parent(session, record, now)
            for parent in records:
                if (
                    parent.workflow == "audio"
                    and parent.child_processing_id in migrated_children
                    and parent.status in ("failed", "waiting")
                    and not parent.resource_deleted
                ):
                    parent.status = "waiting"
                    parent.error_code = None
                    parent.retryable = False
                    parent.lease_owner = parent.lease_expires_at = None
                    parent.generation += 1
                    parent.fencing_token += 1
                    parent.version += 1
                    parent.updated_at = now
                    parent.completed_at = None
                    self.repository.event(session, parent)

    def backup_path(self, workspace):
        instance = hashlib.sha256(self.settings.arcadedb_instance_key.encode()).hexdigest()[:16]
        return self.backup_root / MIGRATION_ID / instance / str(workspace.user_id)

    async def migrate_workspace(self, workspace, *, apply):
        root = self.settings.workspaces_path / str(workspace.user_id)
        records = await self.processing(workspace)
        if apply:
            await self.assert_writers_stopped(workspace, records)
        exists = await asyncio.to_thread(self.admin.database_exists, workspace.database_name)
        if not exists:
            # Include pending/failed registrations, but never hide missing user data.
            empty = not source_fingerprints(root) and not retired_files(root) and not records
            if workspace.status not in ("pending", "provisioning", "failed") or not empty:
                raise ValueError(f"Workspace {workspace.user_id} has a missing graph database")
            return {"workspace": str(workspace.user_id), "status": "unprovisioned_empty"}
        if not root.exists():
            # A provisioned but unused workspace may legitimately have no files yet.
            if apply:
                root.mkdir(parents=True)
            else:
                # Inventory must not create workspace directories on dry run.
                client = AsyncArcadeDBHTTPClient(
                    self.settings.arcadedb_http_url,
                    workspace.database_name,
                    self.settings.arcadedb_username,
                    self.settings.arcadedb_password,
                )
                try:
                    count = (
                        await client.query("MATCH (n) RETURN count(n) AS count", language="cypher")
                    )["result"]
                    if any(row["count"] for row in count) or records:
                        raise ValueError(
                            f"Workspace {workspace.user_id} has missing original files"
                        )
                    return {"workspace": str(workspace.user_id), "status": "empty"}
                finally:
                    await client.close()
        client = AsyncArcadeDBHTTPClient(
            self.settings.arcadedb_http_url,
            workspace.database_name,
            self.settings.arcadedb_username,
            self.settings.arcadedb_password,
        )
        graph = ArcadeDBGraphStore(
            self.settings.arcadedb_http_url,
            workspace.database_name,
            self.settings.arcadedb_username,
            self.settings.arcadedb_password,
            client=client,
        )
        try:
            cleaner = LegacyExtractionCleanup(client, root)
            inventory = await cleaner.inventory()
            documents = await FileDocumentStore(root / "documents").list()
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
            # Empty databases may not have Document yet; no original graph data is removed.
            if "Document" not in inventory["records"]:
                await client.command("CREATE VERTEX TYPE Document IF NOT EXISTS")
                inventory = await cleaner.inventory()
            history = [
                {column.name: getattr(record, column.name) for column in record.__table__.columns}
                for record in records
            ]
            backup = self.backup_path(workspace)
            await cleaner.apply(backup, inventory, history, resume=True)
            await self.reconcile_processing(workspace)
            for document in documents:
                await graph.persist_document(document)
            after = await cleaner.inventory()
            if after["sources"] != inventory["sources"] or after["files"]:
                raise ValueError("Source verification failed after migration")
            if any(values for name, values in after["records"].items() if name != "Document"):
                raise ValueError("Derived graph data remains after migration")
            summary.update(status="completed", backup=str(backup), documents=len(documents))
            return summary
        finally:
            await graph.close()

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


async def run_cli(args):
    try:
        migration = DataMigrations(get_session_maker(), get_settings(), args.backup_root)
        print(
            json.dumps(
                await migration.run(apply=args.apply, services_stopped=args.services_stopped),
                indent=2,
            )
        )
    finally:
        await close_database()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--services-stopped", action="store_true")
    parser.add_argument("--backup-root", type=Path)
    asyncio.run(run_cli(parser.parse_args()))


if __name__ == "__main__":
    main()
