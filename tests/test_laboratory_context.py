"""Owner-scoped, monotonic welcome preference without a workspace or LLM."""

from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.adapters.storage.postgres.accounts import Base, User
from src.bootstrap.auth import get_authenticated_user
from src.bootstrap.database import get_async_session
from src.bootstrap.settings import get_settings
from src.core.auth.identity import AuthenticatedUser
from src.extractors.personal_axes import routes


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_context_disabled_and_preference_is_owned_and_monotonic(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync: Base.metadata.create_all(sync, tables=[User.__table__])
        )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    first, second = uuid4(), uuid4()
    async with sessions() as sql:
        sql.add_all(
            [
                User(id=id, email=f"{id}@example.test", hashed_password="unused")
                for id in (first, second)
            ]
        )
        await sql.commit()

    async def session():
        async with sessions() as sql:
            yield sql

    identity = AuthenticatedUser(id=first, email="first@example.test")
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_async_session] = session
    app.dependency_overrides[get_authenticated_user] = lambda: identity
    monkeypatch.setattr(get_settings(), "personal_axes_enabled", False)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="https://app.test"
        ) as client:
            response = await client.get("/laboratory/context")
            assert response.status_code == 200
            assert response.json() == {
                "enabled": False,
                "welcome_dismissed": False,
                "sample_size": 5,
                "title_limit": 200,
                "purpose_limit": 8000,
                "adjustment_limit": 4000,
                "max_adjustments": 20,
            }
            # Merely reading context never writes a welcome marker.
            async with sessions() as sql:
                assert (
                    await sql.scalar(
                        select(User.laboratory_welcome_dismissed_at).where(User.id == first)
                    )
                    is None
                )
            assert (
                await client.patch("/laboratory/preferences", json={"welcome_dismissed": True})
            ).status_code == 200
            async with sessions() as sql:
                timestamp = await sql.scalar(
                    select(User.laboratory_welcome_dismissed_at).where(User.id == first)
                )
                assert timestamp is not None
            assert (
                await client.patch("/laboratory/preferences", json={"welcome_dismissed": True})
            ).json() == {"welcome_dismissed": True}
            async with sessions() as sql:
                assert (
                    await sql.scalar(
                        select(User.laboratory_welcome_dismissed_at).where(User.id == first)
                    )
                    == timestamp
                )
                assert (
                    await sql.scalar(
                        select(User.laboratory_welcome_dismissed_at).where(User.id == second)
                    )
                    is None
                )
            assert (
                await client.patch("/laboratory/preferences", json={"welcome_dismissed": False})
            ).status_code == 422
            assert (
                await client.patch(
                    "/laboratory/preferences",
                    json={"welcome_dismissed": True, "purpose": "private"},
                )
            ).status_code == 422
            assert (
                await client.patch(
                    "/laboratory/preferences",
                    headers={"Origin": "https://other.test"},
                    json={"welcome_dismissed": True},
                )
            ).status_code == 403
            identity = AuthenticatedUser(id=second, email="second@example.test")
            assert (await client.get("/laboratory/context")).json()["welcome_dismissed"] is False
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_context_and_preference_require_authentication(monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_session_secret", "laboratory-auth-test-secret")
    app = FastAPI()
    app.include_router(routes.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://app.test"
    ) as client:
        assert (await client.get("/laboratory/context")).status_code == 401
        assert (
            await client.patch("/laboratory/preferences", json={"welcome_dismissed": True})
        ).status_code == 401
