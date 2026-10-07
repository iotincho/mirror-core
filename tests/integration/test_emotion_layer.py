"""Emotion-owned schema and persistence against a disposable ArcadeDB database."""

import os
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest

from src.domain.documents import NewDocument, build_document
from src.extractors.artifacts import LayerArtifacts
from src.extractors.contracts import ExtractorProfile, ProviderMetadata
from src.extractors.emotions import EmotionExtractor, Emotions
from src.graph.arcadedb.client import AsyncArcadeDBHTTPClient
from src.graph.arcadedb.schema import schema_statements
from src.graph.arcadedb.store import ArcadeDBGraphStore
from src.services.document_store import FileDocumentStore

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("EMOTIONS_TEST_ARCADEDB_URL"), reason="requires isolated ArcadeDB"
    ),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeProvider:
    provider_name, model_name = "fake", "test"

    def __init__(self):
        self.calls = 0
        self.payload = Emotions(
            occurrences=[
                {"label": "alegría", "quote": "Hoy siento alegría."},
                {"label": "miedo", "quote": "Después sentí miedo."},
            ]
        )

    async def extract(self, document, profile):
        self.calls += 1
        return self.payload, ProviderMetadata(provider="fake", model="test")


@pytest.fixture
async def layer_database(tmp_path):
    url = os.environ["EMOTIONS_TEST_ARCADEDB_URL"]
    password = os.environ["EMOTIONS_TEST_ARCADEDB_PASSWORD"]
    name = f"emotion_test_{uuid4().hex}"
    async with httpx.AsyncClient(base_url=url, auth=("root", password)) as admin:
        (
            await admin.post("/api/v1/server", json={"command": f"create database {name}"})
        ).raise_for_status()
        client = AsyncArcadeDBHTTPClient(url, name, "root", password)
        graph = ArcadeDBGraphStore(url, name, "root", password, client=client)
        try:
            for statement in schema_statements():
                await client.command(statement)
            document = build_document(
                NewDocument(content="Hoy siento alegría. Después sentí miedo.")
            )
            documents = FileDocumentStore(tmp_path / "documents")
            await documents.save(document)
            await graph.persist_document(document)
            artifacts = LayerArtifacts(tmp_path / "layers")
            provider = FakeProvider()
            extractor = EmotionExtractor(documents, artifacts, client, provider)
            yield extractor, document, client, provider, graph
        finally:
            await graph.close()
            (
                await admin.post("/api/v1/server", json={"command": f"drop database {name}"})
            ).raise_for_status()


async def test_dry_run_deferred_write_replay_tags_evidence_and_document_deletion(layer_database):
    extractor, document, client, provider, graph = layer_database
    output = await extractor.extract(document)
    types = (await client.query("SELECT name FROM schema:types"))["result"]
    assert not any(row["name"] == "Emotion" for row in types)
    # Persistence is independent of the current prompt and has no provider dependency.
    later = EmotionExtractor(
        extractor.documents,
        extractor.artifacts,
        client,
        profile=ExtractorProfile(id="emotions/v2", instructions="Changed prompt"),
    )
    await later.persist(output)
    await later.persist(output)
    assert provider.calls == 1
    nodes = (await client.query("SELECT FROM Emotion"))["result"]
    assert len(nodes) == 2
    for node in nodes:
        assert node["layer"] == "emotions" and node["document_id"] == str(document.id)
        assert node["profile_id"] == "emotions/v1" and node["profile_hash"] == output.profile_hash
        assert document.content[node["start_char"] : node["end_char"]] == node["quote"]
    for name, count in [
        ("EmotionExtraction", 1),
        ("HAS_EMOTION_EXTRACTION", 1),
        ("HAS_EMOTION", 2),
    ]:
        rows = (await client.query(f"SELECT FROM {name}"))["result"]
        assert len(rows) == count
        assert all(
            row["layer"] == "emotions" and row["run_id"] == str(output.run_id) for row in rows
        )
    assert (await client.query("SELECT content FROM Document"))["result"] == [
        {"content": document.content}
    ]
    await graph.delete_document(str(document.id))
    for name in [
        "Document",
        "Emotion",
        "EmotionExtraction",
        "HAS_EMOTION",
        "HAS_EMOTION_EXTRACTION",
    ]:
        assert (await client.query(f"SELECT FROM {name}"))["result"] == []


async def test_empty_result_is_persisted_and_runs_are_independent(layer_database):
    extractor, document, client, provider, _ = layer_database
    provider.payload = Emotions(occurrences=[])
    empty = await extractor.extract(document, dry_run=False)
    await extractor.persist(empty)
    assert not (await client.query("SELECT FROM Emotion"))["result"]
    provider.payload = Emotions(occurrences=[{"label": "miedo", "quote": "Después sentí miedo."}])
    other = await extractor.extract(document, dry_run=False)
    assert other.run_id != empty.run_id
    assert len((await client.query("SELECT FROM EmotionExtraction"))["result"]) == 2
    assert len((await client.query("SELECT FROM Emotion"))["result"]) == 1


async def test_missing_graph_source_does_not_report_success(layer_database):
    extractor, document, client, _, graph = layer_database
    output = await extractor.extract(document)
    await graph.delete_document(str(document.id))
    with pytest.raises(ValueError, match="source_missing_in_graph"):
        await extractor.persist(output)
    assert not (await client.query("SELECT FROM EmotionExtraction"))["result"]


async def test_partial_layer_write_rolls_back_and_retry_reuses_artifact(layer_database):
    extractor, document, client, provider, _ = layer_database
    output = await extractor.extract(document)

    class PartialWrite:
        async def command(self, *args, **kwargs):
            return await client.command(*args, **kwargs)

        @asynccontextmanager
        async def transaction(self):
            async with client.transaction() as real:

                class Transaction:
                    async def command(self, statement, *args, **kwargs):
                        if "MERGE (emotion:Emotion" in statement:
                            return {"result": []}
                        return await real.command(statement, *args, **kwargs)

                    async def query(self, *args, **kwargs):
                        return await real.query(*args, **kwargs)

                yield Transaction()

    extractor.graph = PartialWrite()
    with pytest.raises(ValueError, match="nodes_verification_failed"):
        await extractor.persist(output)
    assert not (await client.query("SELECT FROM EmotionExtraction"))["result"]
    assert not (await client.query("SELECT FROM HAS_EMOTION_EXTRACTION"))["result"]
    extractor.graph = client
    await extractor.persist(output)
    assert provider.calls == 1
    assert len((await client.query("SELECT FROM Emotion"))["result"]) == 2
