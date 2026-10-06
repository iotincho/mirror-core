import httpx
import pytest

from src.auth.session import require_authenticated
from src.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "path",
    [
        "/documents/source/extractions",
        "/v2/documents/source/extractions",
        "/documents/source/extractions/run/embeddings",
        "/documents/source/links",
        "/search",
        "/search/claims",
        "/resolve",
    ],
)
async def test_exploratory_routes_are_explicitly_retired(path):
    # No workspace/provider overrides: retired routes cannot construct those dependencies.
    app.dependency_overrides[require_authenticated] = lambda: "owner"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.post(path, json={})
        assert response.status_code == 410
    finally:
        app.dependency_overrides.clear()
