"""Read-only normalized emotion exploration and exact projected hop boundaries."""

# ruff: noqa: F811

import os

import pytest
from test_emotion_layer import layer_database  # noqa: F401

from src.domain.documents import NewDocument, build_document
from src.extractors.emotion_evidence import EmotionResponse
from src.graph.emotion_exploration import group_id
from src.services.graph_store import EmotionNotFoundError

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("EMOTIONS_TEST_ARCADEDB_URL"), reason="requires isolated ArcadeDB"
    ),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_empty_catalog_never_creates_extractor_schema(layer_database):
    _, document, client, _, graph = layer_database
    before = (await client.query("SELECT name FROM schema:types"))["result"]
    catalog = await graph.list_emotions()
    assert catalog.model_dump() == {"emotions": [], "total": 0, "next_offset": None}
    with pytest.raises(EmotionNotFoundError):
        await graph.explore_emotion("miedo")
    neighborhood = await graph.explore_document_emotions(str(document.id))
    assert neighborhood.root_id == f"Document:{document.id}"
    assert len(neighborhood.nodes) == 1 and not neighborhood.edges
    assert (await client.query("SELECT name FROM schema:types"))["result"] == before


async def test_levels_group_labels_deduplicate_runs_and_preserve_evidence(layer_database):
    extractor, _, client, provider, graph = layer_database

    async def add(title, content, emotions):
        document = build_document(NewDocument(content=content, metadata={"title": title}))
        await extractor.documents.save(document)
        await graph.persist_document(document)
        provider.payload = EmotionResponse(emotions=emotions)
        await extractor.extract(document, dry_run=False)
        return document

    a = await add(
        "Nota A",
        "Me dio miedo. Después sentí miedo. También sentí alegría.",
        [
            {"label": "Miedo", "quotes": ["Me dio miedo.", "Después sentí miedo."]},
            {"label": "alegría", "quotes": ["También sentí alegría."]},
        ],
    )
    # Another execution has independent source nodes but must not add notes or repeat quotes.
    await extractor.extract(a, dry_run=False)
    b = await add(
        "Nota B",
        "Tengo miedo de salir.",
        [
            {"label": "MIEDO", "quotes": ["Tengo miedo de salir."]},
        ],
    )
    c = await add(
        "Nota C",
        "Siento alegría. Estoy en calma.",
        [
            {"label": "alegri\u0301a", "quotes": ["Siento alegría."]},
            {"label": "calma", "quotes": ["Estoy en calma."]},
        ],
    )
    unrelated = await add(
        "Nota D",
        "Estoy triste.",
        [
            {"label": "tristeza", "quotes": ["Estoy triste."]},
        ],
    )
    synonym = await add(
        "Nota E",
        "Sentí temor.",
        [
            {"label": "temor", "quotes": ["Sentí temor."]},
        ],
    )
    counts_before = (await client.query("SELECT count(*) AS total FROM Emotion"))["result"]
    catalog = await graph.list_emotions(limit=2)
    assert catalog.total == 5 and catalog.next_offset == 2
    assert {item.key: item.document_count for item in catalog.emotions} == {
        "miedo": 2,
        "alegría": 2,
    }
    remaining = await graph.list_emotions(offset=2, limit=10)
    assert remaining.next_offset is None and {item.key for item in remaining.emotions} == {
        "calma",
        "tristeza",
        "temor",
    }

    l1 = await graph.explore_emotion(" MIEDO ", depth=1)
    assert l1.root_id == group_id("miedo")
    assert len(l1.nodes) == 3 and len(l1.edges) == 2 and not l1.truncated
    assert {node.document_id for node in l1.nodes if node.type == "Document"} == {
        str(a.id),
        str(b.id),
    }
    a_edge = next(edge for edge in l1.edges if edge.source == f"Document:{a.id}")
    assert [item.quote for item in a_edge.evidence] == ["Me dio miedo.", "Después sentí miedo."]
    assert all(len(item.sources) == 2 for item in a_edge.evidence)
    assert all(a.content[item.start_char : item.end_char] == item.quote for item in a_edge.evidence)
    # Follow a single thread past the old L3 boundary without loading unrelated edges.
    centered_a = await graph.explore_document_emotions(str(a.id))
    assert centered_a.root_id == f"Document:{a.id}" and centered_a.document_id == str(a.id)
    assert {n.label for n in centered_a.nodes if n.type == "EmotionGroup"} == {"miedo", "alegría"}
    assert len(centered_a.nodes) == 3 and len(centered_a.edges) == 2
    assert all(e.source == centered_a.root_id for e in centered_a.edges)
    assert next(e for e in centered_a.edges if e.target == group_id("miedo")) == a_edge
    centered_joy = await graph.explore_emotion("alegría")
    assert {n.document_id for n in centered_joy.nodes if n.type == "Document"} == {
        str(a.id),
        str(c.id),
    }
    centered_c = await graph.explore_document_emotions(str(c.id))
    assert {n.label for n in centered_c.nodes if n.type == "EmotionGroup"} == {"alegría", "calma"}
    assert len(centered_c.edges) == 2 and all(
        e.source == centered_c.root_id for e in centered_c.edges
    )
    limited_note = await graph.explore_document_emotions(str(a.id), limit=2)
    assert len(limited_note.nodes) == 2 and limited_note.truncated
    assert len(limited_note.edges) == 1
    l2 = await graph.explore_emotion("miedo", depth=2)
    assert len(l2.nodes) == 4 and len(l2.edges) == 3
    assert {node.label for node in l2.nodes if node.type == "EmotionGroup"} == {"miedo", "alegría"}
    l3 = await graph.explore_emotion("miedo", depth=3)
    assert len(l3.nodes) == 5 and len(l3.edges) == 4
    assert {node.document_id for node in l3.nodes if node.type == "Document"} == {
        str(a.id),
        str(b.id),
        str(c.id),
    }
    assert all(node.document_id not in {str(unrelated.id), str(synonym.id)} for node in l3.nodes)
    assert not any(node.label == "calma" for node in l3.nodes)  # Would require L4.
    assert all(
        edge.source in {node.id for node in l3.nodes}
        and edge.target in {node.id for node in l3.nodes}
        for edge in l3.edges
    )
    limited = await graph.explore_emotion("miedo", depth=3, limit=2)
    assert len(limited.nodes) == 2 and limited.truncated and limited.next_limit == 4
    expanded = await graph.explore_emotion("miedo", depth=3, limit=limited.next_limit)
    assert {node.id for node in limited.nodes}.issubset({node.id for node in expanded.nodes})
    assert (await client.query("SELECT count(*) AS total FROM Emotion"))["result"] == counts_before
    await graph.delete_document(str(b.id))
    after = await graph.explore_emotion("miedo")
    assert len(after.nodes) == 2 and len(after.edges) == 1
    assert next(node for node in after.nodes if node.type == "EmotionGroup").document_count == 1
