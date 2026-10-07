"""Read-only graph contract, paging and document write verification."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from src.auth.session import require_authenticated
from src.dependencies import get_document_store, get_graph_store
from src.domain.documents import NewDocument, build_document
from src.graph.arcadedb.store import ArcadeDBGraphStore
from src.graph.contracts import LinkNeighborhood, LinkType
from src.main import app
from src.services.document_store import DocumentNotFoundError
from src.services.graph_store import GraphPersistenceError
from src.user_management.authentication import get_database_strategy
from src.user_management.manager import get_user_manager


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Client:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.committed = False

    async def query(self, statement, params=None, **kwargs):
        self.calls.append((statement, params, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response if isinstance(response, dict) else {"result": response}

    command = query

    @asynccontextmanager
    async def transaction(self):
        yield self
        self.committed = True


def store(client):
    return ArcadeDBGraphStore("unused", "unused", "unused", "unused", client=client)


def link_row(index=0):
    return dict(
        link_id=f"link-{index}",
        source_claim_id="node-a",
        target_claim_id="node-b",
        source_document_id="doc-a",
        target_document_id="doc-b",
        relation_type="REVISITS",
        profile="profile",
        evidence_json=json.dumps(
            {"source": [{"quote": "Original", "start_line": 1}], "target": [{"quote": "Otra nota"}]}
        ),
    )


@pytest.mark.anyio
async def test_documents_only_graph_returns_empty_without_querying_missing_edges():
    client = Client([[{"name": "Document"}]])
    result = await store(client).get_link_neighborhood("doc-a")
    assert result.model_dump() == dict(
        document_id="doc-a",
        neighbor_ids=[],
        total_neighbors=0,
        next_offset=None,
        links=[],
        links_truncated=False,
    )
    assert len(client.calls) == 1


@pytest.mark.anyio
async def test_neighbor_paging_filter_and_link_evidence_contract():
    row = link_row()
    client = Client(
        [[{"name": "CROSS_DOCUMENT_LINK"}], [{"total": 4}], [{"neighbor_id": "doc-b"}], [row, row]]
    )
    result = await store(client).get_link_neighborhood(
        "doc-a", offset=1, limit=1, relation_type=LinkType.REVISITS
    )
    assert result.next_offset == 2 and result.total_neighbors == 4
    assert result.neighbor_ids == ["doc-b"]
    assert len(result.links) == 1
    assert result.links[0].source_evidence[0].quote == "Original"
    assert result.links[0].source_evidence[0].start_line == 1
    assert result.links[0].target_evidence[0].end_line is None
    assert client.calls[2][1]["offset"] == 1
    assert client.calls[2][1]["relation_types"] == ["REVISITS"]
    assert client.calls[3][1]["document_ids"] == ["doc-a", "doc-b"]


@pytest.mark.anyio
async def test_link_hydration_signals_bounded_results():
    client = Client(
        [
            [{"name": "CROSS_DOCUMENT_LINK"}],
            [{"total": 1}],
            [{"neighbor_id": "doc-b"}],
            [link_row(i) for i in range(501)],
        ]
    )
    result = await store(client).get_link_neighborhood("doc-a")
    assert result.links_truncated and len(result.links) == 500
    assert result.next_offset is None


@pytest.mark.anyio
async def test_invalid_evidence_is_not_reported_as_success():
    client = Client(
        [
            [{"name": "CROSS_DOCUMENT_LINK"}],
            [{"total": 1}],
            [{"neighbor_id": "doc-b"}],
            [{**link_row(), "evidence_json": "bad"}],
        ]
    )
    with pytest.raises(GraphPersistenceError):
        await store(client).get_link_neighborhood("doc-a")


@pytest.mark.anyio
@pytest.mark.parametrize("success", [True, False])
async def test_document_write_is_verified_before_commit(success):
    document = build_document(NewDocument(content="Original sin extracción"))
    client = Client([[{"id": str(document.id), "content": document.content}] if success else []])
    if success:
        await store(client).persist_document(document)
        assert client.committed
    else:
        with pytest.raises(GraphPersistenceError, match="verified"):
            await store(client).persist_document(document)
        assert not client.committed
    assert client.calls[0][1]["content"] == document.content


@pytest.fixture
async def api():
    document_id = uuid4()
    documents = SimpleNamespace(get=AsyncMock(return_value=object()))
    graph = SimpleNamespace(
        get_link_neighborhood=AsyncMock(
            return_value=LinkNeighborhood(
                document_id=str(document_id),
                neighbor_ids=[],
                total_neighbors=0,
                next_offset=None,
                links=[],
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
            yield client, str(document_id), documents, graph
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_graph_api_keeps_response_and_forwards_filters(api):
    client, document_id, _, graph = api
    response = await client.get(
        f"/documents/{document_id}/links",
        params={"offset": 2, "limit": 5, "relation_type": "IN_TENSION"},
    )
    assert response.status_code == 200
    assert response.json() == dict(
        document_id=document_id,
        neighbor_ids=[],
        total_neighbors=0,
        next_offset=None,
        links=[],
        links_truncated=False,
    )
    graph.get_link_neighborhood.assert_awaited_once_with(
        document_id, offset=2, limit=5, relation_type=LinkType.IN_TENSION
    )


@pytest.mark.anyio
async def test_graph_api_checks_document_before_reading_links(api):
    client, document_id, documents, graph = api
    documents.get.side_effect = DocumentNotFoundError("missing")
    assert (await client.get(f"/documents/{document_id}/links")).status_code == 404
    graph.get_link_neighborhood.assert_not_awaited()


@pytest.mark.anyio
async def test_graph_api_reports_storage_failure(api):
    client, document_id, _, graph = api
    graph.get_link_neighborhood.side_effect = GraphPersistenceError("unavailable")
    assert (await client.get(f"/documents/{document_id}/links")).status_code == 502


@pytest.mark.anyio
@pytest.mark.parametrize(
    "params", [{"offset": -1}, {"limit": 0}, {"limit": 41}, {"relation_type": "UNKNOWN"}]
)
async def test_graph_api_rejects_invalid_pagination_and_filters(api, params):
    client, document_id, _, graph = api
    assert (await client.get(f"/documents/{document_id}/links", params=params)).status_code == 422
    graph.get_link_neighborhood.assert_not_awaited()


@pytest.mark.anyio
async def test_graph_api_requires_authentication():
    app.dependency_overrides.update(
        {
            get_user_manager: lambda: object(),
            get_database_strategy: lambda: object(),
        }
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            assert (await client.get(f"/documents/{uuid4()}/links")).status_code == 401
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
@pytest.mark.parametrize("response", [{"result": [], "truncated": True}, {"unexpected": []}])
async def test_incomplete_inventory_is_not_mistaken_for_empty_graph(response):
    with pytest.raises(GraphPersistenceError):
        await store(Client([response])).get_link_neighborhood("doc-a")


@pytest.mark.anyio
@pytest.mark.parametrize("selected", [None, ["emotions", "events"], []])
async def test_extraction_graph_layer_catalog_and_multiple_selection(monkeypatch, selected):
    from src.extractors.presentation import LAYER_PRESENTATIONS
    from src.graph.contracts import GraphLayer

    monkeypatch.setitem(
        LAYER_PRESENTATIONS,
        "document_embedding",
        GraphLayer(id="document_embedding", label="Búsqueda semántica", visualizable=False),
    )
    names = ["emotions", "events", "decisions", "document_embedding"]
    rows = [
        dict(
            layer=name,
            node_id=name,
            edge_id=name,
            node_types=["Item"],
            node_label=name,
            edge_type="HAS_ITEM",
        )
        for name in names
    ]
    client = Client([[{"layer": name} for name in names], rows, [], []])
    result = await store(client).get_extraction_graph("doc", layers=selected)
    assert result.layers == sorted(names)
    assert {option.id: option.label for option in result.layer_options}["emotions"] == "Emociones"
    assert {option.id: option.visualizable for option in result.layer_options}[
        "document_embedding"
    ] is False
    expected = set(names[:-1] if selected is None else selected)
    assert {edge.layer for edge in result.edges} == expected
    assert len(result.nodes) == len(expected) + 1
    assert result.root_id in {node.id for node in result.nodes}
