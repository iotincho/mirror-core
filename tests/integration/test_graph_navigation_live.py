# ruff: noqa: F811
"""Navigate original document vertices without retired extraction schemas."""

import json
import os

import pytest
from test_emotion_layer import layer_database  # noqa: F401, F811

from src.domain.documents import NewDocument, build_document
from src.graph.contracts import LinkType

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("EMOTIONS_TEST_ARCADEDB_URL"), reason="requires isolated ArcadeDB"
    ),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_new_database_and_emotion_layer_return_empty_neighborhood(layer_database):
    extractor, document, _, _, graph = layer_database
    assert (await graph.get_link_neighborhood(str(document.id))).total_neighbors == 0
    await extractor.extract(document, dry_run=False)
    result = await graph.get_link_neighborhood(str(document.id))
    assert result.neighbor_ids == [] and result.links == []


async def test_graph_reads_generic_endpoints_paging_filters_and_direction(layer_database):
    _, document, client, _, graph = layer_database
    neighbors = [build_document(NewDocument(content=f"Nota {i}")) for i in range(2)]
    for neighbor in neighbors:
        await graph.persist_document(neighbor)
    await client.command("CREATE EDGE TYPE CROSS_DOCUMENT_LINK")

    async def edge(source, target, kind, link_id):
        evidence = {"source": [{"quote": source.content}], "target": [{"quote": target.content}]}
        await client.command(
            """
        MATCH (source:Document {id: $source}), (target:Document {id: $target})
        CREATE (source)-[link:CROSS_DOCUMENT_LINK]->(target)
        SET link.link_id=$link_id, link.source_document_id=$source,
            link.target_document_id=$target, link.relation_type=$kind,
            link.profile=$profile, link.evidence_json=$evidence
        """,
            {
                "source": str(source.id),
                "target": str(target.id),
                "link_id": link_id,
                "kind": kind,
                "profile": "presentation-test",
                "evidence": json.dumps(evidence),
            },
            language="cypher",
        )

    await edge(document, neighbors[0], "SAME_REFERENT", "symmetric")
    await edge(neighbors[0], document, "SAME_REFERENT", "symmetric")
    await edge(neighbors[1], document, "REVISITS", "directed")
    result = await graph.get_link_neighborhood(str(document.id))
    assert result.total_neighbors == 2
    assert set(result.neighbor_ids) == {str(d.id) for d in neighbors}
    assert {link.link_id for link in result.links} == {"symmetric", "directed"}
    directed = next(link for link in result.links if link.link_id == "directed")
    assert directed.source_document_id == str(neighbors[1].id)
    assert directed.target_document_id == str(document.id)
    assert directed.source_evidence[0].quote == neighbors[1].content
    first = await graph.get_link_neighborhood(str(document.id), limit=1)
    assert first.total_neighbors == 2 and first.next_offset == 1
    second = await graph.get_link_neighborhood(str(document.id), offset=1, limit=1)
    assert second.next_offset is None and len(second.neighbor_ids) == 1
    assert set(first.neighbor_ids + second.neighbor_ids) == set(result.neighbor_ids)
    filtered = await graph.get_link_neighborhood(str(document.id), relation_type=LinkType.REVISITS)
    assert filtered.neighbor_ids == [str(neighbors[1].id)]
    assert len(filtered.links) == 1 and filtered.links[0].link_id == "directed"
    # The same directed edge remains directed when navigating from its source.
    from_source = await graph.get_link_neighborhood(str(neighbors[1].id))
    assert from_source.links[0].source_document_id == str(neighbors[1].id)
    types = (await client.query("SELECT name FROM schema:types"))["result"]
    assert not any(row["name"] == "Claim" for row in types)
