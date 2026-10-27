"""LAN administration composition with its own settings, SQL pool and application."""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse

from src.adapters.access.api.administration.routes import build_router
from src.adapters.storage.postgres.administration import AdministrationRepository
from src.adapters.storage.postgres.health import PostgresHealth
from src.bootstrap.admin_database import (
    admin_session,
    admin_write_session,
    close_admin_database,
    get_admin_sessions,
)
from src.bootstrap.administration_settings import get_admin_settings
from src.core.processing.errors import StorageUnavailable
from src.use_cases.administration.query import Administration


def administration(session):
    settings = get_admin_settings()
    return Administration(
        AdministrationRepository(
            session,
            settings.inventory_max_age_seconds,
            personal_axes_enabled=settings.personal_axes_enabled,
        )
    )


def get_read_administration(session=Depends(admin_session)):
    return administration(session)


def get_write_administration(session=Depends(admin_write_session)):
    return administration(session)


@asynccontextmanager
async def lifespan(app):
    yield
    await close_admin_database()


app = FastAPI(title="El Espejo · Administración LAN", lifespan=lifespan)
router = build_router(get_read_administration, get_write_administration)
app.include_router(router)


@app.middleware("http")
async def private_responses(request, call_next):
    try:
        response = await call_next(request)
    except (SQLAlchemyError, StorageUnavailable):
        response = JSONResponse({"detail": "administration_database_unavailable"}, status_code=503)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/health", include_in_schema=False)
async def health():
    await PostgresHealth(get_admin_sessions()).check()
    return {"status": "ok"}
