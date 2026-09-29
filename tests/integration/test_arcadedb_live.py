"""Opt-in smoke test against a running ArcadeDB instance."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.domain.documents import Document
from src.embeddings.contracts import ClaimEmbeddingRecord, DocumentEmbeddingRecord, EmbeddingSpec
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
from src.graph.arcadedb.client import ArcadeDBHTTPClient
from src.graph.arcadedb.schema import apply_schema
from src.graph.arcadedb.store import ArcadeDBGraphStore
from src.services.extraction_store import new_extraction_run

pytestmark = pytest.mark.skipif(
    os.getenv("ARCADEDB_INTEGRATION") != "1",
    reason="set ARCADEDB_INTEGRATION=1 to run against ArcadeDB",
)


def test_arcadedb_graph_store_end_to_end() -> None:
    http_url = os.getenv("ARCADEDB_HTTP_URL", "http://127.0.0.1:2480")
    database = os.getenv("ARCADEDB_DATABASE", "el_espejo")
    username = os.getenv("ARCADEDB_USERNAME", "root")
    password = os.getenv("ARCADEDB_ROOT_PASSWORD", "el-espejo-local-password")
    client = ArcadeDBHTTPClient(http_url, database, username, password)
    store = ArcadeDBGraphStore(
        http_url,
        database,
        username,
        password,
        client=client,
    )
    spec = EmbeddingSpec(provider="openai", model="text-embedding-3-small", dimensions=1536)
    apply_schema(client, spec)

    document = Document(
        id=uuid4(),
        content="Prueba integral de ArcadeDB.",
        source="arcadedb-integration-test",
        metadata={"temporary": "true"},
        created_at=datetime.now(UTC),
    )
    evidence = Evidence(
        quote="ArcadeDB",
        start_char=19,
        end_char=27,
        start_line=1,
        end_line=1,
    )
    extraction = new_extraction_run(
        document_id=document.id,
        profile_name="integration",
        schema_version="v1",
        prompt_version="integration",
        provider="test",
        model="test",
        status="completed",
        result=ExtractionResult(
            concepts=[Concept(id="arcadedb", name="ArcadeDB", evidence=[evidence])],
            entities=[],
            claims=[
                Claim(
                    id="claim_1",
                    text=document.content,
                    type=ClaimType.OBSERVATION,
                    evidence=[evidence],
                )
            ],
            relationships=[
                Relationship(
                    source=ExtractionReference(kind="claim", id="claim_1"),
                    type=RelationshipType.ABOUT,
                    target=ExtractionReference(kind="concept", id="arcadedb"),
                    evidence=[evidence],
                )
            ],
        ),
    )
    document_id = str(document.id)
    run_id = str(extraction.id)
    claim_id = f"{run_id}:claim:claim_1"
    vector = [1.0] + [0.0] * (spec.dimensions - 1)

    try:
        store.persist(document, extraction)
        store.persist(document, extraction)
        store.persist_claim_embeddings(
            [
                ClaimEmbeddingRecord(
                    id=f"{claim_id}:embedding:{spec.index_suffix}",
                    claim_graph_id=claim_id,
                    claim_local_id="claim_1",
                    document_id=document_id,
                    run_id=run_id,
                    profile_name=extraction.profile_name,
                    prompt_version=extraction.prompt_version,
                    text_hash="integration-claim",
                    vector=vector,
                    spec=spec,
                )
            ],
            spec,
        )
        store.persist_document_embedding(
            DocumentEmbeddingRecord(
                id=f"{document_id}:embedding:{spec.index_suffix}",
                document_id=document_id,
                text_hash="integration-document",
                content=document.content,
                source=document.source,
                metadata=document.metadata,
                created_at=document.created_at,
                vector=vector,
                spec=spec,
            ),
            spec,
        )

        claims = store.search_claim_embeddings(vector, spec, limit=10)
        documents = store.search_document_embeddings(vector, spec, limit=10)
        relations = store.get_claim_relations([claim_id])

        assert [item.claim_id for item in claims].count(claim_id) == 1
        assert [item.document_id for item in documents].count(document_id) == 1
        assert len(relations) == 1
        assert relations[0].relation_type == "ABOUT"
    finally:
        store.delete_document(document_id)
        store.close()

    response = client.query(
        "SELECT count(*) AS count FROM Document WHERE id = :document_id",
        {"document_id": document_id},
    )
    assert response["result"][0]["count"] == 0
