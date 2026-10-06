"""Commit ordering, replay and real HTTP SSE against isolated PostgreSQL."""

import asyncio
import os
import socket
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from sqlalchemy import delete, func, update

from src.api.routes import events
from src.api.schemas.processing import ProcessingResponse
from src.config import get_settings
from src.processing.events import EventFeed
from src.processing.models import ProcessingEvent
from src.user_management.models import AccessToken
from src.workspaces.models import UserWorkspace
from tests.integration.test_processing_postgres import anyio_backend, job, store  # noqa: F401

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("PROCESSING_TEST_DATABASE_URL"), reason="requires isolated PostgreSQL"
    ),
]


async def test_historical_payload_replay_and_owner_filter(store):  # noqa: F811
    repo, owner = store
    record = await job(store)
    original = ProcessingResponse.from_record(record).model_dump(mode="json")
    acquired = await repo.acquire(record.id, 1, "worker")
    await repo.finish(acquired, status="completed")
    feed = EventFeed(repo.sessions)
    await feed.publish()
    rows = await feed.read(owner, 0)
    assert [payload["status"] for _, payload in rows] == ["queued", "running", "completed"]
    assert rows[0][1] == original
    assert [payload["version"] for _, payload in rows] == [1, 2, 3]
    assert len(await feed.read(owner, rows[1][0])) == 1
    assert await feed.read(uuid4(), 0) == []
    assert "config" not in rows[0][1] and "lease_owner" not in rows[0][1]
    await asyncio.gather(feed.publish(), feed.publish(), feed.publish())
    assert len(await feed.read(owner, 0)) == 3


async def test_late_commit_gets_a_later_delivery_cursor(store):  # noqa: F811
    repo, owner = store
    first = await job(store)
    second = await job(store)
    feed = EventFeed(repo.sessions)
    await feed.publish()
    _, initial = await feed.bounds()
    async with repo.sessions() as slow:
        async with slow.begin():
            row = await slow.get(type(first), first.id)
            row.version += 1
            row.status = "running"
            repo.event(slow, row)
            await slow.flush()  # Lower event ID allocated but not committed yet.
            await repo.acquire(second.id, 1, "fast")
            await feed.publish()
            fast = await feed.read(owner, initial)
            assert len(fast) == 1 and fast[0][1]["id"] == str(second.id)
        await feed.publish()
        late = await feed.read(owner, fast[0][0])
        assert len(late) == 1 and late[0][1]["id"] == str(first.id)


@pytest.fixture
async def sse_server(store, monkeypatch):  # noqa: F811
    repo, owner = store
    token = uuid4().hex
    async with repo.sessions.begin() as session:
        await session.execute(
            update(UserWorkspace)
            .where(UserWorkspace.user_id == owner)
            .values(arcadedb_instance_key=get_settings().arcadedb_instance_key)
        )
        session.add(AccessToken(token=token, user_id=owner))
    monkeypatch.setattr(events, "get_session_maker", lambda: repo.sessions)
    monkeypatch.setattr(events, "POLL_SECONDS", 0.02)
    monkeypatch.setattr(events, "HEARTBEAT_SECONDS", 0.05)
    app = FastAPI()
    app.include_router(events.router)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    for _ in range(100):
        if server.started:
            break
        await asyncio.sleep(0.01)
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=3) as client:
            yield client, token
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=5)
        async with repo.sessions.begin() as session:
            await session.execute(delete(AccessToken).where(AccessToken.token == token))


async def next_frame(lines):
    result = []
    async for line in lines:
        if not line:
            if result:
                return "\n".join(result)
        else:
            result.append(line)
    return ""


async def test_sse_auth_initial_resync_replay_and_revocation(store, sse_server):  # noqa: F811
    repo, owner = store
    client, token = sse_server
    assert (await client.get("/events")).status_code == 401
    client.cookies.set(events.COOKIE_NAME, token)
    assert (await client.get("/events?after=-1")).status_code == 422
    record = await job(store)
    async with client.stream("GET", "/events") as response:
        assert response.status_code == 200
        assert response.headers["x-accel-buffering"] == "no"
        lines = response.aiter_lines()
        initial = await next_frame(lines)
        assert "processing.resync" in initial
        initial_cursor = int(initial.splitlines()[0].split(": ")[1])
        await repo.acquire(record.id, 1, "worker")
        assert await next_frame(lines) == "retry: 3000"
        while "processing.updated" not in (frame := await next_frame(lines)):
            pass
        assert '"status":"running"' in frame
        async with repo.sessions.begin() as session:
            await session.execute(delete(AccessToken).where(AccessToken.token == token))
        while "session.expired" not in (frame := await next_frame(lines)):
            assert frame
    assert (await client.get("/events")).status_code == 401
    async with repo.sessions.begin() as session:
        session.add(AccessToken(token=token, user_id=owner))
    async with client.stream(
        "GET", "/events", headers={"Last-Event-ID": str(initial_cursor)}
    ) as response:
        lines = response.aiter_lines()
        assert await next_frame(lines) == "retry: 3000"
        frame = await next_frame(lines)
        assert "processing.updated" in frame and '"status":"running"' in frame


async def test_expired_cursor_resync_and_old_cookie_rejected(store, sse_server):  # noqa: F811
    repo, owner = store
    client, token = sse_server
    await job(store)
    feed = EventFeed(repo.sessions)
    await feed.publish()
    async with repo.sessions.begin() as session:
        await session.execute(
            update(ProcessingEvent)
            .where(ProcessingEvent.user_id == owner)
            .values(created_at=func.clock_timestamp() - timedelta(days=8))
        )
    client.cookies.set(events.COOKIE_NAME, token)
    async with client.stream("GET", "/events?after=0") as response:
        assert "processing.resync" in await next_frame(response.aiter_lines())
    async with repo.sessions.begin() as session:
        await session.execute(
            update(AccessToken)
            .where(AccessToken.token == token)
            .values(
                created_at=func.clock_timestamp()
                - timedelta(seconds=get_settings().auth_session_ttl_seconds + 1)
            )
        )
    assert (await client.get("/events")).status_code == 401


async def test_workspace_unavailable_ends_stream_without_expiring_valid_session(store, sse_server):  # noqa: F811
    repo, owner = store
    client, token = sse_server
    client.cookies.set(events.COOKIE_NAME, token)
    async with client.stream("GET", "/events") as response:
        lines = response.aiter_lines()
        assert "processing.resync" in await next_frame(lines)
        async with repo.sessions.begin() as session:
            await session.execute(
                update(UserWorkspace).where(UserWorkspace.user_id == owner).values(status="failed")
            )
        while "processing.unavailable" not in (frame := await next_frame(lines)):
            assert "session.expired" not in frame and frame
    assert (await client.get("/events")).status_code == 503
