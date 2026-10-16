import logging
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from src.api.routes.events import stream


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error,expected,frame",
    [
        (HTTPException(401, "private session"), "event_feed_closed", "session.expired"),
        (HTTPException(503, "private workspace"), "event_feed_closed", "processing.unavailable"),
        (SQLAlchemyError("private SQL payload"), "event_feed_storage_error", None),
    ],
)
async def test_stream_failures_after_response_start_are_logged(caplog, error, expected, frame):
    class Feed:
        async def publish(self):
            raise error

    request = SimpleNamespace(state=SimpleNamespace(request_id="test-request"))
    with caplog.at_level(logging.WARNING):
        frames = [item async for item in stream(request, Feed(), "owner-id", None, 389, None)]
    assert expected in caplog.text
    assert "owner_id=owner-id" in caplog.text
    assert "request_id=test-request" in caplog.text
    assert "private" not in caplog.text
    assert (frame in "".join(frames)) if frame else frames == []


@pytest.mark.anyio
async def test_unexpected_stream_failure_logs_and_propagates(caplog):
    class Feed:
        async def publish(self):
            raise RuntimeError("private provider payload")

    request = SimpleNamespace(state=SimpleNamespace(request_id="test-request"))
    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError):
        await anext(stream(request, Feed(), "owner-id", None, 389, None))
    assert "event_feed_unexpected_error" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "private provider payload" not in caplog.text
