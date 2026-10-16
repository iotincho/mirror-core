"""Observe HTTP failures and uploads without reading or buffering request bodies."""

import logging
from time import monotonic
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.observability import report_issue

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        state = scope.setdefault("state", {})
        state["request_id"] = request_id = str(uuid4())
        method, path = scope["method"], scope["path"]
        writing = method in {"POST", "PUT", "PATCH", "DELETE"}
        started_at = monotonic()
        received_bytes = 0
        disconnected = False
        context = f"method={method} path={path} request_id={request_id}"
        if writing:
            logger.info("http_write_started %s", context)

        async def observed_receive() -> Message:
            nonlocal received_bytes, disconnected
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
            elif message["type"] == "http.disconnect" and writing and not disconnected:
                disconnected = True
                report_issue("upload_disconnected", request_id=request_id, method=method)
                logger.warning(
                    "http_client_disconnected %s received_bytes=%s elapsed_ms=%s",
                    context, received_bytes, int((monotonic() - started_at) * 1000),
                )
            return message

        async def observed_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                status = message["status"]
                if writing and 400 <= status < 500 and not disconnected:
                    route = scope.get("route")
                    report_issue(
                        "http_write_rejected", status_code=status, method=method,
                        request_id=request_id, route=getattr(route, "path", None),
                        error_code=state.get("error_type", "http_error"),
                    )
                message = dict(message)
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-request-id", request_id.encode("ascii")),
                ]
                if writing or status >= 400:
                    logger.log(
                        logging.ERROR if status >= 500 else (
                            logging.WARNING if status >= 400 else logging.INFO
                        ),
                        "http_response %s status_code=%s received_bytes=%s elapsed_ms=%s "
                        "error_type=%s validation_types=%s",
                        context, status, received_bytes,
                        int((monotonic() - started_at) * 1000),
                        state.get("error_type", "none"), state.get("validation_types", ()),
                    )
            await send(message)

        await self.app(scope, observed_receive, observed_send)
