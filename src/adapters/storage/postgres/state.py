"""Translate durable PostgreSQL state and failures at the application boundary."""

from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import fields

from sqlalchemy.exc import SQLAlchemyError

from src.core.processing.errors import StorageUnavailable
from src.core.processing.models import OutboxDelivery, ProcessingJob, SubmissionReceipt


def snapshot(value, model=ProcessingJob):
    if value is None:
        return None
    return model(**{field.name: deepcopy(getattr(value, field.name)) for field in fields(model)})


@asynccontextmanager
async def database_errors():
    try:
        yield
    except SQLAlchemyError as error:
        raise StorageUnavailable("processing_storage_unavailable") from error


class PostgresExecutionStore:
    def __init__(self, repository):
        self._repository = repository
        self.lease_seconds = repository.lease_seconds

    @asynccontextmanager
    async def resource_guard(self, processing_id):
        async with database_errors(), self._repository.resource_guard(processing_id) as acquired:
            yield acquired

    async def acquire(self, processing_id, generation, owner):
        async with database_errors():
            return snapshot(await self._repository.acquire(processing_id, generation, owner))

    async def assert_lease(self, record):
        async with database_errors(), self._repository.leased(record):
            pass

    async def heartbeat(self, record):
        async with database_errors():
            await self._repository.heartbeat(record)

    async def advance(self, record, stage, checkpoints):
        async with database_errors():
            await self._repository.advance(record, stage, checkpoints)

    async def finish(self, record, **outcome):
        async with database_errors():
            await self._repository.finish(record, **outcome)

    async def workspace_active(self, user_id):
        async with database_errors():
            return await self._repository.workspace_active(user_id)

    async def extractor_children(self, parent_id, user_id):
        async with database_errors():
            return [
                snapshot(row)
                for row in await self._repository.extractor_children(parent_id, user_id)
            ]

    async def extractors_and_wait(self, record, specifications):
        async with database_errors():
            await self._repository.extractors_and_wait(record, specifications)

    async def child(self, record):
        async with database_errors():
            return snapshot(await self._repository.child(record))

    async def child_and_wait(
        self, record, document_id, *, invitation_id=None, invitation_question_id=None
    ):
        async with database_errors():
            await self._repository.child_and_wait(
                record,
                document_id,
                invitation_id=invitation_id,
                invitation_question_id=invitation_question_id,
            )

    async def claim_outbox(self, limit=20):
        async with database_errors():
            return [
                snapshot(row, OutboxDelivery) for row in await self._repository.claim_outbox(limit)
            ]

    async def settle_outbox(self, row, *, published):
        async with database_errors():
            await self._repository.settle_outbox(row, published=published)


def receipt_snapshot(receipt):
    return snapshot(receipt, SubmissionReceipt)
