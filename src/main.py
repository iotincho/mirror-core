"""HTTP entrypoint for the El Espejo POC."""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from src.api.error_handlers import (
    logged_http_exception_handler,
    unexpected_exception_handler,
)
from src.api.router import api_router
from src.config import get_settings
from src.exteriorization.repository import InvitationError
from src.logging import configure_logging
from src.user_management.database import close_database
from src.workspaces.provisioning import reconcile_active_workspaces

logger = logging.getLogger(__name__)


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


@app.exception_handler(InvitationError)
async def invitation_error_handler(request: Request, error: InvitationError) -> JSONResponse:
    headers = {"Retry-After": "60"} if error.status_code == 429 else None
    return JSONResponse({"detail": error.code}, status_code=error.status_code, headers=headers)


app.add_exception_handler(HTTPException, logged_http_exception_handler)
app.add_exception_handler(Exception, unexpected_exception_handler)
