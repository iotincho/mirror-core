"""Durable migration checkpoints and processing cutover in PostgreSQL."""

from contextlib import asynccontextmanager

from sqlalchemy import func, select

from src.adapters.storage.postgres.boundaries import database_call
from src.adapters.storage.postgres.migration_models import DataMigration
from src.adapters.storage.postgres.models import ProcessingRecord
from src.adapters.storage.postgres.repository import ProcessingRepository
from src.adapters.storage.postgres.state import database_errors, snapshot
from src.adapters.storage.postgres.workspace_models import UserWorkspace
from src.core.maintenance.models import (
    MIGRATION_ID,
    MigrationState,
    MigrationWorkspace,
    ProcessingHistory,
)


class PostgresMigrations:
    def __init__(self, sessions, instance_key, lease_seconds):
        self.sessions, self.instance_key = sessions, instance_key
        self.repository = ProcessingRepository(sessions, lease_seconds)

    @asynccontextmanager
    async def lock(self):
        # Dedicated connection: no lease expiry can allow concurrent migration writers.
        async with database_errors(), self.sessions() as session:
            acquired = await session.scalar(
                select(
                    func.pg_try_advisory_lock(
                        func.hashtextextended(f"data-migration:{self.instance_key}", 0)
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
                            func.hashtextextended(f"data-migration:{self.instance_key}", 0)
                        )
                    )
                )

    def key(self, target):
        return MIGRATION_ID, self.instance_key, str(target)

    @database_call
    async def state(self, target):
        async with database_errors(), self.sessions() as session:
            row = await session.get(DataMigration, self.key(target))
            return MigrationState(row.status, row.details) if row else None

    @database_call
    async def save(self, target, status, details):
        async with self.sessions.begin() as session:
            record = await session.get(DataMigration, self.key(target), with_for_update=True)
            if record is None:
                record = DataMigration(
                    migration_id=MIGRATION_ID,
                    instance_key=self.instance_key,
                    target=str(target),
                )
                session.add(record)
            record.status, record.details = status, details
            record.completed_at = (
                await session.scalar(select(func.clock_timestamp()))
                if status == "completed"
                else None
            )

    @database_call
    async def _discover(self):
        async with database_errors(), self.sessions() as session:
            return list(
                (
                    await session.scalars(
                        select(UserWorkspace)
                        .where(UserWorkspace.arcadedb_instance_key == self.instance_key)
                        .order_by(UserWorkspace.user_id)
                    )
                ).all()
            )

    @database_call
    async def _processing(self, workspace):
        async with database_errors(), self.sessions() as session:
            return list(
                (
                    await session.scalars(
                        select(ProcessingRecord).where(
                            ProcessingRecord.user_id == workspace.user_id
                        )
                    )
                ).all()
            )

    @database_call
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

    @database_call
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

    @database_call
    async def discover(self):
        return [
            MigrationWorkspace(row.user_id, row.database_name, row.status)
            for row in await self._discover()
        ]

    @database_call
    async def processing(self, workspace):
        records = await self._processing(workspace)
        return ProcessingHistory(
            [snapshot(row) for row in records],
            [
                {column.name: getattr(row, column.name) for column in row.__table__.columns}
                for row in records
            ],
        )

    @database_call
    async def retire_legacy_jobs(self, owner):
        async with self.repository.sessions.begin() as session:
            current = list(
                (
                    await session.scalars(
                        select(ProcessingRecord)
                        .where(
                            ProcessingRecord.user_id == owner,
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
                self.repository.event(session, record)
                await self.repository.wake_parent(session, record, now)
