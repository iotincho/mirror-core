"""Log server errors while preserving the public HTTP error contract."""

import logging

from fastapi import Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


def _log_server_error(request: Request, error: Exception, status_code: int) -> None:
    logger.error(
        "http_server_error method=%s path=%s status_code=%s request_id=%s",
        request.method,
        request.url.path,
        status_code,
        getattr(request.state, "request_id", "unavailable"),
        exc_info=(type(error), error, error.__traceback__),
    )


async def logged_http_exception_handler(request: Request, error: HTTPException) -> Response:
    """Include chained causes for errors translated to HTTP 5xx by routes/dependencies."""
    request.state.error_type = type(error.__cause__ or error).__name__
    if 500 <= error.status_code < 600:
        _log_server_error(request, error, error.status_code)
    return await http_exception_handler(request, error)


async def logged_validation_exception_handler(
    request: Request, error: RequestValidationError
) -> Response:
    # Never log errors(), str(error), input, or body: these can contain private notes.
    request.state.error_type = type(error).__name__
    request.state.validation_types = tuple(sorted({item["type"] for item in error.errors()}))
    return await request_validation_exception_handler(request, error)


async def client_disconnect_handler(request: Request, error: ClientDisconnect) -> Response:
    # The peer is already gone. Avoid reporting an interrupted upload as a server crash.
    request.state.error_type = type(error).__name__
    return Response(status_code=499)


async def unexpected_exception_handler(request: Request, error: Exception) -> Response:
    """Log unexpected failures without exposing internal details to the client."""
    _log_server_error(request, error, 500)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"},
        headers={"X-Request-ID": getattr(request.state, "request_id", "unavailable")},
    )
