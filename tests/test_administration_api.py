import httpx
import pytest
from sqlalchemy.exc import SQLAlchemyError

from src.admin_main import app
from src.bootstrap.admin_database import admin_session


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_database_errors_are_unavailable_without_private_details():
    async def broken_session():
        raise SQLAlchemyError("PRIVATE_DATABASE_DETAILS")
        yield  # pragma: no cover

    app.dependency_overrides[admin_session] = broken_session
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://admin.test"
        ) as client:
            result = await client.get("/api/admin/users")
            assert result.status_code == 503
            assert result.headers["cache-control"] == "no-store"
            assert result.json() == {"detail": "administration_database_unavailable"}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_laboratory_commit_failure_never_acknowledges_saved_access(monkeypatch):
    from types import SimpleNamespace
    from uuid import uuid4

    from src.adapters.storage.postgres.administration import AdministrationRepository
    from src.bootstrap.admin_database import admin_write_session

    async def failed_commit():
        raise SQLAlchemyError("PRIVATE_COMMIT_DETAILS")

    async def session():
        yield SimpleNamespace(commit=failed_commit)

    async def set_access(*args):
        return {"laboratory_enabled": True}

    monkeypatch.setattr(AdministrationRepository, "set_laboratory_access", set_access)
    app.dependency_overrides[admin_write_session] = session
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://admin.test"
        ) as client:
            result = await client.patch(
                f"/api/admin/users/{uuid4()}/laboratory", json={"laboratory_enabled": True}
            )
            assert result.status_code == 503
            assert result.headers["cache-control"] == "no-store"
            assert result.json() == {"detail": "administration_database_unavailable"}
    finally:
        app.dependency_overrides.clear()
