"""One SQL transaction tracks detached state, receipts, events and outbox together."""

from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import asdict, fields
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from src.adapters.storage.postgres.models import ProcessingReceipt, ProcessingRecord
from src.adapters.storage.postgres.state import database_errors, receipt_snapshot, snapshot
from src.core.processing.models import ProcessingJob, SubmissionReceipt


class PostgresTransaction:
    def __init__(self, session, repository, now, config_factory):
        self._session, self._repository = session, repository
        self.now, self._config_factory = now, config_factory
        self._jobs, self._receipts = {}, {}

    def _track(self, row, *, receipt=False):
        if row is None:
            return None
        cache = self._receipts if receipt else self._jobs
        if row.id not in cache:
            cache[row.id] = (row, receipt_snapshot(row) if receipt else snapshot(row))
        return cache[row.id][1]

    def synchronize(self, identifier=None):
        tracked = (
            [self._jobs[identifier]]
            if identifier is not None
            else [*self._jobs.values(), *self._receipts.values()]
        )
        for row, state in tracked:
            for field in fields(state):
                setattr(row, field.name, deepcopy(getattr(state, field.name)))

    def refresh(self, identifier=None):
        tracked = (
            [self._jobs[identifier]]
            if identifier is not None
            else [*self._jobs.values(), *self._receipts.values()]
        )
        for row, state in tracked:
            for field in fields(state):
                setattr(state, field.name, deepcopy(getattr(row, field.name)))

    async def receipt(self, owner, operation, key):
        return self._track(
            await self._session.scalar(
                select(ProcessingReceipt).where(
                    ProcessingReceipt.user_id == owner,
                    ProcessingReceipt.operation == operation,
                    ProcessingReceipt.key == key,
                )
            ),
            receipt=True,
        )

    async def reserve_mutation(self, owner, operation, key, request_hash, resource_id):
        await self._session.execute(
            insert(ProcessingReceipt)
            .values(
                id=uuid4(),
                user_id=owner,
                operation=operation,
                key=key,
                request_hash=request_hash,
                resource_kind="document",
                resource_id=resource_id,
                config={},
                manifest={},
                lease_token=uuid4(),
                lease_expires_at=self.now + timedelta(seconds=90),
                created_at=self.now,
            )
            .on_conflict_do_nothing()
        )
        row = await self._session.scalar(
            select(ProcessingReceipt)
            .where(
                ProcessingReceipt.user_id == owner,
                ProcessingReceipt.operation == operation,
                ProcessingReceipt.key == key,
            )
            .with_for_update()
        )
        return self._track(row, receipt=True)

    async def job(self, identifier, *, locked=True):
        return self._track(
            await self._session.get(
                ProcessingRecord,
                identifier,
                with_for_update=locked,
            )
        )

    async def children(self, parent_id, owner):
        rows = await self._session.scalars(
            select(ProcessingRecord)
            .where(
                ProcessingRecord.parent_processing_id == parent_id,
                ProcessingRecord.user_id == owner,
                ProcessingRecord.workflow == "extractor",
            )
            .with_for_update()
        )
        return [self._track(row) for row in rows]

    async def create_jobs(self, jobs: list[ProcessingJob]):
        self.synchronize()
        rows = [ProcessingRecord(**asdict(job)) for job in jobs]
        self._session.add_all(rows)
        await self._session.flush()
        for row, job in zip(rows, jobs, strict=True):
            self._jobs[row.id] = (row, job)
        self.refresh()

    def event(self, job):
        self.synchronize(job.id)
        self._repository.event(self._session, self._jobs[job.id][0])

    def schedule(self, job):
        self.synchronize(job.id)
        self._repository.schedule(self._session, self._jobs[job.id][0])

    async def wake_parent(self, child):
        self.synchronize(child.id)
        parent = child.parent_processing_id
        if parent in self._jobs:
            self.synchronize(parent)
        await self._repository.wake_parent(self._session, self._jobs[child.id][0], self.now)
        if parent in self._jobs:
            self.refresh(parent)

    async def configuration_for(self, owner, baseline):
        return await self._config_factory(self._session, owner, baseline)

    async def deleted(self, owner, identifier):
        return (
            await self._session.scalar(
                select(ProcessingRecord.id)
                .where(
                    ProcessingRecord.user_id == owner,
                    ProcessingRecord.resource_id == identifier,
                    ProcessingRecord.resource_deleted.is_(True),
                )
                .limit(1)
            )
            is not None
        )

    async def jobs_for_resources(self, owner, identifiers):
        rows = await self._session.scalars(
            select(ProcessingRecord)
            .where(
                ProcessingRecord.user_id == owner,
                ProcessingRecord.resource_id.in_(identifiers),
            )
            .order_by(ProcessingRecord.created_at.desc())
        )
        return [self._track(row) for row in rows]

    async def receipts_for_resources(self, owner, identifiers) -> list[SubmissionReceipt]:
        rows = await self._session.scalars(
            select(ProcessingReceipt).where(
                ProcessingReceipt.user_id == owner,
                ProcessingReceipt.resource_id.in_(identifiers),
            )
        )
        return [self._track(row, receipt=True) for row in rows]


class PostgresProcessingRequests:
    def __init__(self, repository, *, config_factory):
        self._repository, self._config_factory = repository, config_factory

    @asynccontextmanager
    async def transaction(self):
        async with database_errors(), self._repository.sessions.begin() as session:
            now = await session.scalar(select(func.clock_timestamp()))
            unit = PostgresTransaction(session, self._repository, now, self._config_factory)
            yield unit
            unit.synchronize()

    @asynccontextmanager
    async def lock_resource(self, owner, resource_id):
        async with (
            database_errors(),
            self._repository.lock_resource(owner, resource_id) as acquired,
        ):
            yield acquired

    @asynccontextmanager
    async def lock_resources(self, owner, resource_ids):
        async with (
            database_errors(),
            self._repository.lock_resources(owner, resource_ids) as acquired,
        ):
            yield acquired

    @asynccontextmanager
    async def lock_extractor(self, owner, resource_id, branch_id):
        async with (
            database_errors(),
            self._repository.lock_extractor(owner, resource_id, branch_id) as acquired,
        ):
            yield acquired

    async def assert_inactive(self, owner, resource_id, exclude=()):
        async with database_errors():
            await self._repository.assert_inactive(owner, resource_id, exclude)

    async def get(self, identifier, owner):
        async with database_errors():
            return snapshot(await self._repository.get(identifier, owner))

    async def latest(self, owner, resource_id, kind):
        async with database_errors():
            return snapshot(await self._repository.latest(owner, resource_id, kind))

    async def mark_deleted(self, owner, resource_id):
        async with database_errors():
            await self._repository.mark_deleted(owner, resource_id)
