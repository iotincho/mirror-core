"""Atomic preview quota, receipt/job/outbox, retry and bounded expiration."""

from contextlib import asynccontextmanager
from uuid import uuid4, uuid5

from sqlalchemy import delete, func, or_, select

from src.adapters.storage.postgres.models import (
    ProcessingOutbox,
    ProcessingReceipt,
    ProcessingRecord,
)
from src.adapters.storage.postgres.state import database_errors, snapshot
from src.core.extractors.personal_axes.models import AxisError
from src.core.processing.models import SubmissionReceipt


class PostgresPreviews:
    def __init__(self, repository):
        self._repository = repository

    async def get(self, owner, preview_id):
        async with database_errors():
            return snapshot(await self._repository.get(preview_id, owner))

    async def receipt(self, owner, operation, key):
        async with database_errors(), self._repository.sessions() as session:
            return snapshot(
                await session.scalar(
                    select(ProcessingReceipt).where(
                        ProcessingReceipt.user_id == owner,
                        ProcessingReceipt.operation == operation,
                        ProcessingReceipt.key == key,
                    )
                ),
                SubmissionReceipt,
            )

    @asynccontextmanager
    async def guard(self, owner, preview_id):
        async with database_errors(), self._repository.lock_resource(owner, preview_id) as locked:
            yield locked

    @asynccontextmanager
    async def sources(self, owner, ids, *, shared=False):
        async with (
            database_errors(),
            self._repository.lock_resources(owner, ids, shared=shared) as locked,
        ):
            yield locked

    @asynccontextmanager
    async def reservation(self, owner, max_pending):
        async with database_errors(), self._repository.sessions.begin() as session:
            now = await session.scalar(select(func.clock_timestamp()))
            locked = await session.scalar(
                select(
                    func.pg_try_advisory_xact_lock(
                        func.hashtextextended(f"{owner}:axis-preview-quota", 0)
                    )
                )
            )
            if not locked:
                raise AxisError("axis_preview_limit")
            pending = await session.scalar(
                select(func.count())
                .select_from(ProcessingRecord)
                .where(
                    ProcessingRecord.user_id == owner,
                    ProcessingRecord.workflow == "axis_preview",
                    ProcessingRecord.expires_at > now,
                    ProcessingRecord.status.in_(["queued", "running", "retrying"]),
                )
            )
            if pending >= max_pending:
                raise AxisError("axis_preview_limit")
            yield PreviewReservation(session, self._repository, owner, now)

    @asynccontextmanager
    async def retrying(self, owner, key):
        async with database_errors(), self._repository.sessions.begin() as session:
            locked = await session.scalar(
                select(
                    func.pg_try_advisory_xact_lock(
                        func.hashtextextended(f"{owner}:axis-retry:{key}", 0)
                    )
                )
            )
            if not locked:
                raise AxisError("axis_preview_busy")
            receipt = snapshot(
                await session.scalar(
                    select(ProcessingReceipt).where(
                        ProcessingReceipt.user_id == owner,
                        ProcessingReceipt.operation == "axis_preview_retry",
                        ProcessingReceipt.key == key,
                    )
                ),
                SubmissionReceipt,
            )
            yield PreviewRetry(session, self._repository, owner, receipt)

    async def expired(self, limit):
        async with database_errors(), self._repository.sessions() as session:
            records = await session.scalars(
                select(ProcessingRecord)
                .where(
                    ProcessingRecord.workflow == "axis_preview",
                    or_(
                        ProcessingRecord.expires_at <= func.clock_timestamp(),
                        ProcessingRecord.resource_deleted.is_(True),
                    ),
                )
                .order_by(ProcessingRecord.created_at)
                .limit(limit)
            )
            return [snapshot(row) for row in records]

    async def remove(self, owner, preview_id):
        async with database_errors(), self._repository.sessions.begin() as session:
            for model in (ProcessingReceipt, ProcessingOutbox):
                await session.execute(delete(model).where(model.processing_id == preview_id))
            await session.execute(
                delete(ProcessingRecord).where(
                    ProcessingRecord.id == preview_id,
                    ProcessingRecord.user_id == owner,
                    ProcessingRecord.workflow == "axis_preview",
                )
            )


class PreviewReservation:
    def __init__(self, session, repository, owner, now):
        self._session, self._repository, self._owner, self.now = session, repository, owner, now

    async def enqueue(self, preview_id, key, request_hash, sources, expires_at):
        record = ProcessingRecord(
            id=preview_id,
            user_id=self._owner,
            workflow="axis_preview",
            workflow_version=1,
            resource_kind="axis_preview",
            resource_id=preview_id,
            stage="prompt_generation",
            config={"preview_id": str(preview_id), "document_ids": list(sources)},
            expires_at=expires_at,
        )
        self._session.add(record)
        await self._session.flush()
        self._session.add(
            ProcessingReceipt(
                user_id=self._owner,
                operation="axis_preview",
                key=key,
                request_hash=request_hash,
                resource_kind="axis_preview",
                resource_id=preview_id,
                config={},
                manifest={},
                processing_id=preview_id,
                lease_token=uuid5(preview_id, "receipt"),
                lease_expires_at=self.now,
                accepted_at=self.now,
                expires_at=expires_at,
            )
        )
        self._repository.schedule(self._session, record)


class PreviewRetry:
    def __init__(self, session, repository, owner, receipt):
        self._session, self._repository, self._owner = session, repository, owner
        self.receipt = receipt

    async def record(self, job, key):
        now = await self._session.scalar(select(func.clock_timestamp()))
        self._session.add(
            ProcessingReceipt(
                user_id=self._owner,
                operation="axis_preview_retry",
                key=key,
                request_hash=str(job.id),
                resource_kind="axis_preview",
                resource_id=job.id,
                config={},
                manifest={},
                processing_id=job.id,
                lease_token=uuid4(),
                lease_expires_at=now,
                accepted_at=now,
                expires_at=job.expires_at,
            )
        )
        if job.status == "failed":
            current = await self._session.get(ProcessingRecord, job.id, with_for_update=True)
            current.status = "queued"
            current.error_code, current.retryable = None, False
            current.generation += 1
            current.version += 1
            current.stage_attempts = 0
            current.available_at = await self._session.scalar(select(func.clock_timestamp()))
            self._repository.schedule(self._session, current)
