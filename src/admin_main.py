"""LAN-only, read-only administrative process; independent of the public application."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse

from src.administration.database import close_admin_database, get_admin_sessions
from src.administration.routes import router


@asynccontextmanager
async def lifespan(app):
    yield
    await close_admin_database()


app = FastAPI(title="El Espejo · Administración LAN", lifespan=lifespan)
app.include_router(router)


@app.middleware("http")
async def private_responses(request, call_next):
    try:
        response = await call_next(request)
    except SQLAlchemyError:
        response = JSONResponse({"detail": "administration_database_unavailable"}, status_code=503)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/health", include_in_schema=False)
async def health():
    async with get_admin_sessions()() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ok"}
