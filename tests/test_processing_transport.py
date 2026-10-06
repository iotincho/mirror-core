"""ACK is an execution boundary, independent of business workflow stages."""

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.processing import tasks


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_transport_acknowledges_only_after_durable_execution(monkeypatch):
    persisted = False
    context = AsyncMock()

    async def execute(processing_id, generation):
        nonlocal persisted
        assert generation == 7
        persisted = True

    async def ack():
        assert persisted

    context.ack.side_effect = ack
    monkeypatch.setattr(tasks, "get_executor", lambda: execute)
    await tasks.execute_processing(str(uuid4()), 7, context=context)
    context.ack.assert_awaited_once()


@pytest.mark.anyio
async def test_database_interruption_keeps_delivery_unacked_until_recovery(monkeypatch):
    context = AsyncMock()
    execute = AsyncMock(side_effect=[ConnectionError("database unavailable"), None])

    async def retry_pause(seconds):
        context.ack.assert_not_awaited()

    monkeypatch.setattr(tasks, "get_executor", lambda: execute)
    monkeypatch.setattr(tasks.asyncio, "sleep", retry_pause)
    await tasks.execute_processing(str(uuid4()), 1, context=context)
    assert execute.await_count == 2
    context.ack.assert_awaited_once()


@pytest.mark.anyio
async def test_worker_cancellation_leaves_delivery_unacked(monkeypatch):
    context = AsyncMock()
    execute = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(tasks, "get_executor", lambda: execute)
    with pytest.raises(asyncio.CancelledError):
        await tasks.execute_processing(str(uuid4()), 1, context=context)
    context.ack.assert_not_awaited()


@pytest.mark.anyio
async def test_malformed_delivery_does_not_block_worker_capacity(monkeypatch):
    context = AsyncMock()
    execute = AsyncMock()
    monkeypatch.setattr(tasks, "get_executor", lambda: execute)
    await tasks.execute_processing("invalid-uuid", 1, context=context)
    execute.assert_not_awaited()
    context.ack.assert_awaited_once()
