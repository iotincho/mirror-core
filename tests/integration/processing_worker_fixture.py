"""Synthetic workflow loaded only by opt-in worker integration tests."""

import asyncio
import os

from src.processing.execution import WorkflowDefinition
from src.processing.runtime import registry


async def run(context):
    if context.record.stage == "extract":
        await context.advance("embed", artifact="persisted", worker_pid=os.getpid())
    delay = context.record.config.get("delay", 0.1) if context.record.attempts == 1 else 0.1
    await asyncio.sleep(delay)


registry.register("test", 1, WorkflowDefinition(run, frozenset({("extract", "embed")})))
