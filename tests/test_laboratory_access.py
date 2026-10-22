"""Account grants protect HTTP and only the LAN admin surface can change them."""

from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.administration.config import get_admin_settings
from src.administration.database import admin_session, admin_write_session
from src.administration.models import DocumentMetric, InventoryState, UserActivity
from src.administration.routes import router as admin_router
from src.config import get_settings
from src.extractors.personal_axes.routes import router
from src.user_management.database import get_async_session
from src.user_management.dependencies import AuthenticatedUser, get_authenticated_user
from src.user_management.models import Base, User
from src.workspaces.dependencies import get_workspace_runtime


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def access():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync: Base.metadata.create_all(
                sync,
                tables=[
                    User.__table__,
                    DocumentMetric.__table__,
                    InventoryState.__table__,
                    UserActivity.__table__,
                ],
            )
        )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    first, second = uuid4(), uuid4()
    async with sessions.begin() as session:
        session.add_all(
            [
                User(id=id, email=f"{id}@example.test", hashed_password="PRIVATE_HASH")
                for id in (first, second)
            ]
        )

    async def database():
        async with sessions.begin() as session:
            yield session

    async def workspace():
        # An allowed request reaches workspace resolution; a denied one must not.
        raise HTTPException(418, "workspace_reached")

    app = FastAPI()
    app.include_router(router)
    app.include_router(admin_router)
    for dependency in (get_async_session, admin_session, admin_write_session):
        app.dependency_overrides[dependency] = database
    app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(
        id=first, email="first@example.test"
    )
    app.dependency_overrides[get_workspace_runtime] = workspace
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="https://admin.test"
        ) as client:
            yield client, sessions, first, second
    finally:
        await engine.dispose()


@pytest.mark.anyio
async def test_global_and_account_access_matrix_and_revocation(access, monkeypatch):
    client, sessions, first, second = access
    for global_enabled in (False, True):
        monkeypatch.setattr(get_settings(), "personal_axes_enabled", global_enabled)
        monkeypatch.setattr(get_admin_settings(), "personal_axes_enabled", global_enabled)
        for granted in (False, True):
            result = await client.patch(
                f"/api/admin/users/{first}/laboratory", json={"laboratory_enabled": granted}
            )
            assert result.status_code == 200
            assert result.json()["laboratory_enabled"] is granted
            assert result.json()["laboratory_global_enabled"] is global_enabled
            assert "PRIVATE_HASH" not in result.text
            assert (await client.get("/laboratory/context")).json()["enabled"] is (
                global_enabled and granted
            )
            assert (await client.get("/personal-axes")).status_code == (
                418 if global_enabled and granted else 404
            )
    # Revoke after having accessed the feature; no restart or identity refresh.
    await client.patch(f"/api/admin/users/{first}/laboratory", json={"laboratory_enabled": False})
    for path in (
        "/personal-axes",
        f"/personal-axes/{uuid4()}/findings",
        f"/laboratory/axis-previews/{uuid4()}",
    ):
        assert (await client.get(path)).status_code == 404
    async with sessions() as session:
        assert (
            await session.scalar(select(User.laboratory_enabled).where(User.id == second)) is False
        )
    assert (await client.get(f"/api/admin/users/{first}")).json()["laboratory_enabled"] is False
    rows = (await client.get("/api/admin/users")).json()["items"]
    assert all(row["laboratory_enabled"] is False for row in rows)


@pytest.mark.anyio
async def test_admin_patch_is_narrow_idempotent_and_rejects_cross_origin(access):
    client, sessions, first, second = access
    path = f"/api/admin/users/{first}/laboratory"
    for payload in (
        {"laboratory_enabled": "true"},
        {"laboratory_enabled": 1},
        {},
        {"laboratory_enabled": True, "is_superuser": True},
    ):
        assert (await client.patch(path, json=payload)).status_code == 422
    for headers in (
        {"Origin": "https://evil.test"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Origin": "null"},
    ):
        assert (
            await client.patch(path, headers=headers, json={"laboratory_enabled": True})
        ).status_code == 403
    assert (
        await client.patch(
            f"/api/admin/users/{uuid4()}/laboratory", json={"laboratory_enabled": True}
        )
    ).status_code == 404
    for _ in range(2):
        result = await client.patch(
            path, headers={"Origin": "https://admin.test"}, json={"laboratory_enabled": True}
        )
        assert result.status_code == 200
        assert result.json()["laboratory_enabled"] is True
    async with sessions() as session:
        assert await session.scalar(select(User.is_superuser).where(User.id == first)) is False
        assert (
            await session.scalar(select(User.laboratory_enabled).where(User.id == second)) is False
        )
        assert (
            await session.scalar(
                select(User.laboratory_welcome_dismissed_at).where(User.id == first)
            )
            is None
        )


def test_public_application_has_no_administrative_write_route():
    from src.main import app
    from src.user_management.schemas import UserCreate, UserUpdate

    assert not any(path.startswith("/api/admin") for path in app.openapi()["paths"])
    assert "laboratory_enabled" not in UserUpdate.model_fields
    assert "laboratory_enabled" not in UserCreate.model_fields
