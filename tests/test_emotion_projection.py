"""Incomplete storage scans must not look like a complete emotion catalog."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from src.graph import emotion_exploration as projection
from src.graph.arcadedb.store import ArcadeDBGraphStore
from src.services.graph_store import GraphPersistenceError


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Client:
    def __init__(self, responses):
        self.query = AsyncMock(side_effect=responses)

    @asynccontextmanager
    async def transaction(self):
        yield self


def store(client):
    return ArcadeDBGraphStore("http://test", "workspace-a", "test", "test", client=client)


def types():
    return {"result": [{"name": name} for name in sorted(projection.REQUIRED_TYPES)]}


@pytest.mark.anyio
@pytest.mark.parametrize("response", [{"result": [], "truncated": True}, {"unexpected": []}])
async def test_truncated_memberships_do_not_return_empty_catalog(response):
    with pytest.raises(GraphPersistenceError):
        await store(Client([types(), response])).list_emotions()


@pytest.mark.anyio
async def test_membership_pages_keep_normalized_groups_and_unique_notes(monkeypatch):
    monkeypatch.setattr(projection, "PAGE_SIZE", 2)
    client = Client(
        [
            types(),
            {
                "result": [
                    {"document_id": "a", "label": " MIEDO "},
                    {"document_id": "a", "label": "miedo"},
                ]
            },
            {"result": [{"document_id": "b", "label": "Miedo"}]},
        ]
    )
    catalog = await store(client).list_emotions()
    assert catalog.total == 1 and catalog.emotions[0].document_count == 2
    assert [call.args[1]["offset"] for call in client.query.await_args_list[1:]] == [0, 2]


@pytest.mark.anyio
async def test_scan_ceiling_reports_failure(monkeypatch):
    monkeypatch.setattr(projection, "PAGE_SIZE", 1)
    monkeypatch.setattr(projection, "MAX_ROWS", 1)
    row = {"result": [{"document_id": "a", "label": "miedo"}]}
    with pytest.raises(GraphPersistenceError):
        await store(Client([types(), row, row])).list_emotions()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "change", [{"quote": ""}, {"end_char": 99}, {"start_char": True}, {"quote": "Otra"}]
)
async def test_invalid_evidence_never_produces_success(change):
    client = Client(
        [
            types(),
            {"result": [{"document_id": "a", "label": "miedo"}]},
            {"result": [{"id": "a", "title": "Nota", "content": "Miedo", "metadata_json": "{}"}]},
            {
                "result": [
                    {
                        "document_id": "a",
                        "label": "miedo",
                        "quote": "Miedo",
                        "start_char": 0,
                        "end_char": 5,
                        "run_id": "run",
                        "emotion_id": "emotion",
                        "edge_id": "edge",
                        **change,
                    }
                ]
            },
        ]
    )
    with pytest.raises(GraphPersistenceError):
        await store(client).explore_emotion("miedo")
