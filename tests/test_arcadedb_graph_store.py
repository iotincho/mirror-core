from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.constellation.contracts import CrossDocumentLink, LinkType
from src.domain.documents import Document
from src.embeddings.contracts import (
    ClaimEmbeddingRecord,
    DocumentEmbeddingRecord,
    EmbeddingSpec,
    EvidenceReference,
)
from src.extraction.contracts import (
    Claim,
    ClaimType,
    Concept,
    Evidence,
    ExtractionReference,
    ExtractionResult,
    Relationship,
    RelationshipType,
)
from src.graph.arcadedb.store import ArcadeDBGraphStore
from src.services.extraction_store import new_extraction_run
from src.services.graph_store import GraphPersistenceError


class FakeArcadeDBClient:
    def __init__(self) -> None:
        self.commands: list[tuple[str, dict | None, str]] = []
        self.queries: list[tuple[str, dict | None, str]] = []
        self.query_results: list[dict] = []
        self.command_results: list[dict] = []
        self.transaction_count = 0
        self.closed = False

    @asynccontextmanager
    async def transaction(self):
        self.transaction_count += 1
        yield self

    async def command(self, statement, params=None, *, language="sql"):
        self.commands.append((statement, params, language))
        return self.command_results.pop(0) if self.command_results else {"result": []}

    async def query(self, statement, params=None, *, language="sql"):
        self.queries.append((statement, params, language))
        return self.query_results.pop(0)

    async def close(self) -> None:
        self.closed = True


def embedding_spec() -> EmbeddingSpec:
    return EmbeddingSpec(provider="openai", model="text-embedding-3-small", dimensions=3)


def completed_extraction():
    document = Document(
        id=uuid4(),
        content="Quiero más autonomía.",
        source="test",
        metadata={"filename": "note.md"},
        created_at=datetime(2026, 9, 29, tzinfo=UTC),
    )
    evidence = Evidence(
        quote="autonomía",
        start_char=11,
        end_char=20,
        start_line=1,
        end_line=1,
    )
    result = ExtractionResult(
        concepts=[Concept(id="autonomy", name="autonomía", evidence=[evidence])],
        entities=[],
        claims=[
            Claim(
                id="claim_1",
                text="Quiero más autonomía.",
                type=ClaimType.DESIRE,
                evidence=[evidence],
            )
        ],
        relationships=[
            Relationship(
                source=ExtractionReference(kind="claim", id="claim_1"),
                type=RelationshipType.ABOUT,
                target=ExtractionReference(kind="concept", id="autonomy"),
                evidence=[evidence],
            )
        ],
    )
    run = new_extraction_run(
        document_id=document.id,
        profile_name="v3",
        schema_version="v2",
        prompt_version="v3",
        provider="fake",
        model="fake-model",
        status="completed",
        result=result,
    )
    return document, run


def build_store(client: FakeArcadeDBClient) -> ArcadeDBGraphStore:
    return ArcadeDBGraphStore(
        "http://graph:2480",
        "el_espejo",
        "root",
        "password",
        client=client,
    )


@pytest.mark.anyio
async def test_persist_writes_full_extraction_inside_one_transaction() -> None:
    client = FakeArcadeDBClient()
    document, run = completed_extraction()

    document = document.model_copy(update={"title": "Una reflexión personal"})
    await build_store(client).persist(document, run)

    assert client.commands[0][1]["title"] == document.title
    joined = "\n".join(statement for statement, _, _ in client.commands)
    assert client.transaction_count == 1
    assert "MERGE (document:Document" in joined
    assert "MERGE (item:Concept" in joined
    assert "MERGE (item:Claim" in joined
    assert "relationship:ABOUT" in joined
    assert "MERGE (evidence:Evidence" in joined
    assert all(language == "cypher" for _, _, language in client.commands)


@pytest.mark.anyio
async def test_cross_document_links_keep_both_evidence_spans_in_one_transaction() -> None:
    client = FakeArcadeDBClient()
    link = CrossDocumentLink(
        source_claim_id="run-a:claim:1", target_claim_id="run-b:claim:2",
        source_document_id="doc-a", target_document_id="doc-b",
        relation_type=LinkType.REVISITS,
        source_evidence=[EvidenceReference(quote="Quiero pintar")],
        target_evidence=[EvidenceReference(quote="Volví a pintar")],
        similarity=0.81,
    )

    store = build_store(client)
    rows = store._cross_document_link_rows(link)
    client.command_results = [{"result": [{"persisted_id": row["id"]} for row in rows]}]

    await store.persist_cross_document_links([link, link])

    assert client.transaction_count == 1
    statement, params, language = client.commands[0]
    assert "CROSS_DOCUMENT_LINK" in statement
    assert language == "cypher"
    assert len(params["rows"]) == 2
    assert params["rows"][0]["link_id"] == params["rows"][1]["link_id"]
    assert {row["relation_type"] for row in params["rows"]} == {
        "REVISITS", "IS_REVISITED_BY",
    }
    assert '"source": [{"quote": "Quiero pintar"' in params["rows"][0]["evidence_json"]
    assert '"target": [{"quote": "Volví a pintar"' in params["rows"][0]["evidence_json"]


@pytest.mark.anyio
async def test_cross_document_link_persistence_fails_when_any_claim_was_not_matched() -> None:
    client = FakeArcadeDBClient()
    link = CrossDocumentLink(
        source_claim_id="run-a:claim:1", target_claim_id="run-b:claim:2",
        source_document_id="doc-a", target_document_id="doc-b",
        relation_type=LinkType.SAME_REFERENT,
        source_evidence=[EvidenceReference(quote="Quiero pintar")],
        target_evidence=[EvidenceReference(quote="Pintar me importa")],
        similarity=0.81,
    )
    client.command_results = [{"result": []}]

    with pytest.raises(GraphPersistenceError, match="did not persist every"):
        await build_store(client).persist_cross_document_links([link])


@pytest.mark.anyio
async def test_claim_embedding_search_preserves_neighbor_order_and_hydrates_context() -> None:
    client = FakeArcadeDBClient()
    client.query_results = [
        {
            "result": [
                {"claim_graph_id": "run:claim:second", "distance": 0.1},
                {"claim_graph_id": "run:claim:first", "distance": 0.25},
            ]
        },
        {
            "result": [
                {
                    "claim_id": claim_id,
                    "claim_local_id": claim_id.rsplit(":", 1)[-1],
                    "document_id": "document",
                    "run_id": "run",
                    "profile_name": "v3",
                    "prompt_version": "v3",
                    "text": claim_id,
                    "type": "desire",
                    "document_source": "test",
                    "document_metadata_json": '{"filename": "note.md"}',
                    "document_created_at": "2026-09-29T00:00:00+00:00",
                    "document_authored_at": None,
                    "evidence": [{"quote": "evidence", "start_line": 1, "end_line": 1}],
                }
                for claim_id in ("run:claim:first", "run:claim:second")
            ]
        },
    ]

    results = await build_store(client).search_claim_embeddings(
        [1.0, 0.0, 0.0],
        embedding_spec(),
        limit=2,
    )

    assert [result.claim_id for result in results] == [
        "run:claim:second",
        "run:claim:first",
    ]
    assert [result.score for result in results] == [0.9, 0.75]
    assert results[0].document_metadata == {"filename": "note.md"}
    assert client.queries[0][2] == "sql"
    assert client.queries[1][2] == "cypher"


@pytest.mark.anyio
async def test_persist_and_search_document_embedding_uses_versioned_type() -> None:
    client = FakeArcadeDBClient()
    spec = embedding_spec()
    record = DocumentEmbeddingRecord(
        id="document:embedding:hash",
        document_id="document",
        text_hash="hash",
        content="Quiero más autonomía.",
        source="test",
        metadata={"filename": "note.md"},
        created_at=datetime(2026, 9, 29, tzinfo=UTC),
        vector=[1.0, 0.0, 0.0],
        spec=spec,
    )
    store = build_store(client)

    await store.persist_document_embedding(record, spec)
    client.query_results = [
        {
            "result": [
                {
                    "document_id": "document",
                    "content": record.content,
                    "source": "test",
                    "metadata_json": '{"filename": "note.md"}',
                    "created_at": "2026-09-29T00:00:00+00:00",
                    "authored_at": None,
                    "distance": 0.05,
                }
            ]
        }
    ]
    results = await store.search_document_embeddings(record.vector, spec, limit=1)

    statement = client.commands[0][0]
    assert f"DocumentEmbedding_{spec.index_suffix}" in statement
    assert results[0].document_id == "document"
    assert results[0].score == 0.95


@pytest.mark.anyio
async def test_persist_claim_embeddings_and_delete_use_arcadedb_queries() -> None:
    client = FakeArcadeDBClient()
    spec = embedding_spec()
    store = build_store(client)
    await store.persist_claim_embeddings(
        [
            ClaimEmbeddingRecord(
                id="claim:embedding",
                claim_graph_id="run:claim:claim_1",
                claim_local_id="claim_1",
                document_id="document",
                run_id="run",
                profile_name="v3",
                prompt_version="v3",
                text_hash="hash",
                vector=[1.0, 0.0, 0.0],
                spec=spec,
            )
        ],
        spec,
    )
    await store.delete_document("document")

    assert f"ClaimEmbedding_{spec.index_suffix}" in client.commands[0][0]
    assert "DETACH DELETE" in client.commands[1][0]
    assert client.commands[1][1] == {"document_id": "document"}
