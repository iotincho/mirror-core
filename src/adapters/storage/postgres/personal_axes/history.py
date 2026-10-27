"""History units share the existing processing transaction and return detached facts."""

from contextlib import asynccontextmanager
from dataclasses import asdict, fields
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert

from src.adapters.storage.postgres.models import ProcessingReceipt, ProcessingRecord
from src.adapters.storage.postgres.personal_axes.definitions import definition
from src.adapters.storage.postgres.personal_axes.history_models import (
    AxisHistoryBatch,
    AxisHistoryItem,
)
from src.adapters.storage.postgres.personal_axes.laboratory import PostgresLaboratory
from src.adapters.storage.postgres.personal_axes.models import PersonalAxis, PersonalAxisVersion
from src.adapters.storage.postgres.state import database_errors, snapshot
from src.adapters.storage.postgres.transactions import PostgresTransaction
from src.core.extractors.personal_axes.history import (
    ACTIVE,
    HistoryBatch,
    HistoryItem,
    HistoryStart,
    HistoryView,
)
from src.core.extractors.personal_axes.models import AxisError


def detached(row, model):
    return model(**{field.name: getattr(row, field.name) for field in fields(model)})


class PostgresHistory:
    def __init__(self, repository, *, enabled):
        self._repository, self._enabled = repository, enabled

    async def previous(self, owner, key):
        async with database_errors(), self._repository.sessions() as session:
            row = await session.scalar(
                select(AxisHistoryBatch).where(
                    AxisHistoryBatch.user_id == owner, AxisHistoryBatch.request_key == key
                )
            )
            return detached(row, HistoryBatch) if row else None

    async def active(self, owner, axis_id):
        async with database_errors(), self._repository.sessions() as session:
            return await HistoryUnit(session, self._repository, None, owner).active_documents(
                axis_id
            )

    async def view(self, owner, axis_id, batch_id):
        async with database_errors(), self._repository.sessions() as session:
            unit = HistoryUnit(session, self._repository, None, owner)
            batch = await unit.batch(axis_id, batch_id, lock=False)
            version = await session.get(PersonalAxisVersion, batch.version_id)
            pairs = (
                await session.execute(
                    select(AxisHistoryItem, ProcessingRecord)
                    .outerjoin(
                        ProcessingRecord, AxisHistoryItem.processing_id == ProcessingRecord.id
                    )
                    .where(AxisHistoryItem.batch_id == batch.id)
                    .order_by(AxisHistoryItem.document_id)
                )
            ).all()
            return HistoryView(
                batch,
                version.number,
                [(detached(item, HistoryItem), snapshot(job)) for item, job in pairs],
            )

    async def batch_ids(self, owner, axis_id, offset, limit):
        async with database_errors(), self._repository.sessions() as session:
            return list(
                (
                    await session.scalars(
                        select(AxisHistoryBatch.id)
                        .where(
                            AxisHistoryBatch.axis_id == axis_id, AxisHistoryBatch.user_id == owner
                        )
                        .order_by(AxisHistoryBatch.created_at.desc(), AxisHistoryBatch.id.desc())
                        .offset(offset)
                        .limit(limit)
                    )
                ).all()
            )

    @asynccontextmanager
    async def guard(self, owner, axis_id):
        async with database_errors(), self._repository.lock_resource(owner, axis_id) as locked:
            yield locked

    @asynccontextmanager
    async def transaction(self, owner, axis_id, *, planning=False):
        async with database_errors(), self._repository.sessions.begin() as session:
            now = await session.scalar(select(func.clock_timestamp()))
            unit = HistoryUnit(session, self._repository, now, owner)
            if planning:
                axis = await session.scalar(
                    select(PersonalAxis)
                    .where(PersonalAxis.id == axis_id, PersonalAxis.user_id == owner)
                    .with_for_update()
                )
                state = (
                    await PostgresLaboratory(session=session).read(owner) if self._enabled else None
                )
                if axis is None or state is None or not state.active or not state.granted:
                    raise AxisError("axis_not_found")
                version = await session.get(PersonalAxisVersion, axis.current_version_id)
                unit.definition = definition(axis, version)
            yield unit
            unit.synchronize()

    async def begin(self, record):
        async with self.transaction(record.user_id, None) as unit:
            batch = await unit.batch(None, record.config["batch_id"])
            item = await unit.item(batch.id, record.resource_id)
            if item is None or item.processing_id != record.id:
                raise AxisError("axis_history_item_mismatch")
            skip = item.outcome is not None or (
                batch.stopped_at is not None and item.started_at is None
            )
            if not skip and item.started_at is None:
                item.started_at = await unit.timestamp()
            return HistoryStart(skip, item.outcome)

    async def outcome(self, record, value):
        async with database_errors(), self._repository.leased(record) as (session, _, _):
            item = await session.get(
                AxisHistoryItem,
                (UUID(record.config["batch_id"]), record.resource_id),
                with_for_update=True,
            )
            item.outcome = value


class HistoryUnit(PostgresTransaction):
    def __init__(self, session, repository, now, owner):
        super().__init__(session, repository, now, None)
        self.owner, self._batches, self._items = owner, {}, {}
        self.definition = None

    def synchronize(self, identifier=None):
        super().synchronize(identifier)
        for row, state in [*self._batches.values(), *self._items.values()]:
            for field in fields(state):
                setattr(row, field.name, getattr(state, field.name))

    async def timestamp(self):
        self.now = await self._session.scalar(select(func.clock_timestamp()))
        return self.now

    async def batch(self, axis_id, batch_id, *, lock=True):
        query = select(AxisHistoryBatch).where(
            AxisHistoryBatch.id == UUID(str(batch_id)), AxisHistoryBatch.user_id == self.owner
        )
        if axis_id is not None:
            query = query.where(AxisHistoryBatch.axis_id == axis_id)
        row = await self._session.scalar(query.with_for_update() if lock else query)
        if row is None:
            raise AxisError("axis_history_not_found")
        if row.id not in self._batches:
            self._batches[row.id] = row, detached(row, HistoryBatch)
        return self._batches[row.id][1]

    async def item(self, batch_id, document_id):
        key = (batch_id, document_id)
        row = await self._session.get(AxisHistoryItem, key, with_for_update=True)
        if row is None:
            return None
        if key not in self._items:
            self._items[key] = row, detached(row, HistoryItem)
        return self._items[key][1]

    async def active_documents(self, axis_id):
        historical = set(
            (
                await self._session.scalars(
                    select(AxisHistoryItem.document_id)
                    .join(AxisHistoryBatch, AxisHistoryItem.batch_id == AxisHistoryBatch.id)
                    .join(ProcessingRecord, AxisHistoryItem.processing_id == ProcessingRecord.id)
                    .where(
                        AxisHistoryBatch.user_id == self.owner,
                        AxisHistoryBatch.axis_id == axis_id,
                        AxisHistoryItem.outcome.is_(None),
                        ProcessingRecord.status.in_(ACTIVE),
                    )
                )
            ).all()
        )
        regular = set(
            (
                await self._session.scalars(
                    select(ProcessingRecord.resource_id).where(
                        ProcessingRecord.user_id == self.owner,
                        ProcessingRecord.resource_kind == "document",
                        ProcessingRecord.status.in_(ACTIVE),
                        or_(
                            (ProcessingRecord.workflow == "extractor")
                            & (ProcessingRecord.extractor_key == f"axis:{axis_id}"),
                            (ProcessingRecord.workflow == "document")
                            & ProcessingRecord.config["extractors"].contains(
                                [{"axis_id": str(axis_id)}]
                            ),
                        ),
                    )
                )
            ).all()
        )
        return historical | regular

    async def create_batch(self, axis_id, version_id, key, fingerprint):
        now, identifier = await self.timestamp(), uuid4()
        await self._session.execute(
            insert(AxisHistoryBatch)
            .values(
                id=identifier,
                user_id=self.owner,
                axis_id=axis_id,
                version_id=version_id,
                request_key=key,
                request_hash=fingerprint,
                created_at=now,
            )
            .on_conflict_do_nothing()
        )
        row = await self._session.scalar(
            select(AxisHistoryBatch)
            .where(AxisHistoryBatch.user_id == self.owner, AxisHistoryBatch.request_key == key)
            .with_for_update()
        )
        if row.request_hash != fingerprint:
            raise AxisError("axis_history_request_conflict")
        state = detached(row, HistoryBatch)
        self._batches[row.id] = row, state
        return state, row.id == identifier

    async def add_item(self, state):
        row = AxisHistoryItem(**asdict(state))
        self._session.add(row)
        self._items[state.batch_id, state.document_id] = row, state

    async def stop_candidates(self, batch_id):
        rows = (
            await self._session.scalars(
                select(ProcessingRecord)
                .join(AxisHistoryItem, AxisHistoryItem.processing_id == ProcessingRecord.id)
                .where(
                    AxisHistoryItem.batch_id == batch_id,
                    AxisHistoryItem.outcome.is_(None),
                    ProcessingRecord.status.in_(ACTIVE),
                    or_(
                        AxisHistoryItem.started_at.is_(None),
                        ProcessingRecord.status.in_(["queued", "retrying"]),
                    ),
                )
                .with_for_update(of=ProcessingRecord)
            )
        ).all()
        await self.timestamp()
        return [(await self.item(batch_id, row.resource_id), self._track(row)) for row in rows]

    async def retry_receipt(self, batch_id, key, fingerprint):
        await self._session.execute(
            insert(ProcessingReceipt)
            .values(
                id=uuid4(),
                user_id=self.owner,
                operation="axis_history_retry",
                key=key,
                request_hash=fingerprint,
                resource_kind="axis_history",
                resource_id=batch_id,
                config={},
                manifest={},
                lease_token=uuid4(),
                lease_expires_at=func.now(),
            )
            .on_conflict_do_nothing()
        )
        row = await self._session.scalar(
            select(ProcessingReceipt)
            .where(
                ProcessingReceipt.user_id == self.owner,
                ProcessingReceipt.operation == "axis_history_retry",
                ProcessingReceipt.key == key,
            )
            .with_for_update()
        )
        return self._track(row, receipt=True)

    async def retry_candidates(self, batch_id):
        rows = (
            await self._session.scalars(
                select(ProcessingRecord)
                .join(AxisHistoryItem, AxisHistoryItem.processing_id == ProcessingRecord.id)
                .where(
                    AxisHistoryItem.batch_id == batch_id,
                    AxisHistoryItem.outcome.is_(None),
                    ProcessingRecord.status == "failed",
                    ProcessingRecord.retryable.is_(True),
                    ProcessingRecord.resource_deleted.is_(False),
                )
                .with_for_update(of=ProcessingRecord)
            )
        ).all()
        await self.timestamp()
        return [(await self.item(batch_id, row.resource_id), self._track(row)) for row in rows]
