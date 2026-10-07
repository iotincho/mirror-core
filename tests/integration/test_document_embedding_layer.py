"""Native vector indexing, replacement rollback, deduplication and document deletion."""

import os
from uuid import uuid4

import httpx
import pytest

from src.domain.documents import NewDocument, build_document
from src.extractors.artifacts import LayerArtifacts
from src.extractors.document_embedding_store import ArcadeDBDocumentEmbeddingStore
from src.extractors.document_embeddings import (
    DocumentEmbeddingExtractor,
    EmbeddingConfiguration,
    Segmentation,
)
from src.graph.arcadedb.client import AsyncArcadeDBHTTPClient
from src.graph.arcadedb.schema import schema_statements
from src.graph.arcadedb.store import ArcadeDBGraphStore
from src.services.document_store import FileDocumentStore

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("EMBEDDINGS_TEST_ARCADEDB_URL"), reason="requires isolated ArcadeDB"
    ),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Provider:
    def __init__(self):
        self.calls = 0
        self.vector = [1.0, 0.0, 0.0]

    async def segment(self, blocks, profile, target):
        return Segmentation(sections=[])

    async def embed(self, texts, configuration):
        self.calls += 1
        return [self.vector for text in texts]


@pytest.fixture
async def layer(tmp_path):
    url, password = (
        os.environ["EMBEDDINGS_TEST_ARCADEDB_URL"],
        os.environ["EMBEDDINGS_TEST_ARCADEDB_PASSWORD"],
    )
    name = "embedding_test_" + uuid4().hex
    async with httpx.AsyncClient(base_url=url, auth=("root", password)) as admin:
        (
            await admin.post("/api/v1/server", json={"command": f"create database {name}"})
        ).raise_for_status()
        client = AsyncArcadeDBHTTPClient(url, name, "root", password)
        graph = ArcadeDBGraphStore(url, name, "root", password, client=client)
        try:
            for statement in schema_statements():
                await client.command(statement)
            documents = FileDocumentStore(tmp_path / "documents")
            document = build_document(
                NewDocument(content="Hoy siento alegría. Después sentí miedo.\n" * 20)
            )
            await documents.save(document)
            await graph.persist_document(document)
            provider = Provider()
            config = EmbeddingConfiguration(
                segmentation_model="test",
                dimensions=3,
                segmentation_threshold=100,
                section_max_tokens=64,
                section_target_tokens=32,
            )
            store = ArcadeDBDocumentEmbeddingStore(client)
            extractor = DocumentEmbeddingExtractor(
                documents, LayerArtifacts(tmp_path / "layers"), store, config, provider
            )
            yield document, extractor, client, graph, provider
        finally:
            await graph.close()
            (
                await admin.post("/api/v1/server", json={"command": f"drop database {name}"})
            ).raise_for_status()


async def test_native_index_dry_run_replay_skip_search_and_delete(layer):
    document, extractor, client, graph, provider = layer
    output = await extractor.extract(document)
    assert not await extractor.store.has_schema("DocumentSemanticIndex")
    await extractor.persist(output)
    await extractor.persist(output)
    assert provider.calls == 1
    await extractor.extract(document, dry_run=False)
    assert provider.calls == 1
    sections = (await client.query("SELECT FROM DocumentEmbeddingSection"))["result"]
    assert len(sections) == len(output.payload["sections"])
    results = await extractor.store.search([1, 0, 0], extractor.configuration)
    assert len(results) == 1
    assert results[0].document_id == document.id
    assert results[0].distance == pytest.approx(0, abs=1e-5)
    assert len(results[0].sections) == len(sections)
    visible = await graph.get_extraction_graph(str(document.id))
    assert visible.layers == [] and visible.edges == [] and len(visible.nodes) == 1
    await graph.delete_document(str(document.id))
    assert await extractor.store.search([1, 0, 0], extractor.configuration) == []
    assert await extractor.store.existing(document.id) is None


async def test_force_replacement_is_atomic_and_idempotent(layer, monkeypatch):
    document, extractor, client, _, provider = layer
    old = await extractor.extract(document, dry_run=False)
    extractor.force = True
    provider.vector = [0, 1, 0]
    new = await extractor.extract(document)
    original_verify = extractor.store.verify

    async def fail(*args):
        raise ValueError("injected_failure")

    monkeypatch.setattr(extractor.store, "verify", fail)
    with pytest.raises(ValueError, match="injected_failure"):
        await extractor.persist(new)
    assert (await extractor.store.existing(document.id)).run_id == old.run_id
    monkeypatch.setattr(extractor.store, "verify", original_verify)
    await extractor.persist(new)
    await extractor.persist(new)
    assert (await extractor.store.existing(document.id)).run_id == new.run_id
    sections = (await client.query("SELECT FROM DocumentEmbeddingSection"))["result"]
    assert len(sections) == len(new.payload["sections"])
    assert all(section["run_id"] == str(new.run_id) for section in sections)
    assert (await extractor.store.search([0, 1, 0], extractor.configuration))[
        0
    ].distance == pytest.approx(0)


async def test_search_returns_unique_documents_and_expands_candidates(layer):
    document, extractor, _, graph, provider = layer
    await extractor.extract(document, dry_run=False)
    other = build_document(NewDocument(content="Una nota diferente."))
    await extractor.documents.save(other)
    await graph.persist_document(other)
    provider.vector = [0, 1, 0]
    await extractor.extract(other, dry_run=False)
    results = await extractor.store.search([1, 0, 0], extractor.configuration, limit=2)
    assert [match.document_id for match in results] == [document.id, other.id]
    incompatible = extractor.configuration.model_copy(update={"dimensions": 2})
    assert await extractor.store.search([1, 0], incompatible) == []
