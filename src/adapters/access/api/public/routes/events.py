"""Cookie-authenticated event stream, with short lived authentication queries."""

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.adapters.access.api.public.auth.cookies import COOKIE_NAME
from src.adapters.access.api.public.diagnostics import report_issue
from src.core.auth.session import SessionExpired
from src.core.processing.errors import StorageUnavailable
from src.core.workspaces.models import WorkspaceUnavailable

logger = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 15
POLL_SECONDS = 1


async def stream_owner(token, authorization):
    try:
        return await authorization.execute(token)
    except SessionExpired as error:
        raise HTTPException(401, "Unauthorized") from error
    except WorkspaceUnavailable as error:
        raise HTTPException(503, error.detail) from error


def frame(event, data, cursor=None):
    prefix = f"id: {cursor}\n" if cursor is not None else ""
    return f"{prefix}event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


async def stream(request, feed, owner, token, cursor, authorization):
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
                if await stream_owner(token, authorization) != owner:
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
        if error.status_code >= 500:
            report_issue(
                request,
                "event_feed_unavailable",
                error,
                request_id=getattr(request.state, "request_id", None),
            )
        logger.warning(
            "event_feed_closed owner_id=%s status_code=%s request_id=%s",
            owner,
            error.status_code,
            getattr(request.state, "request_id", "unavailable"),
        )
        yield frame("session.expired" if error.status_code == 401 else "processing.unavailable", {})
    except StorageUnavailable as error:
        report_issue(
            request,
            "event_feed_storage_error",
            error,
            request_id=getattr(request.state, "request_id", None),
        )
        logger.warning(
            "event_feed_storage_error owner_id=%s error_type=%s request_id=%s",
            owner,
            type(error).__name__,
            getattr(request.state, "request_id", "unavailable"),
        )
    except Exception as error:
        report_issue(
            request,
            "event_feed_unexpected_error",
            error,
            request_id=getattr(request.state, "request_id", None),
        )
        logger.error(
            "event_feed_unexpected_error owner_id=%s error_type=%s request_id=%s",
            owner,
            type(error).__name__,
            getattr(request.state, "request_id", "unavailable"),
        )
        raise


def build_router(get_authorization, get_feed):
    router = APIRouter(tags=["processing"])

    @router.get("/events")
    async def events(
        request: Request,
        after: int | None = None,
        authorization=Depends(get_authorization),
        feed=Depends(get_feed),
    ):
        token = request.cookies.get(COOKIE_NAME)
        try:
            owner = await stream_owner(token, authorization)
            header = request.headers.get("last-event-id")
            cursor = int(header) if header is not None else after
            if cursor is not None and cursor < 0:
                raise ValueError
        except ValueError as error:
            raise HTTPException(422, "Invalid event cursor") from error
        except StorageUnavailable as error:
            raise HTTPException(503, "Event storage unavailable") from error
        return StreamingResponse(
            stream(request, feed, owner, token, cursor, authorization),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    return router
