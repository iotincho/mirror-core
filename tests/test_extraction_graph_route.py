"""Layer graph response, source scope and safe errors."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from src.auth.session import require_authenticated
from src.dependencies import get_document_store, get_graph_store
from src.domain.documents import NewDocument, build_document
from src.graph.contracts import ExtractionGraph, GraphEdge, GraphNode
from src.main import app
from src.services.document_store import DocumentNotFoundError
from src.services.graph_store import GraphPersistenceError


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def api():
    document = build_document(NewDocument(content="Hoy siento alegría."))
    root = f"Document:{document.id}"
    documents = SimpleNamespace(get=AsyncMock(return_value=document))
    graph = SimpleNamespace(
        get_extraction_graph=AsyncMock(
            return_value=ExtractionGraph(
                document_id=str(document.id),
                root_id=root,
                layers=[],
                nodes=[
                    GraphNode(id=root, type="Document", label="Nota", document_id=str(document.id))
                ],
                edges=[],
            )
        )
    )
    app.dependency_overrides.update(
        {
            require_authenticated: lambda: "owner",
            get_document_store: lambda: documents,
            get_graph_store: lambda: graph,
        }
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            yield client, document, documents, graph
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_graph_route_returns_source_label_and_forwards_layer(api):
    client, document, documents, graph = api
    response = await client.get(f"/documents/{document.id}/graph", params={"layer": "emotions"})
    assert response.status_code == 200
    assert response.json()["nodes"][0]["label"] == document.content
    assert response.json()["root_id"] == f"Document:{document.id}"
    documents.get.assert_awaited_once_with(document.id)
    graph.get_extraction_graph.assert_awaited_once_with(str(document.id), layer="emotions")


@pytest.mark.anyio
async def test_missing_workspace_document_does_not_query_graph(api):
    client, document, documents, graph = api
    documents.get.side_effect = DocumentNotFoundError("missing")
    assert (await client.get(f"/documents/{document.id}/graph")).status_code == 404
    graph.get_extraction_graph.assert_not_awaited()


@pytest.mark.anyio
async def test_graph_failure_is_not_a_successful_empty_graph(api):
    client, document, _, graph = api
    graph.get_extraction_graph.side_effect = GraphPersistenceError("incomplete")
    assert (await client.get(f"/documents/{document.id}/graph")).status_code == 502


@pytest.mark.anyio
async def test_invalid_document_id_is_rejected(api):
    client, _, _, graph = api
    assert (await client.get(f"/documents/{uuid4()}bad/graph")).status_code == 422
    graph.get_extraction_graph.assert_not_awaited()


@pytest.mark.anyio
async def test_graph_route_keeps_multiple_evidence_edges_to_one_emotion(api):
    client, document, _, graph = api
    result = graph.get_extraction_graph.return_value
    emotion_id = "Emotion:joy"
    result.nodes.append(GraphNode(id=emotion_id, type="Emotion", label="alegría", layer="emotions"))
    result.edges = [
        GraphEdge(
            id=f"HAS_EMOTION:{index}",
            source=result.root_id,
            target=emotion_id,
            type="HAS_EMOTION",
            layer="emotions",
            quote=quote,
            start_char=start,
            end_char=start + len(quote),
        )
        for index, (quote, start) in enumerate([("Hoy", 0), ("alegría", 11)])
    ]
    response = await client.get(f"/documents/{document.id}/graph")
    assert response.status_code == 200
    data = response.json()
    assert len(data["nodes"]) == 2 and len(data["edges"]) == 2
    assert data["nodes"][1]["quote"] is None
    assert {edge["target"] for edge in data["edges"]} == {emotion_id}
    assert data["edges"] == [edge.model_dump() for edge in result.edges]
