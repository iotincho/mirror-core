"""Cookie-authenticated event stream, with short lived authentication queries."""

import asyncio
import json
import logging
from datetime import timedelta

import anyio
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from src.config import get_settings
from src.processing.events import EventFeed
from src.user_management.authentication import COOKIE_NAME
from src.user_management.database import get_session_maker
from src.user_management.models import AccessToken, User
from src.workspaces.models import UserWorkspace

router = APIRouter(tags=["processing"])
logger = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 15
POLL_SECONDS = 1


async def stream_owner(token, sessions):
    # Match the DB cookie strategy: token lifetime, active user and active workspace.
    # The session closes before yielding; SSE never occupies a pooled DB connection.
    if not token:
        raise HTTPException(401, "Unauthorized")
    settings = get_settings()
    with anyio.CancelScope(shield=True):
        async with sessions() as session:
            row = (
                await session.execute(
                    select(User.id, UserWorkspace.status, UserWorkspace.arcadedb_instance_key)
                    .join(AccessToken, AccessToken.user_id == User.id)
                    .outerjoin(UserWorkspace, UserWorkspace.user_id == User.id)
                    .where(
                        AccessToken.token == token,
                        User.is_active.is_(True),
                        AccessToken.created_at
                        >= func.clock_timestamp()
                        - timedelta(seconds=settings.auth_session_ttl_seconds),
                    )
                )
            ).first()
    if row is None:
        raise HTTPException(401, "Unauthorized")
    if row.status != "active" or row.arcadedb_instance_key != settings.arcadedb_instance_key:
        raise HTTPException(503, "Personal workspace is unavailable")
    return row.id


def frame(event, data, cursor=None):
    prefix = f"id: {cursor}\n" if cursor is not None else ""
    return f"{prefix}event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


async def stream(request, feed, owner, token, cursor, sessions):
    try:
        await feed.publish()
        low, high = await feed.bounds()
        if (
            cursor is None
            or cursor > high
            or (low is not None and cursor < low - 1)
            or (low is None and cursor < high)
            or (cursor > 0 and not await feed.cursor_retained(cursor))
        ):
            cursor = high
            yield frame("processing.resync", {"reason": "snapshot_required"}, high)
        yield "retry: 3000\n\n"
        heartbeat_at = asyncio.get_running_loop().time() + HEARTBEAT_SECONDS
        while not await request.is_disconnected():
            # Recheck revocation and workspace status on every heartbeat, including idle streams.
            now = asyncio.get_running_loop().time()
            if now >= heartbeat_at:
                if await stream_owner(token, sessions) != owner:
                    return
                yield ": heartbeat\n\n"
                heartbeat_at = now + HEARTBEAT_SECONDS
            await feed.publish()
            rows = await feed.read(owner, cursor)
            for delivery_id, payload in rows:
                yield frame("processing.updated", payload, delivery_id)
                cursor = delivery_id
            if len(rows) < 100:
                await asyncio.sleep(POLL_SECONDS)
    except HTTPException as error:
        yield frame("session.expired" if error.status_code == 401 else "processing.unavailable", {})
    except SQLAlchemyError:
        logger.warning("Event feed interrupted by database unavailability")


@router.get("/events")
async def events(request: Request, after: int | None = None):
    sessions = get_session_maker()
    token = request.cookies.get(COOKIE_NAME)
    try:
        owner = await stream_owner(token, sessions)
        header = request.headers.get("last-event-id")
        cursor = int(header) if header is not None else after
        if cursor is not None and cursor < 0:
            raise ValueError
    except ValueError as error:
        raise HTTPException(422, "Invalid event cursor") from error
    except SQLAlchemyError as error:
        raise HTTPException(503, "Event storage unavailable") from error
    return StreamingResponse(
        stream(request, EventFeed(sessions), owner, token, cursor, sessions),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
