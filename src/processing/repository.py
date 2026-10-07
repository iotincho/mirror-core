"""Short transactions: state, event and scheduling changes commit together."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import UUID, uuid4, uuid5

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from src.processing.configuration import document_workflow_version
from src.processing.models import ProcessingEvent, ProcessingOutbox, ProcessingRecord
from src.processing.projections import processing_projection
from src.workspaces.models import UserWorkspace


class LeaseLost(RuntimeError):
    """An expired or replaced worker may no longer commit progress."""


class ProcessingRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], lease_seconds: int = 90):
        self.sessions = sessions
        self.lease_seconds = lease_seconds

    @staticmethod
    def event(session, record):
        session.add(
            ProcessingEvent(
                processing_id=record.id,
                user_id=record.user_id,
                version=record.version,
                status=record.status,
                stage=record.stage,
                error_code=record.error_code,
                payload=processing_projection(record),
            )
        )

    @staticmethod
    def schedule(session, record):
        session.add(
            ProcessingOutbox(
                processing_id=record.id,
                generation=record.generation,
                available_at=record.available_at,
            )
        )

    async def create(
        self,
        *,
        user_id: UUID,
        workflow: str,
        stage: str,
        resource_kind: str,
        resource_id: UUID,
        config: dict | None = None,
        workflow_version: int = 1,
        document_id: UUID | None = None,
    ) -> ProcessingRecord:
        async with self.sessions.begin() as session:
            active = await session.scalar(
                select(UserWorkspace.user_id).where(
                    UserWorkspace.user_id == user_id,
                    UserWorkspace.status == "active",
                )
            )
            if active is None:
                raise ValueError("workspace_unavailable")
            record = ProcessingRecord(
                id=uuid4(),
                user_id=user_id,
                workflow=workflow,
                stage=stage,
                workflow_version=workflow_version,
                resource_kind=resource_kind,
                resource_id=resource_id,
                config=config or {},
                document_id=document_id or (resource_id if resource_kind == "document" else None),
            )
            session.add(record)
            await session.flush()
            self.event(session, record)
            self.schedule(session, record)
        return record

    async def get(self, processing_id: UUID, user_id: UUID) -> ProcessingRecord | None:
        async with self.sessions() as session:
            return await session.scalar(
                select(ProcessingRecord).where(
                    ProcessingRecord.id == processing_id,
                    ProcessingRecord.user_id == user_id,
                )
            )

    async def acquire(
        self, processing_id: UUID, generation: int, owner: str
    ) -> ProcessingRecord | None:
        async with self.sessions.begin() as session:
            record = await session.get(ProcessingRecord, processing_id, with_for_update=True)
            now = await session.scalar(select(func.clock_timestamp()))
            if (
                record is None
                or record.generation != generation
                or record.status not in {"queued", "retrying"}
                or record.available_at > now
            ):
                return None
            record.status = "running"
            record.attempts += 1
            record.stage_attempts += 1
            record.fencing_token += 1
            record.version += 1
            record.lease_owner = owner
            record.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            record.updated_at = now
            record.error_code = None
            record.retryable = False
            self.event(session, record)
        return record

    @asynccontextmanager
    async def leased(self, record: ProcessingRecord):
        async with self.sessions.begin() as session:
            current = await session.get(ProcessingRecord, record.id, with_for_update=True)
            now = await session.scalar(select(func.clock_timestamp()))
            if (
                current is None
                or current.status != "running"
                or current.fencing_token != record.fencing_token
                or current.lease_owner != record.lease_owner
                or current.lease_expires_at <= now
            ):
                raise LeaseLost(str(record.id))
            yield session, current, now

    async def heartbeat(self, record: ProcessingRecord):
        async with self.leased(record) as (_, current, now):
            current.lease_expires_at = now + timedelta(seconds=self.lease_seconds)

    async def advance(self, record: ProcessingRecord, stage: str, checkpoints: dict):
        async with self.leased(record) as (session, current, now):
            if current.version != record.version:
                raise LeaseLost(str(record.id))
            if current.stage != stage:
                current.stage_attempts = 1
            current.stage = stage
            current.checkpoints = {**current.checkpoints, **checkpoints}
            if "extraction_run_id" in checkpoints:
                current.extraction_run_id = UUID(checkpoints["extraction_run_id"])
            current.version += 1
            current.updated_at = now
            self.event(session, current)
            version = current.version
        record.stage, record.checkpoints, record.version = stage, current.checkpoints, version
        record.stage_attempts = current.stage_attempts
        record.extraction_run_id = current.extraction_run_id

    async def finish(
        self,
        record: ProcessingRecord,
        *,
        status: str = "completed",
        error_code: str | None = None,
        retry_delay: float | None = None,
        retryable: bool = False,
    ):
        if status not in {"completed", "failed", "waiting", "retrying"}:
            raise ValueError("invalid_final_status")
        async with self.leased(record) as (session, current, now):
            if current.version != record.version:
                raise LeaseLost(str(record.id))
            current.status = status
            current.error_code = error_code
            current.retryable = retryable
            current.version += 1
            current.updated_at = now
            current.lease_owner = None
            current.lease_expires_at = None
            current.completed_at = now if status == "completed" else None
            if status == "retrying":
                if retry_delay is None or retry_delay < 0:
                    raise ValueError("invalid_retry_delay")
                current.generation += 1
                current.available_at = now + timedelta(seconds=retry_delay)
                self.schedule(session, current)
            self.event(session, current)
            if status in {"completed", "failed"}:
                await self.wake_parent(session, current, now)

    async def claim_outbox(self, limit: int = 20) -> list[ProcessingOutbox]:
        async with self.sessions.begin() as session:
            now = await session.scalar(select(func.clock_timestamp()))
            rows = list(
                (
                    await session.scalars(
                        select(ProcessingOutbox)
                        .where(
                            ProcessingOutbox.published_at.is_(None),
                            ProcessingOutbox.available_at <= now,
                            or_(
                                ProcessingOutbox.claimed_until.is_(None),
                                ProcessingOutbox.claimed_until <= now,
                            ),
                        )
                        .order_by(ProcessingOutbox.available_at)
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for row in rows:
                row.claim_token = uuid4()
                row.claimed_until = now + timedelta(seconds=self.lease_seconds)
                row.attempts += 1
        return rows

    async def settle_outbox(self, row: ProcessingOutbox, *, published: bool):
        async with self.sessions.begin() as session:
            current = await session.get(ProcessingOutbox, row.id, with_for_update=True)
            if current is None or current.claim_token != row.claim_token:
                return
            now = await session.scalar(select(func.clock_timestamp()))
            if published:
                current.published_at = now
            else:
                current.available_at = now + timedelta(seconds=min(60, 2 ** min(row.attempts, 6)))
            current.claimed_until = None
            current.claim_token = None

    async def recover(self, replay_seconds: int = 300, max_attempts: int = 4) -> int:
        """Recover dead workers and republish jobs lost with a broker/queue."""
        async with self.sessions.begin() as session:
            now = await session.scalar(select(func.clock_timestamp()))
            rows = list(
                (
                    await session.scalars(
                        select(ProcessingRecord)
                        .where(
                            or_(
                                and_(
                                    ProcessingRecord.status == "running",
                                    ProcessingRecord.lease_expires_at <= now,
                                ),
                                and_(
                                    ProcessingRecord.status.in_(["queued", "retrying"]),
                                    ProcessingRecord.available_at
                                    <= now - timedelta(seconds=replay_seconds),
                                    ~select(ProcessingOutbox.id)
                                    .where(
                                        ProcessingOutbox.processing_id == ProcessingRecord.id,
                                        ProcessingOutbox.generation == ProcessingRecord.generation,
                                        ProcessingOutbox.published_at.is_(None),
                                    )
                                    .exists(),
                                ),
                            )
                        )
                        .limit(100)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for record in rows:
                expired = record.status == "running"
                if expired:
                    record.generation += 1
                    record.fencing_token += 1
                record.version += 1
                if expired:
                    record.status = (
                        "failed" if record.stage_attempts >= max_attempts else "retrying"
                    )
                record.error_code = "worker_lease_expired" if expired else "delivery_recovered"
                if expired:
                    record.retryable = True
                record.lease_owner = None
                record.lease_expires_at = None
                record.available_at = now
                record.updated_at = now
                if record.status in {"queued", "retrying"}:
                    self.schedule(session, record)
                self.event(session, record)
                if record.status == "failed":
                    await self.wake_parent(session, record, now)
        return len(rows)

    @asynccontextmanager
    async def resource_guard(self, processing_id: UUID):
        """Serialize cooperating executors for the same workspace/resource.

        Held on a dedicated connection for the execution, never a row lock.
        External adapters must remain idempotent if that connection is lost.
        """
        async with self.sessions.begin() as session:
            record = await session.get(ProcessingRecord, processing_id)
            if record is None:
                yield True
                return
            yield await self._acquire_resource_lock(
                session,
                record.user_id,
                record.resource_id,
                record.id if record.workflow == "extractor" else None,
            )

    async def workspace_active(self, user_id: UUID) -> bool:
        async with self.sessions() as session:
            return (
                await session.scalar(
                    select(UserWorkspace.status).where(
                        UserWorkspace.user_id == user_id,
                    )
                )
                == "active"
            )

    @staticmethod
    async def wake_parent(session, child, now):
        if child.parent_processing_id is None:
            return
        parent = await session.get(
            ProcessingRecord, child.parent_processing_id, with_for_update=True
        )
        if parent is None or parent.user_id != child.user_id or parent.status != "waiting":
            return
        if child.workflow == "extractor":
            if parent.workflow != "document" or parent.workflow_version != 4:
                return
            active = await session.scalar(
                select(ProcessingRecord.id)
                .where(
                    ProcessingRecord.parent_processing_id == parent.id,
                    ProcessingRecord.workflow == "extractor",
                    ProcessingRecord.status.not_in(["completed", "failed"]),
                )
                .limit(1)
            )
            if active is not None:
                return
        elif parent.child_processing_id != child.id:
            return
        parent.status = "queued"
        parent.generation += 1
        parent.version += 1
        parent.available_at = now
        parent.updated_at = now
        ProcessingRepository.event(session, parent)
        ProcessingRepository.schedule(session, parent)

    async def extractor_children(self, parent_id: UUID, user_id: UUID):
        async with self.sessions() as session:
            return list(
                (
                    await session.scalars(
                        select(ProcessingRecord)
                        .where(
                            ProcessingRecord.parent_processing_id == parent_id,
                            ProcessingRecord.user_id == user_id,
                            ProcessingRecord.workflow == "extractor",
                        )
                        .order_by(ProcessingRecord.extractor_name)
                    )
                ).all()
            )

    async def extractors_and_wait(self, record: ProcessingRecord, specifications: list[dict]):
        """Fork all layers, events and outbox atomically, or resume the same children."""
        async with self.leased(record) as (session, current, now):
            if current.version != record.version:
                raise LeaseLost(str(record.id))
            for spec in specifications:
                identifier = uuid5(current.id, "extractor:" + spec["name"])
                child = await session.get(ProcessingRecord, identifier)
                if child is None:
                    child = ProcessingRecord(
                        id=identifier,
                        user_id=current.user_id,
                        workflow="extractor",
                        workflow_version=1,
                        resource_kind="document",
                        resource_id=current.resource_id,
                        document_id=current.resource_id,
                        stage="extraction",
                        extractor_name=spec["name"],
                        extraction_run_id=uuid5(current.id, spec["name"]),
                        config={"extractor": spec},
                        parent_processing_id=current.id,
                    )
                    session.add(child)
                    await session.flush()
                    self.event(session, child)
                    self.schedule(session, child)
                elif child.config != {"extractor": spec} or child.user_id != current.user_id:
                    raise ValueError("extractor_configuration_changed")
            current.status = "waiting"
            current.stage_attempts = 0
            current.version += 1
            current.updated_at = now
            current.lease_owner = None
            current.lease_expires_at = None
            self.event(session, current)

    async def child_and_wait(self, record: ProcessingRecord, document_id: UUID):
        async with self.leased(record) as (session, current, now):
            if current.child_processing_id is None:
                child = ProcessingRecord(
                    id=uuid5(current.id, "document"),
                    user_id=current.user_id,
                    workflow="document",
                    workflow_version=document_workflow_version(current.config),
                    stage="document_persistence",
                    resource_kind="document",
                    resource_id=document_id,
                    document_id=document_id,
                    config=current.config,
                    parent_processing_id=current.id,
                )
                session.add(child)
                await session.flush()
                self.event(session, child)
                self.schedule(session, child)
                current.child_processing_id = child.id
            current.document_id = document_id
            current.status = "waiting"
            current.stage = "document_processing"
            current.stage_attempts = 0
            current.version += 1
            current.updated_at = now
            current.lease_owner = None
            current.lease_expires_at = None
            self.event(session, current)

    async def child(self, record: ProcessingRecord) -> ProcessingRecord | None:
        if record.child_processing_id is None:
            return None
        return await self.get(record.child_processing_id, record.user_id)

    async def list_for_owner(
        self, user_id: UUID, *, active: bool = False, cursor: UUID | None = None, limit: int = 50
    ):
        async with self.sessions() as session:
            query = select(ProcessingRecord).where(ProcessingRecord.user_id == user_id)
            if active:
                query = query.where(
                    ProcessingRecord.status.in_(
                        [
                            "queued",
                            "running",
                            "waiting",
                            "retrying",
                        ]
                    )
                )
            if cursor:
                anchor = await session.get(ProcessingRecord, cursor)
                if anchor is None or anchor.user_id != user_id:
                    raise ValueError("invalid_cursor")
                query = query.where(
                    or_(
                        ProcessingRecord.created_at < anchor.created_at,
                        and_(
                            ProcessingRecord.created_at == anchor.created_at,
                            ProcessingRecord.id < anchor.id,
                        ),
                    )
                )
            return list(
                (
                    await session.scalars(
                        query.order_by(
                            ProcessingRecord.created_at.desc(),
                            ProcessingRecord.id.desc(),
                        ).limit(limit)
                    )
                ).all()
            )

    async def latest(self, user_id: UUID, resource_id: UUID, kind: str):
        async with self.sessions() as session:
            return await session.scalar(
                select(ProcessingRecord)
                .where(
                    ProcessingRecord.user_id == user_id,
                    ProcessingRecord.resource_id == resource_id,
                    ProcessingRecord.resource_kind == kind,
                    ProcessingRecord.workflow == kind,
                )
                .order_by(ProcessingRecord.created_at.desc(), ProcessingRecord.id.desc())
                .limit(1)
            )

    @staticmethod
    async def _acquire_resource_lock(session, user_id, resource_id, branch_id=None):
        key = func.hashtextextended(f"{user_id}:{resource_id}", 0)
        lock = (
            func.pg_try_advisory_xact_lock_shared if branch_id else func.pg_try_advisory_xact_lock
        )
        if not await session.scalar(select(lock(key))):
            return False
        if branch_id is not None:
            return bool(
                await session.scalar(
                    select(
                        func.pg_try_advisory_xact_lock(
                            func.hashtextextended(f"{user_id}:extractor-job:{branch_id}", 0),
                        )
                    )
                )
            )
        return True

    @asynccontextmanager
    async def lock_resource(self, user_id: UUID, resource_id: UUID):
        async with self.sessions.begin() as session:
            yield await self._acquire_resource_lock(session, user_id, resource_id)

    @asynccontextmanager
    async def lock_extractor(self, user_id: UUID, resource_id: UUID, processing_id: UUID):
        """Concurrent branches share the document guard, and exclude duplicate executors."""
        async with self.sessions.begin() as session:
            yield await self._acquire_resource_lock(session, user_id, resource_id, processing_id)

    async def assert_inactive(self, user_id: UUID, resource_id: UUID, exclude=()):
        async with self.sessions() as session:
            active = await session.scalar(
                select(ProcessingRecord.id)
                .where(
                    ProcessingRecord.user_id == user_id,
                    ProcessingRecord.resource_id == resource_id,
                    ProcessingRecord.id.not_in(exclude),
                    ProcessingRecord.status.in_(["queued", "running", "waiting", "retrying"]),
                )
                .limit(1)
            )
            if active:
                raise ValueError("processing_active")

    async def mark_deleted(self, user_id: UUID, resource_id: UUID):
        async with self.sessions.begin() as session:
            rows = await session.scalars(
                select(ProcessingRecord)
                .where(
                    ProcessingRecord.user_id == user_id,
                    ProcessingRecord.resource_id == resource_id,
                )
                .with_for_update()
            )
            for record in rows:
                record.resource_deleted = True

    async def recover_parents(self):
        async with self.sessions.begin() as session:
            now = await session.scalar(select(func.clock_timestamp()))
            # Do not lock child here: wake_parent takes parent after child in finish().
            parent = aliased(ProcessingRecord)
            children = list(
                (
                    await session.scalars(
                        select(ProcessingRecord)
                        .join(
                            parent,
                            ProcessingRecord.parent_processing_id == parent.id,
                        )
                        .where(
                            ProcessingRecord.parent_processing_id.is_not(None),
                            ProcessingRecord.status.in_(["completed", "failed"]),
                            parent.status == "waiting",
                        )
                        .limit(100)
                    )
                ).all()
            )
            for child in children:
                await self.wake_parent(session, child, now)
