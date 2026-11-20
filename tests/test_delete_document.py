from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest

from src.bootstrap.archives import build_delete_document as DeleteDocument
from src.bootstrap.auth import require_authenticated
from src.bootstrap.processing import get_repository
from src.bootstrap.public_api import app
from src.bootstrap.workspaces import get_workspace_runtime
from src.core.graph.ports import GraphStore


class RecordingDocumentStore:
    def __init__(self) -> None:
        self.loaded: list[UUID] = []
        self.deleted: list[UUID] = []

    async def get(self, document_id: UUID) -> object:
        self.loaded.append(document_id)
        return object()

    async def delete(self, document_id: UUID) -> None:
        self.deleted.append(document_id)


class RecordingLayerArtifacts:
    def __init__(self) -> None:
        self.deleted: list[UUID] = []

    async def delete_for_document(self, document_id: UUID) -> None:
        self.deleted.append(document_id)


class RecordingGraphStore(GraphStore):
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete_document(self, document_id: str) -> None:
        self.deleted.append(document_id)


@pytest.mark.anyio
async def test_delete_document_depends_on_graph_contract() -> None:
    document_id = uuid4()
    documents = RecordingDocumentStore()
    graph = RecordingGraphStore()

    await DeleteDocument(documents, graph).execute(document_id)

    assert documents.loaded == [document_id]
    assert graph.deleted == [str(document_id)]
    assert documents.deleted == [document_id]


@pytest.mark.anyio
async def test_delete_document_removes_derived_layer_artifacts():
    document_id = uuid4()
    documents = RecordingDocumentStore()
    layers = RecordingLayerArtifacts()
    graph = RecordingGraphStore()
    await DeleteDocument(documents, graph, layer_artifacts=layers).execute(document_id)
    assert layers.deleted == [document_id]
    assert documents.deleted == [document_id]


@pytest.mark.anyio
async def test_public_delete_builds_the_use_case_and_cleans_its_artifacts(tmp_path, monkeypatch):
    owner, document_id, job_id = uuid4(), uuid4(), uuid4()
    documents, graph = RecordingDocumentStore(), RecordingGraphStore()
    runtime = SimpleNamespace(
        context=SimpleNamespace(user_id=owner, filesystem_root=tmp_path),
        document_store=documents,
        graph_store=graph,
    )
    layer = tmp_path / "layers" / str(document_id)
    checkpoint = tmp_path / "processing" / str(job_id)
    for directory in (layer, checkpoint):
        directory.mkdir(parents=True)
        (directory / "result.json").write_text("{}", encoding="utf-8")

    marked = []

    class Processing:
        @asynccontextmanager
        async def lock_resource(self, user_id, resource_id):
            assert (user_id, resource_id) == (owner, document_id)
            yield True

        async def assert_inactive(self, user_id, resource_id):
            assert (user_id, resource_id) == (owner, document_id)

        async def mark_deleted(self, user_id, resource_id):
            marked.append((user_id, resource_id))

        @asynccontextmanager
        async def transaction(self):
            yield self

        async def jobs_for_resources(self, user_id, resource_ids):
            assert (user_id, resource_ids) == (owner, [document_id])
            return [SimpleNamespace(id=job_id)]

    monkeypatch.setitem(app.dependency_overrides, require_authenticated, lambda: owner)
    monkeypatch.setitem(app.dependency_overrides, get_workspace_runtime, lambda: runtime)
    monkeypatch.setitem(app.dependency_overrides, get_repository, lambda: Processing())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.delete(f"/documents/{document_id}")

    assert response.status_code == 204
    assert marked == [(owner, document_id)]
    assert documents.deleted == [document_id]
    assert graph.deleted == [str(document_id)]
    assert not layer.exists() and not checkpoint.exists()
