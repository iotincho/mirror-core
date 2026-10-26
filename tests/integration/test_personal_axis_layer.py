import os
from contextlib import asynccontextmanager
from uuid import uuid4, uuid5

import pytest
from test_emotion_layer import layer_database  # noqa: F401

from src.adapters.storage.arcadedb.personal_axes import ArcadeDBAxisStore
from src.core.extractors.personal_axes.models import AxisSpecification, FindingsResponse
from src.use_cases.extraction.personal_axis import PersonalAxisExtractor

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("EMOTIONS_TEST_ARCADEDB_URL"), reason="requires isolated ArcadeDB"
    ),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_atomic_axis_replacement_keeps_other_axes_and_emotions(layer_database):  # noqa: F811
    emotions, document, client, emotion_provider, graph = layer_database
    await emotions.extract(document, dry_run=False)

    class Provider:
        calls = 0
        empty = False

        async def extract(self, document, profile):
            self.calls += 1
            return FindingsResponse(
                findings=[]
                if self.empty
                else [
                    {
                        "title": "Un hallazgo",
                        "content": "Contenido desarrollado de la idea.",
                        "evidence": [{"quote": "Hoy siento alegría."}],
                        "tags": ["crear"],
                    }
                ]
            ), None

    provider = Provider()
    spec = AxisSpecification(profile=emotions.profile, model="test")
    axis_a, axis_b = uuid4(), uuid4()
    a = PersonalAxisExtractor(
        emotions.documents,
        emotions.artifacts,
        spec,
        provider,
        ArcadeDBAxisStore(client),
        axis_a,
        uuid4(),
    )
    b = PersonalAxisExtractor(
        emotions.documents,
        emotions.artifacts,
        spec,
        provider,
        ArcadeDBAxisStore(client),
        axis_b,
        uuid4(),
    )
    first = await a.extract(document, dry_run=False)
    await b.extract(document, dry_run=False)
    assert len((await client.query("SELECT FROM AxisFinding"))["result"]) == 2
    assert len((await client.query("SELECT FROM Emotion"))["result"]) == 2
    assert (await graph.get_extraction_graph(str(document.id))).layers == ["emotions"]
    provider.empty = True
    replacement = await a.extract(document)

    @asynccontextmanager
    async def interrupted():
        async with client.transaction() as tx:
            yield tx
            raise ConnectionError("synthetic failure before commit")

    class FailingClient:
        command = client.command
        transaction = staticmethod(interrupted)

    a.store = ArcadeDBAxisStore(FailingClient())
    with pytest.raises(ConnectionError):
        await a.persist(replacement)
    assert len((await client.query("SELECT FROM AxisFinding"))["result"]) == 2
    a.store = ArcadeDBAxisStore(client)
    a.provider = None
    await a.persist(replacement)
    await a.persist(replacement)
    findings = (await client.query("SELECT FROM AxisFinding"))["result"]
    assert len(findings) == 1 and findings[0]["axis_id"] == str(axis_b)
    assert (
        await client.query("SELECT FROM AxisExtraction WHERE id=:id", {"id": str(first.run_id)})
    )["result"] == []
    assert provider.calls == 3
    assert emotion_provider.calls == 1
    await graph.delete_document(str(document.id))
    assert (await client.query("SELECT FROM AxisFinding"))["result"] == []
    assert (await client.query("SELECT FROM AxisExtraction"))["result"] == []


async def test_multiple_quotes_are_edges_and_replay_repairs_early_node_evidence(
    layer_database,  # noqa: F811
):
    base, document, client, _, _ = layer_database
    quotes = ["Hoy siento alegría.", "Después sentí miedo."]

    class Provider:
        calls = 0

        async def extract(self, document, profile):
            self.calls += 1
            return FindingsResponse(
                findings=[
                    {
                        "title": "Un hallazgo",
                        "content": "Una idea con dos fragmentos de apoyo.",
                        "evidence": [{"quote": quote} for quote in quotes],
                        "tags": ["idea"],
                    }
                ]
            ), None

    provider = Provider()
    axis_id, version_id = uuid4(), uuid4()
    extractor = PersonalAxisExtractor(
        base.documents,
        base.artifacts,
        AxisSpecification(profile=base.profile, model="test"),
        provider,
        ArcadeDBAxisStore(client),
        axis_id,
        version_id,
    )
    output = await extractor.extract(document, dry_run=False)
    forbidden = {"quote", "start_char", "end_char", "evidence", "evidence_json"}

    async def verify():
        findings = (await client.query("SELECT FROM AxisFinding"))["result"]
        assert len(findings) == 1
        assert not forbidden & findings[0].keys()
        assert findings[0]["content"] == "Una idea con dos fragmentos de apoyo."
        edges = (await client.query("SELECT FROM HAS_AXIS_FINDING"))["result"]
        assert len(edges) == len({edge["id"] for edge in edges}) == 2
        assert {edge["quote"] for edge in edges} == set(quotes)
        for edge in edges:
            assert document.content[edge["start_char"] : edge["end_char"]] == edge["quote"]
            assert edge["axis_id"] == str(axis_id) and edge["version_id"] == str(version_id)
            assert edge["document_id"] == str(document.id) and edge["run_id"] == str(output.run_id)
        return findings[0]["id"], {edge["id"] for edge in edges}

    identity = await verify()
    extractor.provider = None
    await extractor.persist(output)
    assert await verify() == identity

    # Simulate the pre-correction representation of the same already saved artifact.
    params = {
        "run_id": str(output.run_id),
        "finding_id": identity[0],
        "edge_id": str(uuid5(output.run_id, "finding-edge:0")),
    }
    async with client.transaction() as tx:
        await tx.command(
            "MATCH (r:AxisExtraction {id:$run_id})-[e:HAS_AXIS_FINDING]->() DELETE e",
            params,
            language="cypher",
        )
        await tx.command(
            """
MATCH (r:AxisExtraction {id:$run_id}), (n:AxisFinding {id:$finding_id})
SET n.evidence_json='legacy-evidence'
MERGE (r)-[e:HAS_AXIS_FINDING {id:$edge_id}]->(n)
""",
            params,
            language="cypher",
        )
    await extractor.persist(output)
    assert await verify() == identity
    assert provider.calls == 1
