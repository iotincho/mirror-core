"""Taskiq messages carry identifiers; the use case loads authoritative state."""

import asyncio
import logging
from uuid import UUID

from taskiq import Context, TaskiqDepends, TaskiqEvents

from src.core.processing.errors import ResourceBusy

logger = logging.getLogger(__name__)


def register_tasks(
    broker, get_executor, *, initialize_sentry, report_issue, trace_operation, close_resources
):
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
                with trace_operation("processing.execute", processing_id=identifier):
                    await get_executor()(identifier, generation)
                await context.ack()  # Only after PostgreSQL resolves the execution.
                return
            except ResourceBusy:
                await asyncio.sleep(2)
            except Exception as error:
                report_issue("processing_delivery_failed", error, processing_id=identifier)
                # Keep delivery unacknowledged while DB/recovery resolves the lease.
                # Also avoids exhausting Rabbit prefetch with abandoned messages.
                await asyncio.sleep(5)

    @broker.on_event(TaskiqEvents.WORKER_STARTUP)
    async def startup_worker(state):
        initialize_sentry("processing-worker")

    @broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
    async def shutdown_worker(state):
        await close_resources()

    return execute_processing, startup_worker, shutdown_worker
