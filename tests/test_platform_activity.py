from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from src.api.routes import activity
from src.bootstrap.auth import get_authenticated_user
from src.core.auth.identity import AuthenticatedUser


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_activity_is_opt_in_and_does_not_accept_another_owner(monkeypatch):
    app = FastAPI()
    app.include_router(activity.router)
    owner = uuid4()
    app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(
        owner, "test@example.com"
    )
    observations = []

    async def observe(sessions, user_id):
        observations.append(user_id)

    monkeypatch.setattr(activity, "record_access", observe)
    monkeypatch.setattr(activity, "get_session_maker", lambda: "unused")
    monkeypatch.setattr(
        activity, "get_settings", lambda: SimpleNamespace(platform_activity_enabled=False)
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://app.test"
    ) as client:
        assert (await client.post("/activity")).status_code == 204
        assert observations == []
        monkeypatch.setattr(
            activity, "get_settings", lambda: SimpleNamespace(platform_activity_enabled=True)
        )
        assert (await client.post("/activity", json={"user_id": str(uuid4())})).status_code == 204
        assert observations == [owner]
        assert (
            await client.post("/activity", headers={"Origin": "http://other.test"})
        ).status_code == 403
        assert observations == [owner]
