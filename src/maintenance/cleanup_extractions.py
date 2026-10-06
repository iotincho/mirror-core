"""Run with python -m src.maintenance.cleanup_extractions; default is inventory only."""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select

from src.config import get_settings
from src.maintenance.extraction_cleanup import LegacyExtractionCleanup
from src.processing.models import ProcessingRecord
from src.processing.runtime import get_repository
from src.processing.workflows import worker_runtime


async def run(args):
    settings = get_settings()
    if args.instance != settings.arcadedb_instance_key:
        raise ValueError("Instance does not match runtime configuration")
    repository = get_repository()
    async with repository.sessions() as session:
        records = list(
            (
                await session.scalars(
                    select(ProcessingRecord).where(ProcessingRecord.user_id == args.workspace)
                )
            ).all()
        )
        active = [r for r in records if r.status in ("running", "queued", "waiting", "retrying")]
    async with worker_runtime(args.workspace) as runtime:
        cleaner = LegacyExtractionCleanup(
            runtime.graph_store._client, runtime.context.filesystem_root
        )
        inventory = await cleaner.inventory()
        documents = await runtime.document_store.list()
        source_ids = {str(document.id) for document in documents}
        if any(row["id"] not in source_ids for row in inventory["records"].get("Document", [])):
            raise ValueError("Graph document missing its original file; cleanup refused")
        summary = {
            "instance": args.instance,
            "workspace": str(args.workspace),
            "database": runtime.context.database_name,
            "graph_records": {name: len(values) for name, values in inventory["records"].items()},
            "source_files": len(inventory["sources"]),
            "derived_files": len(inventory["files"]),
            "active_processing": len(active),
            "applied": False,
        }
        if not args.apply:
            print(json.dumps(summary, indent=2))
            return
        if not args.services_stopped or not args.backup:
            raise ValueError("Apply requires --services-stopped and --backup outside workspace")
        if any(r.status == "running" for r in records):
            raise ValueError("Running jobs must be drained/recovered before cleanup")
        # Snapshot operational history before changing eligibility of old document jobs.
        backup = Path(args.backup)
        if backup.exists():
            raise ValueError("Backup destination already exists")
        history = [
            {column.name: getattr(r, column.name) for column in r.__table__.columns}
            for r in records
        ]
        await cleaner.apply(backup, inventory, history)
        async with repository.sessions.begin() as session:
            current = list(
                (
                    await session.scalars(
                        select(ProcessingRecord)
                        .where(
                            ProcessingRecord.user_id == args.workspace,
                            ProcessingRecord.workflow == "document",
                            ProcessingRecord.workflow_version == 1,
                        )
                        .with_for_update()
                    )
                ).all()
            )
            now = await session.scalar(select(func.clock_timestamp()))
            for record in current:
                # Keep historical success, but never retry an extraction checkpoint.
                record.retryable = False
                record.extraction_run_id = None
                if record.status not in ("completed", "failed"):
                    record.status = "failed"
                    record.error_code = "extraction_retired"
                    record.completed_at = now
                record.generation += 1
                record.fencing_token += 1
                record.lease_owner = record.lease_expires_at = None
                record.version += 1
                record.updated_at = now
                repository.event(session, record)
                await repository.wake_parent(session, record, now)
        # Backfill originals absent from graph and their full content; no model calls.
        documents = await runtime.document_store.list()
        for document in documents:
            await runtime.graph_store.persist_document(document)
        if inventory["sources"] != (await cleaner.inventory())["sources"]:
            raise ValueError("Original files changed during cutover")
        summary.update(applied=True, synchronized_documents=len(documents), backup=str(backup))
        print(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=UUID, required=True)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--services-stopped", action="store_true")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
