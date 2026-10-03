"""Correlate failures from routes, dependencies, and infrastructure adapters."""

import logging
from time import perf_counter
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.logging import request_id_context

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid4())
        token = request_id_context.set(request_id)
        started = perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            logger.exception(
                "http_request_unhandled_error method=%s path=%s request_id=%s",
                scope["method"], scope["path"], request_id,
            )
            raise
        finally:
            log = logger.error if status_code >= 500 else logger.info
            log(
                "http_request_completed method=%s path=%s status=%s duration_ms=%.1f "
                "request_id=%s",
                scope["method"], scope["path"], status_code,
                (perf_counter() - started) * 1000, request_id,
            )
            request_id_context.reset(token)
