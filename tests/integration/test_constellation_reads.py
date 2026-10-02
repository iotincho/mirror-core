"""Opt-in graph reads against an isolated temporary ArcadeDB database."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.config import Settings
from src.constellation.contracts import CrossDocumentLink, LinkType
from src.constellation.supplement import prepare_supplement
from src.domain.documents import Document
from src.embeddings.contracts import ClaimEmbeddingRecord, EmbeddingSpec, EvidenceReference
from src.extraction.contracts import (
    Claim,
    ClaimType,
    Entity,
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
from src.services.graph_store import GraphPersistenceError
from src.use_cases.embed_claims import EmbedClaims
from src.workspaces.arcade_admin import ArcadeDBAdminClient

pytestmark = pytest.mark.skipif(
    os.getenv("ARCADEDB_INTEGRATION") != "1", reason="requires a local ArcadeDB instance"
)


def test_saved_neighborhood_and_extraction_readiness():
    settings = Settings()
    url = "http://127.0.0.1:2480"
    database = f"test_constellation_{uuid4().hex}"
    admin = ArcadeDBAdminClient(url, settings.arcadedb_username, settings.arcadedb_password)
    assert not admin.database_exists(database)
    admin.ensure_database(database)
    client = ArcadeDBHTTPClient(url, database, settings.arcadedb_username,
                               settings.arcadedb_password)
    store = ArcadeDBGraphStore(url, database, settings.arcadedb_username,
                              settings.arcadedb_password, client=client)
    spec = EmbeddingSpec(provider="test", model="test", dimensions=3)
    try:
        apply_schema(client, spec)
        documents, runs, claims = [], [], []
        for index in range(3):
            document = Document(id=uuid4(), content=f"Nota {index}. Quiero pintar.", source="test",
                                metadata={}, created_at=datetime.now(UTC))
            run = new_extraction_run(
                document_id=document.id, profile_name="v5", schema_version="v3",
                prompt_version="v5", provider="test", model="test", status="completed",
                result=ExtractionResult(concepts=[], entities=[], relationships=[], claims=[
                    Claim(id="c", text=document.content, type=ClaimType.OBSERVATION,
                          evidence=[Evidence(quote=document.content, start_char=0,
                                             end_char=6, start_line=1, end_line=1)])
                ]),
            )
            store.persist(document, run)
            claim_id = f"{run.id}:claim:c"
            documents.append(str(document.id))
            runs.append(str(run.id))
            claims.append(claim_id)
            if index != 2:
                store.persist_claim_embeddings([ClaimEmbeddingRecord(
                    id=f"{claim_id}:embedding:{spec.index_suffix}", claim_graph_id=claim_id,
                    claim_local_id="c", document_id=str(document.id), run_id=str(run.id),
                    profile_name="v5", prompt_version="v5", text_hash="fixture",
                    vector=[1.0, 0.0, 0.0], spec=spec,
                )], spec)
        assert store.ready_extraction_ids(dict.fromkeys(runs, 1), spec) == set(runs[:2])
        for index, kind in [(1, LinkType.SAME_REFERENT), (2, LinkType.SHIFTS)]:
            link = CrossDocumentLink(
                source_claim_id=claims[0], target_claim_id=claims[index],
                source_document_id=documents[0], target_document_id=documents[index],
                relation_type=kind, source_evidence=[EvidenceReference(quote="Origen")],
                target_evidence=[EvidenceReference(quote="Destino")], similarity=0.8,
            )
            store.persist_cross_document_links([link])
            store.persist_cross_document_links([link])
            with pytest.raises(GraphPersistenceError):
                store.persist_cross_document_links([
                    link, link.model_copy(update={"source_claim_id": "missing"})
                ])
        page = store.get_link_neighborhood(documents[0], limit=1)
        assert page.total_neighbors == 2
        assert len(page.neighbor_ids) == len(page.links) == 1
        assert page.next_offset == 1
        assert len(store.get_link_neighborhood(documents[0], offset=1, limit=1).links) == 1
        reverse = store.get_link_neighborhood(documents[2])
        assert len(reverse.links) == 1
        assert reverse.links[0].relation_type == LinkType.SHIFTS
        assert reverse.links[0].source_document_id == documents[0]
        assert store.get_link_neighborhood(
            documents[0], relation_type=LinkType.IN_TENSION
        ).total_neighbors == 0

        # Nodes, evidence, internal relations and links share one real transaction.
        source = Document(id=documents[0], content="Nota 0. Quiero pintar.", source="test",
                          metadata={}, created_at=datetime.now(UTC))
        parent = run.model_copy(update={"id": runs[0], "document_id": source.id})
        evidence = Evidence(quote="Quiero pintar.")
        additions = ExtractionResult(
            concepts=[], entities=[Entity(id="painting", name="pintura", type="actividad",
                                          evidence=[evidence])],
            claims=[Claim(id="paint", text="Quiero pintar.", type=ClaimType.DESIRE,
                          evidence=[evidence])],
            relationships=[Relationship(
                source=ExtractionReference(kind="claim", id="paint"),
                type=RelationshipType.ABOUT,
                target=ExtractionReference(kind="entity", id="painting"), evidence=[evidence],
            )],
        )
        supplement = prepare_supplement(source, parent, additions,
                                        store.existing_document_items(documents[0]),
                                        provider="test", model="test")
        assert supplement is not None
        new_link = CrossDocumentLink(
            source_claim_id=supplement.item_graph_ids["claim:paint"], target_claim_id=claims[1],
            source_document_id=documents[0], target_document_id=documents[1],
            relation_type=LinkType.IN_TENSION,
            source_evidence=[EvidenceReference(quote="Quiero pintar.")],
            target_evidence=[EvidenceReference(quote="Nota 1")], similarity=0.7, profile="link-v2",
        )
        with pytest.raises(GraphPersistenceError):
            store.persist_link_analysis(source, supplement, [
                new_link, new_link.model_copy(update={"target_claim_id": "does-not-exist"}),
            ])
        assert not store.supplemental_items_persisted(supplement)
        assert new_link.source_claim_id not in {
            item["id"] for item in store.existing_document_items(documents[0])
        }
        store.persist_link_analysis(source, supplement, [new_link])
        store.persist_link_analysis(source, supplement, [new_link])
        assert store.supplemental_items_persisted(supplement)
        assert str(supplement.id) not in store.ready_extraction_ids({str(supplement.id): 1}, spec)

        class TestEmbeddings:
            def embed(self, texts):
                from src.embeddings.contracts import EmbeddingVector
                return [EmbeddingVector(vector=[1.0, 0.0, 0.0], spec=spec) for _ in texts]

        assert EmbedClaims(TestEmbeddings(), store).execute(source, supplement) == 1
        assert store.ready_extraction_ids({str(supplement.id): 1}, spec) == {str(supplement.id)}
        assert len(store.get_link_neighborhood(
            documents[0], relation_type=LinkType.IN_TENSION
        ).links) == 1
        reused = prepare_supplement(source, parent, additions,
                                   store.existing_document_items(documents[0]),
                                   provider="test", model="test")
        assert reused is not None
        assert set(reused.reused_item_keys) == {"claim:paint", "entity:painting"}
        before = store.existing_document_items(documents[0])
        store.persist_link_analysis(source, reused, [new_link])
        assert store.existing_document_items(documents[0]) == before
    finally:
        admin._request("/api/v1/server", method="POST",
                       payload={"command": f"drop database {database}"})
