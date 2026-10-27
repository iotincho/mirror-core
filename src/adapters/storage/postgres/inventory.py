"""Administrative metadata checkpoints and connection-scoped inventory exclusion."""

from contextlib import asynccontextmanager
from dataclasses import asdict

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from src.adapters.storage.postgres.accounts import User
from src.adapters.storage.postgres.administration_models import DocumentMetric, InventoryState
from src.adapters.storage.postgres.boundaries import database_call
from src.adapters.storage.postgres.models import ProcessingReceipt, ProcessingRecord
from src.adapters.storage.postgres.state import database_errors
from src.core.administration.inventory import ReceiptMetadata

LOCK_ID = 814021069


class PostgresInventory:
    def __init__(self, sessions):
        self.sessions = sessions

    @database_call
    async def invalidate(self, user_id):
        async with self.sessions.begin() as session:
            statement = insert(InventoryState).values(user_id=user_id, complete=False)
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[InventoryState.user_id], set_={"complete": False}
                )
            )

    @database_call
    async def facts(self, user_id):
        async with self.sessions() as session:
            receipts = (
                await session.execute(
                    select(
                        ProcessingReceipt.resource_id,
                        ProcessingReceipt.operation,
                        ProcessingReceipt.accepted_at,
                        ProcessingRecord.resource_deleted,
                    )
                    .outerjoin(
                        ProcessingRecord, ProcessingRecord.id == ProcessingReceipt.processing_id
                    )
                    .where(
                        ProcessingReceipt.user_id == user_id,
                        ProcessingReceipt.accepted_at.is_not(None),
                        ProcessingReceipt.is_original.is_(True),
                        ProcessingReceipt.operation.in_(
                            ["upload_document", "upload_audio", "import_document"]
                        ),
                    )
                    .order_by(ProcessingReceipt.accepted_at)
                )
            ).all()
            previous = set(
                (
                    await session.scalars(
                        select(DocumentMetric.document_id).where(DocumentMetric.user_id == user_id)
                    )
                ).all()
            )
        return [ReceiptMetadata(*row) for row in receipts], previous

    @database_call
    async def replace(self, user_id, entries, stamp):
        async with self.sessions.begin() as session:
            for entry in entries:
                statement = insert(DocumentMetric).values(
                    user_id=user_id,
                    seen_at=stamp,
                    **asdict(entry),
                )
                if entry.deleted:
                    await session.execute(statement.on_conflict_do_nothing())
                else:
                    await session.execute(
                        statement.on_conflict_do_update(
                            index_elements=[DocumentMetric.user_id, DocumentMetric.document_id],
                            set_={
                                key: getattr(statement.excluded, key)
                                for key in (
                                    "created_at",
                                    "arrived_at",
                                    "kind",
                                    "deleted",
                                    "seen_at",
                                )
                            },
                        )
                    )
            await session.execute(
                update(DocumentMetric)
                .where(
                    DocumentMetric.user_id == user_id,
                    DocumentMetric.seen_at != stamp,
                )
                .values(deleted=True)
            )
            statement = insert(InventoryState).values(
                user_id=user_id, complete=True, synced_at=stamp
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[InventoryState.user_id],
                    set_={"complete": True, "synced_at": stamp},
                )
            )

    @database_call
    async def owners(self):
        async with self.sessions() as session:
            return list((await session.scalars(select(User.id).order_by(User.id))).all())

    @asynccontextmanager
    async def guard(self):
        async with database_errors(), self.sessions() as session:
            locked = await session.scalar(select(func.pg_try_advisory_lock(LOCK_ID)))
            try:
                yield bool(locked)
            finally:
                if locked:
                    await session.execute(select(func.pg_advisory_unlock(LOCK_ID)))
