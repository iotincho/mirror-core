import httpx
import pytest

from src.bootstrap.public_api import app


@pytest.mark.anyio
async def test_health_endpoint_returns_ok() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
