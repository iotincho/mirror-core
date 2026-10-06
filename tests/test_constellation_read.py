import json
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from src.api.routes.retired import router
from src.constellation.contracts import LinkType
from src.embeddings.contracts import EmbeddingSpec
from src.extraction.contracts import ExtractionResult
from src.graph.arcadedb.store import ArcadeDBGraphStore
from src.services.extraction_store import FileExtractionStore, new_extraction_run


class QueryClient:
    def __init__(self, results):
        self.results = results
        self.calls = []

    async def query(self, query, params, *, language):
        self.calls.append((query, params, language))
        return {"result": self.results.pop(0)}


def store(client):
    return ArcadeDBGraphStore("http://unused", "user-database", "user", "secret", client=client)


@pytest.mark.anyio
async def test_neighborhood_pages_in_server_and_deduplicates_reciprocal_edges():
    row = {
        "link_id": "shared",
        "source_claim_id": "claim-a",
        "target_claim_id": "claim-b",
        "source_document_id": "a",
        "target_document_id": "b",
        "relation_type": "SAME_REFERENT",
        "profile": "link-v1",
        "evidence_json": json.dumps({"source": [{"quote": "A"}], "target": [{"quote": "B"}]}),
    }
    reverse = {
        **row,
        "source_claim_id": "claim-b",
        "target_claim_id": "claim-a",
        "source_document_id": "b",
        "target_document_id": "a",
        "evidence_json": json.dumps({"source": [{"quote": "B"}], "target": [{"quote": "A"}]}),
    }
    client = QueryClient([[{"total": 3}], [{"neighbor_id": "b"}], [row, reverse]])
    result = await store(client).get_link_neighborhood("a", offset=1, limit=1)
    assert result.neighbor_ids == ["b"]
    assert result.next_offset == 2
    assert len(result.links) == 1
    assert result.links[0].source_evidence[0].quote == "B"
    assert client.calls[1][1]["limit"] == 1
    assert client.calls[2][1]["document_ids"] == ["a", "b"]
    assert "IS_REVISITED_BY" not in client.calls[0][1]["relation_types"]


@pytest.mark.anyio
async def test_temporal_filter_does_not_include_inverse_projection():
    client = QueryClient([[{"total": 0}], []])
    result = await store(client).get_link_neighborhood("a", relation_type=LinkType.SHIFTS)
    assert result.links == [] and result.next_offset is None
    assert client.calls[0][1]["relation_types"] == ["SHIFTS"]


@pytest.mark.anyio
async def test_readiness_requires_all_expected_claims_and_current_embeddings():
    client = QueryClient(
        [
            [
                {"run_id": "ready", "claim_count": 2, "embedded_count": 2},
                {"run_id": "missing-embedding", "claim_count": 2, "embedded_count": 1},
                {"run_id": "partial-graph", "claim_count": 1, "embedded_count": 1},
            ]
        ]
    )
    result = await store(client).ready_extraction_ids(
        {"ready": 2, "missing-embedding": 2, "partial-graph": 2},
        EmbeddingSpec(provider="openai", model="current-model", dimensions=3),
    )
    assert result == {"ready"}
    assert client.calls[0][1]["model"] == "current-model"


@pytest.mark.anyio
async def test_file_history_is_scoped_to_its_workspace_and_document(tmp_path):
    extraction_store = FileExtractionStore(tmp_path / "own")
    another_store = FileExtractionStore(tmp_path / "other")
    doc_id = uuid4()
    run = new_extraction_run(
        document_id=doc_id,
        profile_name="v5",
        schema_version="v3",
        prompt_version="v5",
        provider="fake",
        model="fake",
        status="completed",
        result=ExtractionResult(concepts=[], entities=[], claims=[], relationships=[]),
    )
    await extraction_store.save(run)
    assert await extraction_store.list_for_document(doc_id) == [run]
    assert await extraction_store.list_for_document(uuid4()) == []
    assert await another_store.list_for_document(doc_id) == []


@pytest.mark.anyio
async def test_constellation_history_and_links_are_retired():
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        assert (await client.get("/documents/source/links")).status_code == 410
        assert (await client.get("/documents/source/extractions")).status_code == 410


@pytest.fixture
def anyio_backend():
    return "asyncio"
