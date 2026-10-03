"""HTTP entrypoint for the El Espejo POC."""

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from src.api.middleware import RequestLoggingMiddleware
from src.api.router import api_router
from src.config import get_settings
from src.dependencies import close_graph_store
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
        close_graph_store()
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
app.add_middleware(RequestLoggingMiddleware)
