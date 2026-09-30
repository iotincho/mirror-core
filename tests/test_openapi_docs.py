import httpx
import pytest

from src.main import app


@pytest.mark.anyio
async def test_docs_references_the_public_openapi_path() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/docs")

    assert response.status_code == 200
    assert "url: '/api/openapi.json'" in response.text


@pytest.mark.anyio
async def test_openapi_schema_declares_the_public_api_prefix() -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["openapi"].startswith("3.")
    assert response.json()["servers"] == [{"url": "/api"}]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
