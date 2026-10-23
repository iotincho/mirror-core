"""Register inbound tasks, observability and process resource ownership."""

import asyncio as asyncio

from src.adapters.access.workers.processing import register_tasks
from src.bootstrap.messaging import broker
from src.bootstrap.processing import get_executor
from src.observability import initialize_sentry, report_issue, trace_operation


async def close_resources():
    from src.bootstrap.database import close_database
    from src.bootstrap.workflows import close_workflow_providers

    await close_workflow_providers()
    await close_database()


execute_processing, startup_worker, shutdown_worker = register_tasks(
    broker,
    lambda: get_executor(),
    initialize_sentry=initialize_sentry,
    report_issue=report_issue,
    trace_operation=trace_operation,
    close_resources=close_resources,
)
