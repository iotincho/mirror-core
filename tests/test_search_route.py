from datetime import UTC, datetime

import httpx
import pytest

from src.auth.session import require_authenticated
from src.dependencies import get_search_semantically
from src.embeddings.contracts import SimilarClaim, SimilarDocument
from src.main import app


class FakeSearchSemantically:
    async def execute(self, query: str, limit: int):
        assert query == "autonomía"
        assert limit == 3
        return [
            SimilarDocument(
                document_id="document",
                content="Quiero más autonomía.",
                source="manual",
                metadata={"filename": "note.md"},
                created_at=datetime.now(UTC),
                score=0.91,
            ),
            SimilarClaim(
                claim_id="run:claim:autonomy",
                claim_local_id="autonomy",
                document_id="document",
                run_id="run",
                profile_name="v3",
                prompt_version="v3",
                text="Quiero más autonomía.",
                type="desire",
                score=0.88,
                evidence=[],
            ),
        ]


@pytest.mark.anyio
async def test_search_returns_document_and_claim_results() -> None:
    async def override_search() -> FakeSearchSemantically:
        return FakeSearchSemantically()

    async def override_authentication() -> str:
        return "test-user"

    app.dependency_overrides[get_search_semantically] = override_search
    app.dependency_overrides[require_authenticated] = override_authentication
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/search", json={"query": "autonomía", "limit": 3})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert [item["target"] for item in response.json()] == ["document", "claim"]
    assert response.json()[0]["metadata"] == {"filename": "note.md"}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
