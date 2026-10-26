"""HTTP entrypoint for the El Espejo POC."""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse

from src.adapters.access.api.public.error_handlers import (
    client_disconnect_handler,
    logged_http_exception_handler,
    logged_validation_exception_handler,
    unexpected_exception_handler,
)
from src.adapters.access.api.public.errors import (
    invitation_error_handler,
    notification_error_handler,
)
from src.adapters.access.api.public.personal_axes.errors import axis_status
from src.adapters.access.api.public.request_logging import RequestLoggingMiddleware
from src.bootstrap.database import close_database
from src.bootstrap.logging import configure_logging
from src.bootstrap.observability import initialize_sentry, report_issue
from src.bootstrap.public_router import api_router
from src.bootstrap.settings import get_settings
from src.bootstrap.workspaces import reconcile_active_workspaces
from src.core.exteriorization.models import InvitationError
from src.core.extractors.personal_axes.models import AxisError
from src.core.notifications.rules import NotificationError

logger = logging.getLogger(__name__)
initialize_sentry("api")


async def _reconcile_workspaces_at_startup() -> None:
    try:
        await reconcile_active_workspaces()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("workspace_reconciliation_failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(get_settings().log_level)
    reconciliation = asyncio.create_task(_reconcile_workspaces_at_startup())
    try:
        yield
    finally:
        reconciliation.cancel()
        with suppress(asyncio.CancelledError):
            await reconciliation
        await close_database()


app = FastAPI(
    title="El Espejo",
    description="Personal AI-assisted introspection proof of concept.",
    version="0.1.0",
    # Nginx exposes this application under /api while proxying that prefix away.
    # Keep generated OpenAPI and Swagger UI URLs on the public path.
    root_path="/api",
    lifespan=lifespan,
)
app.include_router(api_router)
app.state.report_issue = report_issue
app.add_middleware(RequestLoggingMiddleware, report_issue=report_issue)


@app.exception_handler(AxisError)
async def axis_error_handler(request: Request, error: AxisError) -> JSONResponse:
    return JSONResponse(
        {"detail": error.code}, status_code=getattr(error, "status", axis_status(error))
    )


app.add_exception_handler(InvitationError, invitation_error_handler)
app.add_exception_handler(NotificationError, notification_error_handler)

app.add_exception_handler(HTTPException, logged_http_exception_handler)
app.add_exception_handler(RequestValidationError, logged_validation_exception_handler)
app.add_exception_handler(ClientDisconnect, client_disconnect_handler)
app.add_exception_handler(Exception, unexpected_exception_handler)
