"""Taskiq messages carry identifiers; the use case loads authoritative state."""

import asyncio
import logging
from uuid import UUID

from taskiq import Context, TaskiqDepends, TaskiqEvents

from src.processing.broker import broker
from src.processing.execution import ResourceBusy
from src.processing.runtime import get_executor

logger = logging.getLogger(__name__)


@broker.task(task_name="processing.execute")
async def execute_processing(
    processing_id: str, generation: int, context: Context = TaskiqDepends()
):
    try:
        identifier = UUID(processing_id)
        if type(generation) is not int or generation < 1:
            raise ValueError("invalid_generation")
    except (ValueError, TypeError, AttributeError):
        logger.warning("Discarding malformed processing delivery")
        await context.ack()
        return
    while True:
        try:
            await get_executor()(identifier, generation)
            await context.ack()  # Only after PostgreSQL resolves the execution.
            return
        except ResourceBusy:
            await asyncio.sleep(2)
        except Exception:
            # Keep delivery unacknowledged while DB/recovery resolves the lease.
            # Also avoids exhausting Rabbit prefetch with abandoned messages.
            await asyncio.sleep(5)


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def shutdown_worker(state):
    from src.dependencies import close_provider_clients
    from src.user_management.database import close_database

    await close_provider_clients()
    await close_database()
