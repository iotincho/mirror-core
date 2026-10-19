import httpx
import pytest
from sqlalchemy.exc import SQLAlchemyError

from src.admin_main import app
from src.administration.database import admin_session


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
