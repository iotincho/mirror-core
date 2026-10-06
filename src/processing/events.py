"""Replay committed events without keeping a DB connection open during SSE waits.

Event IDs are allocated before commit and can commit in reverse order. A separate,
serialized publication transaction assigns delivery IDs only to committed events.
No processing rows are locked by publication, avoiding worker/parent lock cycles.
"""

from datetime import timedelta

import anyio
from sqlalchemy import func, select

from src.processing.models import ProcessingDelivery, ProcessingEvent

RETENTION = timedelta(days=7)
PUBLICATION_LOCK = 734851902


class EventFeed:
    def __init__(self, sessions):
        self.sessions = sessions

    async def publish(self):
        with anyio.CancelScope(shield=True):
            async with self.sessions.begin() as session:
                if not await session.scalar(
                    select(func.pg_try_advisory_xact_lock(PUBLICATION_LOCK))
                ):
                    return
                ids = await session.scalars(
                    select(ProcessingEvent.id)
                    .where(
                        ProcessingEvent.payload.is_not(None),
                        ProcessingEvent.created_at >= func.clock_timestamp() - RETENTION,
                        ~select(ProcessingDelivery.id)
                        .where(ProcessingDelivery.event_id == ProcessingEvent.id)
                        .exists(),
                    )
                    .order_by(ProcessingEvent.id)
                    .limit(500)
                )
                session.add_all(ProcessingDelivery(event_id=id_) for id_ in ids)

    async def bounds(self):
        with anyio.CancelScope(shield=True):
            async with self.sessions() as session:
                high = await session.scalar(select(func.max(ProcessingDelivery.id))) or 0
                low = await session.scalar(
                    select(func.min(ProcessingDelivery.id))
                    .join(ProcessingEvent)
                    .where(ProcessingEvent.created_at >= func.clock_timestamp() - RETENTION)
                )
                return low, high

    async def cursor_retained(self, cursor):
        with anyio.CancelScope(shield=True):
            async with self.sessions() as session:
                return (
                    await session.scalar(
                        select(ProcessingDelivery.id)
                        .join(ProcessingEvent)
                        .where(
                            ProcessingDelivery.id == cursor,
                            ProcessingEvent.created_at >= func.clock_timestamp() - RETENTION,
                        )
                    )
                    is not None
                )

    async def read(self, owner, after, limit=100):
        with anyio.CancelScope(shield=True):
            async with self.sessions() as session:
                return (
                    await session.execute(
                        select(ProcessingDelivery.id, ProcessingEvent.payload)
                        .join(ProcessingEvent)
                        .where(
                            ProcessingDelivery.id > after,
                            ProcessingEvent.user_id == owner,
                            ProcessingEvent.created_at >= func.clock_timestamp() - RETENTION,
                        )
                        .order_by(ProcessingDelivery.id)
                        .limit(limit)
                    )
                ).all()
