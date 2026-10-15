"""Exercise the real auth routes and workspace retry using an isolated SQL database."""

from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import Depends, FastAPI
from fastapi_users.authentication.strategy.db import DatabaseStrategy
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.config import Settings
from src.user_management.authentication import get_database_strategy
from src.user_management.database import get_access_token_db, get_async_session
from src.user_management.models import AccessToken, Base, OAuthAccount, User
from src.user_management.routes import build_router, session
from src.workspaces import provisioning
from src.workspaces.arcade_admin import ArcadeDBAdminError
from src.workspaces.models import UserWorkspace
from src.workspaces.routes import router as workspace_router

PASSWORD = "a-long-private-passphrase"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def signup_env(monkeypatch, tmp_path):
    settings = Settings(auth_session_secret="signup-test-secret", workspaces_path=tmp_path)
    engine = create_async_engine("sqlite+aiosqlite://")
    tables = [
        User.__table__,
        OAuthAccount.__table__,
        AccessToken.__table__,
        UserWorkspace.__table__,
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr("src.user_management.manager.get_settings", lambda: settings)
    monkeypatch.setattr("src.workspaces.routes.get_settings", lambda: settings)
    monkeypatch.setattr(provisioning, "get_settings", lambda: settings)
    monkeypatch.setattr(provisioning, "get_session_maker", lambda: sessions)
    env = SimpleNamespace(fail=False, crash=False, targets=[], sessions=sessions)

    def remote(self, target):
        env.targets.append(target)
        if env.fail:
            raise ArcadeDBAdminError("simulated remote failure with private details")

    monkeypatch.setattr(provisioning.WorkspaceProvisioner, "_provision_remote", remote)
    original_start = provisioning.WorkspaceProvisioner._start

    async def start(self, *args, **kwargs):
        if env.crash:
            raise RuntimeError("simulated allocation failure")
        return await original_start(self, *args, **kwargs)

    monkeypatch.setattr(provisioning.WorkspaceProvisioner, "_start", start)

    async def db_session():
        async with sessions() as sql:
            yield sql

    # Exercise actual persisted cookies, including logout, without invoking the
    # unrelated invitation module's PostgreSQL-only session cleanup.
    async def strategy(db=Depends(get_access_token_db)):
        return DatabaseStrategy(db, lifetime_seconds=3600)

    app = FastAPI()
    router = build_router(settings)
    router.add_api_route("/session", session, methods=["GET"])
    app.include_router(router)
    app.include_router(workspace_router)
    app.dependency_overrides[get_async_session] = db_session
    app.dependency_overrides[get_database_strategy] = strategy
    env.transport = ASGITransport(app=app)
    async with AsyncClient(transport=env.transport, base_url="https://signup.test") as client:
        env.client = client
        yield env
    await engine.dispose()


async def register(client, email="alex@example.com"):
    return await client.post("/auth/register", json={"email": email, "password": PASSWORD})


async def login(client, email="alex@example.com"):
    return await client.post("/auth/login", data={"username": email, "password": PASSWORD})


@pytest.mark.anyio
async def test_registration_login_workspace_and_revocable_session(signup_env):
    env = signup_env
    assert (await env.client.get("/workspace/status")).status_code == 401
    assert (await env.client.post("/workspace/prepare")).status_code == 401
    created = await register(env.client)
    assert created.status_code == 201
    user = created.json()
    assert "hashed_password" not in user
    # Registration never implicitly signs in; the PWA explicitly performs login.
    assert (await env.client.get("/auth/session")).status_code == 401
    assert (await login(env.client)).status_code == 204
    assert (await env.client.get("/auth/session")).json()["user_id"] == user["id"]
    assert (await env.client.get("/workspace/status")).json() == {"status": "active"}
    assert (await env.client.post("/workspace/prepare")).json() == {"status": "active"}
    assert len(env.targets) == 1
    async with env.sessions() as sql:
        stored = await sql.get(User, UUID(user["id"]))
        assert stored.hashed_password != PASSWORD
    assert (await env.client.post("/auth/logout")).status_code == 204
    assert (await env.client.get("/auth/session")).status_code == 401
    assert (await login(env.client)).status_code == 204


@pytest.mark.anyio
async def test_failed_workspace_preserves_account_and_retries_same_allocation(signup_env):
    env = signup_env
    env.fail = True
    assert (await register(env.client)).status_code == 201
    assert (await login(env.client)).status_code == 204
    assert (await env.client.get("/workspace/status")).json() == {"status": "failed"}
    duplicate = await register(env.client)
    assert duplicate.status_code == 400
    assert duplicate.json()["detail"] == "REGISTER_USER_ALREADY_EXISTS"
    env.fail = False
    assert (await env.client.post("/workspace/prepare")).json() == {"status": "active"}
    assert env.targets[0] == env.targets[1]
    async with env.sessions() as sql:
        assert await sql.scalar(select(func.count()).select_from(User)) == 1


@pytest.mark.anyio
async def test_allocation_exception_does_not_turn_committed_registration_into_failure(signup_env):
    env = signup_env
    env.crash = True
    assert (await register(env.client)).status_code == 201
    assert (await login(env.client)).status_code == 204
    assert (await env.client.get("/workspace/status")).json() == {"status": "unavailable"}
    failed = await env.client.post("/workspace/prepare")
    assert failed.status_code == 503
    assert "allocation" not in failed.text
    env.crash = False
    assert (await env.client.post("/workspace/prepare")).json() == {"status": "active"}


@pytest.mark.anyio
async def test_workspace_status_retry_and_suspension_are_scoped_to_cookie_owner(signup_env):
    env = signup_env
    env.fail = True
    first = (await register(env.client)).json()
    assert (await login(env.client)).status_code == 204
    env.fail = False
    async with AsyncClient(transport=env.transport, base_url="https://signup.test") as other:
        second = (await register(other, "other@example.com")).json()
        assert (await login(other, "other@example.com")).status_code == 204
        assert (await other.get("/workspace/status")).json() == {"status": "active"}
        # Even a forged owner parameter cannot redirect a retry to another user.
        await other.post("/workspace/prepare", json={"user_id": first["id"]})
    assert (await env.client.get("/workspace/status")).json() == {"status": "failed"}
    async with env.sessions.begin() as sql:
        own = await sql.get(UserWorkspace, UUID(first["id"]))
        own.status = "suspended"
    before = len(env.targets)
    assert (await env.client.post("/workspace/prepare")).json() == {"status": "suspended"}
    assert len(env.targets) == before
    assert first["id"] != second["id"]


@pytest.mark.anyio
async def test_invalid_password_and_google_email_collision_do_not_create_accounts(signup_env):
    env = signup_env
    weak = await env.client.post(
        "/auth/register", json={"email": "alex@example.com", "password": "short"}
    )
    assert weak.status_code == 400
    assert weak.json()["detail"]["code"] == "REGISTER_INVALID_PASSWORD"
    async with env.sessions.begin() as sql:
        user = User(email="google@example.com", hashed_password="unused-google-only-password")
        sql.add(user)
        await sql.flush()
        sql.add(
            OAuthAccount(
                user_id=user.id,
                oauth_name="google",
                access_token="test",
                account_id="google-id",
                account_email=user.email,
            )
        )
    duplicate = await register(env.client, "google@example.com")
    assert duplicate.status_code == 400
    assert duplicate.json()["detail"] == "REGISTER_USER_ALREADY_EXISTS"
    assert not env.targets


@pytest.mark.anyio
async def test_retry_does_not_duplicate_in_progress_provisioning(signup_env):
    env = signup_env
    created = (await register(env.client)).json()
    assert (await login(env.client)).status_code == 204
    async with env.sessions.begin() as sql:
        workspace = await sql.get(UserWorkspace, UUID(created["id"]))
        workspace.status = "provisioning"
    before = len(env.targets)
    assert (await env.client.post("/workspace/prepare")).json() == {"status": "provisioning"}
    assert len(env.targets) == before


@pytest.mark.anyio
async def test_invalid_active_workspace_binding_does_not_expose_secrets(signup_env):
    env = signup_env
    created = (await register(env.client)).json()
    assert (await login(env.client)).status_code == 204
    async with env.sessions.begin() as sql:
        workspace = await sql.get(UserWorkspace, UUID(created["id"]))
        workspace.graph_secret_ciphertext = "corrupted-private-binding"
    assert (await env.client.get("/workspace/status")).json() == {"status": "unavailable"}
    assert (await env.client.post("/workspace/prepare")).json() == {"status": "unavailable"}
    assert len(env.targets) == 1
