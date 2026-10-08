"""Emotion-owned schema and persistence against a disposable ArcadeDB database."""

import os
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest

from src.domain.documents import NewDocument, build_document
from src.extractors.artifacts import LayerArtifacts
from src.extractors.contracts import ExtractorProfile, ProviderMetadata
from src.extractors.emotion_evidence import EmotionResponse
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
        self.payload = EmotionResponse(
            emotions=[
                {"label": "alegría", "quotes": ["Hoy siento alegría."]},
                {"label": "miedo", "quotes": ["Después sentí miedo."]},
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
        assert node["profile_id"] == "emotions/v2" and node["profile_hash"] == output.profile_hash
        assert not {"quote", "start_char", "end_char"} & node.keys()
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
    evidence = (await client.query("SELECT FROM HAS_EMOTION"))["result"]
    for edge in evidence:
        assert document.content[edge["start_char"] : edge["end_char"]] == edge["quote"]
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
    provider.payload = Emotions(emotions=[])
    empty = await extractor.extract(document, dry_run=False)
    await extractor.persist(empty)
    assert not (await client.query("SELECT FROM Emotion"))["result"]
    provider.payload = Emotions(emotions=[{"label": "miedo", "quotes": ["Después sentí miedo."]}])
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


@pytest.mark.parametrize("failure", ["node", "edge", "evidence"])
async def test_partial_layer_write_rolls_back_and_retry_reuses_artifact(layer_database, failure):
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
                        if failure == "node" and "MERGE (emotion:Emotion" in statement:
                            return {"result": []}
                        if "MERGE (run)-[edge:HAS_EMOTION " in statement:
                            if failure == "edge":
                                return {"result": []}
                            if failure == "evidence":
                                statement = statement.replace(
                                    "edge.quote=$quote", "edge.quote='wrong'"
                                )
                        return await real.command(statement, *args, **kwargs)

                    async def query(self, *args, **kwargs):
                        return await real.query(*args, **kwargs)

                yield Transaction()

    extractor.graph = PartialWrite()
    verification = "nodes" if failure == "node" else "edges"
    with pytest.raises(ValueError, match=f"{verification}_verification_failed"):
        await extractor.persist(output)
    assert not (await client.query("SELECT FROM EmotionExtraction"))["result"]
    assert not (await client.query("SELECT FROM HAS_EMOTION_EXTRACTION"))["result"]
    extractor.graph = client
    await extractor.persist(output)
    assert provider.calls == 1
    assert len((await client.query("SELECT FROM Emotion"))["result"]) == 2


async def test_repeated_emotion_has_one_node_multiple_edges_and_independent_documents(
    layer_database,
):
    extractor, _, client, provider, graph = layer_database
    quotes = ["Me dio miedo salir.", "Al volver sentí miedo.", "Todavía tengo miedo."]
    document = build_document(NewDocument(content=" 🫥 ".join(quotes)))
    await extractor.documents.save(document)
    await graph.persist_document(document)
    provider.payload = Emotions(emotions=[{"label": "miedo", "quotes": quotes}])
    output = await extractor.extract(document, dry_run=False)
    await extractor.persist(output)
    assert provider.calls == 1
    result = await graph.get_extraction_graph(str(document.id))
    emotions = [node for node in result.nodes if node.type == "Emotion"]
    assert len(emotions) == 1 and emotions[0].quote is None
    assert len(result.edges) == 3 and len({edge.id for edge in result.edges}) == 3
    assert {edge.target for edge in result.edges} == {emotions[0].id}
    assert {edge.quote for edge in result.edges} == set(quotes)
    for edge in result.edges:
        assert document.content[edge.start_char : edge.end_char] == edge.quote
    second_run = await extractor.extract(document, dry_run=False)
    assert second_run.run_id != output.run_id
    result = await graph.get_extraction_graph(str(document.id))
    assert len(result.nodes) == 3 and len(result.edges) == 6
    other = build_document(NewDocument(content=document.content))
    await extractor.documents.save(other)
    await graph.persist_document(other)
    await extractor.extract(other, dry_run=False)
    other_graph = await graph.get_extraction_graph(str(other.id))
    assert len(other_graph.nodes) == 2 and len(other_graph.edges) == 3
    assert {n.id for n in other_graph.nodes}.isdisjoint({n.id for n in result.nodes})
    await graph.delete_document(str(document.id))
    assert await graph.get_extraction_graph(str(other.id)) == other_graph
    assert (await extractor.documents.get(other.id)).content == other.content


async def test_corrected_emotions_persist_only_valid_quotes_and_keep_warnings(layer_database):
    extractor, document, client, provider, graph = layer_database
    provider.payload = EmotionResponse(
        emotions=[
            {"label": "alegría", "quotes": ["", "Hoy siento alegría."]},
            {"label": "miedo", "quotes": ["Una frase inventada."]},
            {"label": "tristeza", "quotes": [" "]},
        ]
    )
    calls = []

    async def correct(note, profile, previous, issues):
        calls.append(issues)
        assert note == document
        return EmotionResponse(
            emotions=[
                {"label": "alegría", "quotes": ["Hoy siento alegría."]},
                {"label": "miedo", "quotes": ["Después sentí miedo.", ""]},
            ]
        ), ProviderMetadata(provider="fake", model="test", response_id="corrected")

    provider.correct = correct
    output = await extractor.extract(document, dry_run=False)
    await extractor.persist(output)
    assert provider.calls == 1 and len(calls) == 1
    assert calls[0][0].code == "emotion_quote_not_found"
    assert len(output.payload["warnings"]) == 4
    assert output.provider.response_id == "corrected"
    run = (await client.query("SELECT artifact_json FROM EmotionExtraction"))["result"]
    assert run == [{"artifact_json": output.model_dump_json()}]
    result = await graph.get_extraction_graph(str(document.id))
    assert len(result.nodes) == 3 and len(result.edges) == 2
    assert {edge.quote for edge in result.edges} == {"Hoy siento alegría.", "Después sentí miedo."}
    assert (await extractor.documents.get(document.id)).content == document.content
