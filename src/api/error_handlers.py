"""Log server errors while preserving the public HTTP error contract."""

import logging

from fastapi import Request
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


def _log_server_error(request: Request, error: Exception, status_code: int) -> None:
    logger.error(
        "http_server_error method=%s path=%s status_code=%s",
        request.method,
        request.url.path,
        status_code,
        exc_info=(type(error), error, error.__traceback__),
    )


async def logged_http_exception_handler(request: Request, error: HTTPException) -> Response:
    """Include chained causes for errors translated to HTTP 5xx by routes/dependencies."""
    if 500 <= error.status_code < 600:
        _log_server_error(request, error, error.status_code)
    return await http_exception_handler(request, error)


async def unexpected_exception_handler(request: Request, error: Exception) -> Response:
    """Log unexpected failures without exposing internal details to the client."""
    _log_server_error(request, error, 500)
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})
