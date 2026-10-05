"""Concurrency, cancellation and real async transports without external services."""

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from openai import AsyncOpenAI

from src.config import Settings
from src.domain.documents import NewDocument
from src.embeddings.contracts import EmbeddingSpec
from src.extraction.contracts import ExtractionResult
from src.graph.arcadedb.client import ArcadeDBClientError, AsyncArcadeDBHTTPClient
from src.graph.arcadedb.store import ArcadeDBGraphStore
from src.services.document_store import DocumentAlreadyExistsError, FileDocumentStore
from src.services.extraction_store import FileExtractionStore
from src.services.openai_embedding_provider import OpenAIEmbeddingProvider
from src.services.structured_extractor import ProviderExtraction
from src.use_cases.embed_claims import EmbedClaims
from src.use_cases.embed_documents import EmbedDocument
from src.use_cases.extract_and_persist_document import ExtractAndPersistDocument
from src.use_cases.extract_document import ExtractDocument
from src.use_cases.extract_persist_and_embed_document import ExtractPersistAndEmbedDocument
from src.use_cases.ingest_and_extract_document import IngestAndExtractDocument
from src.use_cases.ingest_document import IngestDocument

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def test_embedding_uses_real_async_sdk_and_bounds_inflight_requests(monkeypatch):
    monkeypatch.setattr(
        "src.services.async_provider.get_settings",
        lambda: Settings(provider_max_concurrency=2),
    )
    active = maximum = calls = 0
    two_started, release = asyncio.Event(), asyncio.Event()

    async def respond(request):
        nonlocal active, maximum, calls
        assert request.url.path == "/v1/embeddings"
        payload = json.loads(request.content)
        calls += 1
        active += 1
        maximum = max(maximum, active)
        if active == 2:
            two_started.set()
        try:
            await release.wait()
            return httpx.Response(
                200,
                json={
                    "object": "list",
                    "model": "test-embedding",
                    "data": [{"object": "embedding", "index": 0, "embedding": [1.0, 0.0]}],
                    "usage": {"prompt_tokens": len(payload["input"]), "total_tokens": 1},
                },
            )
        finally:
            active -= 1

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        async with AsyncOpenAI(api_key="local-test", http_client=http, max_retries=0) as sdk:
            provider = OpenAIEmbeddingProvider(None, "test-embedding", 2, client=sdk)
            tasks = [asyncio.create_task(provider.embed([f"note {i}"])) for i in range(5)]
            try:
                await asyncio.wait_for(two_started.wait(), 2)
                await asyncio.sleep(0)
                assert calls == maximum == 2
                release.set()
                results = await asyncio.gather(*tasks)
                assert calls == 5 and maximum == 2
                assert all(result[0].vector == [1.0, 0.0] for result in results)
                await provider.close()
                assert not sdk.is_closed()  # Borrowed SDK belongs to the enclosing context.
            finally:
                release.set()
                await asyncio.gather(*tasks, return_exceptions=True)


async def test_provider_created_client_is_closed_and_can_be_recreated(monkeypatch):
    clients = []

    class Client:
        def __init__(self, **kwargs):
            self.options = kwargs
            self.closed = False
            clients.append(self)

        async def close(self):
            self.closed = True

    monkeypatch.setattr("openai.AsyncOpenAI", Client)
    provider = OpenAIEmbeddingProvider("local-test", "test", 2)
    first = provider._get_client()
    await provider.close()
    assert first.closed and provider._client is None
    assert provider._get_client() is not first
    await provider.close()
    assert all(client.closed for client in clients)


async def test_concurrent_graph_transactions_keep_separate_sessions_and_rollback():
    requests = []
    commands_started, release = asyncio.Event(), asyncio.Event()
    starts = commands = 0

    async def respond(request):
        nonlocal starts, commands
        operation = request.url.path.split("/")[-2]
        session = request.headers.get("arcadedb-session-id")
        requests.append((operation, session))
        if operation == "begin":
            starts += 1
            return httpx.Response(200, headers={"arcadedb-session-id": f"session-{starts}"})
        if operation == "command":
            commands += 1
            if commands == 2:
                commands_started.set()
            await release.wait()
        return httpx.Response(200, json={"result": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        client = AsyncArcadeDBHTTPClient("http://graph", "workspace", "user", "secret", client=http)

        async def execute(fail):
            async with client.transaction() as transaction:
                await transaction.command("SELECT 1")
                if fail:
                    raise ValueError("abort")

        tasks = [asyncio.create_task(execute(fail)) for fail in (False, True)]
        try:
            await asyncio.wait_for(commands_started.wait(), 2)
            assert {session for op, session in requests if op == "command"} == {
                "session-1",
                "session-2",
            }
            release.set()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            assert results[0] is None and isinstance(results[1], ValueError)
            assert ("commit", "session-1") in requests
            assert ("rollback", "session-2") in requests
            assert ("commit", "session-2") not in requests
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)


async def test_cancellation_rolls_back_graph_transaction():
    operations = []
    started = asyncio.Event()

    async def respond(request):
        operation = request.url.path.split("/")[-2]
        operations.append(operation)
        return httpx.Response(200, json={}, headers={"arcadedb-session-id": "session"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        client = AsyncArcadeDBHTTPClient("http://graph", "workspace", "user", "secret", client=http)

        async def execute():
            async with client.transaction() as transaction:
                await transaction.command("SELECT 1")
                started.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(execute())
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert operations == ["begin", "command", "rollback"]


@pytest.mark.parametrize("failure", ["http", "connection"])
async def test_async_graph_transport_preserves_error_boundary(failure):
    def respond(request):
        if failure == "connection":
            raise httpx.ConnectError("unavailable", request=request)
        return httpx.Response(503, text="private details")

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        client = AsyncArcadeDBHTTPClient("http://graph", "workspace", "user", "secret", client=http)
        with pytest.raises(ArcadeDBClientError) as caught:
            await client.query("SELECT 1")
        assert caught.value.__cause__ is not None
        assert "private details" not in str(caught.value)


async def test_file_io_does_not_block_other_coroutines(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    store = FileDocumentStore(tmp_path)
    original_save = store._save
    document = SimpleNamespace()

    def slow_save(value):
        entered.set()
        assert release.wait(2)
        assert value is document

    monkeypatch.setattr(store, "_save", slow_save)
    task = asyncio.create_task(store.save(document))
    try:
        assert await asyncio.wait_for(asyncio.to_thread(entered.wait, 1), 2)
        # The storage operation is still blocked in its thread while the loop advances.
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
        await task
    monkeypatch.setattr(store, "_save", original_save)


async def test_two_complete_document_pipelines_overlap_without_reordering_stages(tmp_path):
    both_extracting, release = asyncio.Event(), asyncio.Event()
    extracting = 0
    order = {}

    class Extractor:
        provider_name = model_name = "test"

        async def extract(self, document, profile):
            nonlocal extracting
            order[document.id] = ["extraction"]
            extracting += 1
            if extracting == 2:
                both_extracting.set()
            await release.wait()
            return ProviderExtraction(
                result=ExtractionResult(concepts=[], entities=[], relationships=[], claims=[]),
                provider="test",
                model="test",
            )

    class Embeddings:
        spec = EmbeddingSpec(provider="test", model="test", dimensions=2)

        async def embed(self, texts):
            from src.embeddings.contracts import EmbeddingVector

            return [EmbeddingVector(vector=[1.0, 0.0], spec=self.spec) for _ in texts]

    class Client:
        @asynccontextmanager
        async def transaction(self):
            yield self

        async def command(self, statement, params, **kwargs):
            doc_id = params.get("document_id", params.get("id"))
            if doc_id and "run_id" in params:
                from uuid import UUID

                order[UUID(doc_id)].append("graph")
            elif "vector" in params:
                from uuid import UUID

                order[UUID(doc_id)].append("document_embedding")
            return {"result": []}

    documents = FileDocumentStore(tmp_path / "documents")
    history = FileExtractionStore(tmp_path / "extractions")
    graph = ArcadeDBGraphStore("http://unused", "test", "user", "secret", client=Client())
    embeddings = Embeddings()
    pipeline = IngestAndExtractDocument(
        IngestDocument(documents),
        ExtractPersistAndEmbedDocument(
            ExtractAndPersistDocument(ExtractDocument(documents, history, Extractor()), graph),
            EmbedClaims(embeddings, graph),
            EmbedDocument(embeddings, graph),
        ),
    )
    tasks = [
        asyncio.create_task(pipeline.execute(NewDocument(content=text)))
        for text in ("Primera nota", "Segunda nota")
    ]
    try:
        await asyncio.wait_for(both_extracting.wait(), 2)
        release.set()
        results = await asyncio.gather(*tasks)
        assert len(await documents.list()) == 2
        for result in results:
            assert result.extraction.status == "completed"
            assert order[result.document.id] == ["extraction", "graph", "document_embedding"]
            assert len(await history.list_for_document(result.document.id)) == 1
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_concurrent_submission_of_same_id_cannot_overwrite_original(tmp_path, monkeypatch):
    from pathlib import Path

    store = FileDocumentStore(tmp_path)
    document = await IngestDocument(FileDocumentStore(tmp_path / "source")).execute(
        NewDocument(content="Original")
    )
    another = document.model_copy(update={"content": "Otro contenido"})
    barrier = threading.Barrier(2)
    write_text = Path.write_text

    def synchronize_writes(path, *args, **kwargs):
        result = write_text(path, *args, **kwargs)
        barrier.wait(timeout=2)
        return result

    monkeypatch.setattr(Path, "write_text", synchronize_writes)
    results = await asyncio.gather(
        store.save(document), store.save(another), return_exceptions=True
    )
    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, DocumentAlreadyExistsError) for result in results) == 1
    stored = await store.get(document.id)
    winner = document if results[0] is None else another
    assert stored == winner
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("fail", [False, True])
async def test_workspace_runtime_closes_graph_after_background_tasks(monkeypatch, fail):
    from typing import Annotated

    from fastapi import BackgroundTasks, Depends, FastAPI

    from src.workspaces.dependencies import get_workspace_binding, get_workspace_runtime

    events = []

    async def close():
        events.append("closed")

    runtime = SimpleNamespace(graph_store=SimpleNamespace(close=close))
    monkeypatch.setattr(
        "src.workspaces.dependencies.build_workspace_runtime", lambda *args: runtime
    )
    app = FastAPI()
    app.dependency_overrides[get_workspace_binding] = lambda: None

    @app.get("/test")
    async def endpoint(
        background: BackgroundTasks,
        workspace: Annotated[object, Depends(get_workspace_runtime)],
    ):
        assert workspace is runtime
        if fail:
            raise ValueError("endpoint failed")

        async def work():
            assert not events
            events.append("background")

        background.add_task(work)
        return {"accepted": True}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        if fail:
            with pytest.raises(ValueError, match="endpoint failed"):
                await client.get("/test")
            assert events == ["closed"]
        else:
            assert (await client.get("/test")).status_code == 200
            assert events == ["background", "closed"]
