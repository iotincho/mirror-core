"""Failures retain original notes and remain traceable across worker threads."""

import asyncio
import logging
from threading import Event
from uuid import UUID, uuid4

import httpx
import pytest

from src.auth.session import require_authenticated
from src.dependencies import get_ingest_and_extract_document, get_ingest_document_file
from src.embeddings.contracts import EmbeddingSpec, EmbeddingVector
from src.extraction.contracts import Claim, Evidence, ExtractionResult
from src.logging import request_id_context
from src.main import app
from src.services.document_embedding_store import DocumentEmbeddingStoreError
from src.services.document_store import FileDocumentStore
from src.services.embedding_provider import EmbeddingProviderError
from src.services.extraction_store import FileExtractionStore
from src.services.graph_store import GraphPersistenceError
from src.services.structured_extractor import ExtractionProviderError, ProviderExtraction
from src.use_cases.embed_claims import EmbedClaims
from src.use_cases.embed_documents import EmbedDocument
from src.use_cases.extract_and_persist_document import (
    ExtractAndPersistDocument,
    GraphPersistenceFailedError,
)
from src.use_cases.extract_document import ExtractDocument
from src.use_cases.extract_persist_and_embed_document import ExtractPersistAndEmbedDocument
from src.use_cases.ingest_and_extract_document import IngestAndExtractDocument
from src.use_cases.ingest_document import IngestDocument
from src.use_cases.ingest_document_file import IngestDocumentFile


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("file_upload", [False, True])
@pytest.mark.parametrize(
    "failure,status,stage,log_event",
    [
        ("extraction", 502, "extraction", "extraction_failed"),
        ("graph", 503, "graph_persistence", "graph_persistence_failed"),
        ("claim_provider", 503, "claim_embeddings", "claim_embedding_failed"),
        ("document_store", 503, "document_embeddings", "document_embedding_failed"),
    ],
)
async def test_processing_failures_are_logged_and_preserve_documents(
    tmp_path, caplog, failure, status, stage, log_event, file_upload,
):
    contexts = []

    class Extractor:
        provider_name = "fake"
        model_name = "extraction-model"

        def extract(self, document, profile):
            contexts.append(request_id_context.get())
            if failure == "extraction":
                raise ExtractionProviderError("model unavailable")
            return ProviderExtraction(
                provider="fake", model=self.model_name,
                result=ExtractionResult(
                    title="Un día tranquilo", concepts=[], entities=[], relationships=[],
                    claims=[Claim(
                        id="claim", text="Tuve un día tranquilo.", type="observation",
                        evidence=[Evidence(quote=document.content)],
                    )],
                ),
            )

    class GraphStore:
        def persist(self, document, extraction):
            if failure == "graph":
                raise GraphPersistenceError("ArcadeDB rejected graph write with HTTP 403")

        def persist_claim_embeddings(self, records, spec):
            pass

        def persist_document_embedding(self, record, spec):
            if failure == "document_store":
                raise DocumentEmbeddingStoreError("vector index unavailable")

    class Provider:
        spec = EmbeddingSpec(provider="fake", model="embedding-model", dimensions=2)

        def embed(self, texts):
            if failure == "claim_provider":
                raise EmbeddingProviderError("embedding model unavailable")
            return [EmbeddingVector(vector=[0.1, 0.2], spec=self.spec) for _ in texts]

    documents = FileDocumentStore(tmp_path / "documents")
    extractions = FileExtractionStore(tmp_path / "extractions")
    graph = GraphStore()
    provider = Provider()
    processor = IngestAndExtractDocument(
        IngestDocument(documents),
        ExtractPersistAndEmbedDocument(
            ExtractAndPersistDocument(ExtractDocument(documents, extractions, Extractor()), graph),
            EmbedClaims(provider, graph), EmbedDocument(provider, graph),
        ),
    )
    app.dependency_overrides[get_ingest_and_extract_document] = lambda: processor
    app.dependency_overrides[get_ingest_document_file] = lambda: IngestDocumentFile(documents)
    app.dependency_overrides[require_authenticated] = lambda: "test-user"
    caplog.set_level(logging.INFO)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            if file_upload:
                response = await client.post(
                    "/documents/files", files={"file": ("note.txt", b"Private source material")},
                )
            else:
                response = await client.post(
                    "/documents", json={"content": "Private source material", "source": "manual"},
                )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == status
    assert response.json()["detail"]["stage"] == stage
    assert response.json()["detail"]["run_id"]
    request_id = response.headers["x-request-id"]
    assert UUID(request_id)
    assert contexts == [request_id]
    assert request_id_context.get() == "-"
    assert log_event in caplog.text
    assert f"status={status}" in caplog.text
    assert request_id in caplog.text
    assert "Traceback" in caplog.text
    assert "Private source material" not in caplog.text
    assert documents.list()[0].content == "Private source material"
    if failure in {"claim_provider", "document_store"}:
        assert "model=embedding-model" in caplog.text
        assert "dimensions=2" in caplog.text
    if failure == "document_store":
        assert "stage=persistence" in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize("file_upload", [False, True])
async def test_upload_processing_does_not_block_health_checks(tmp_path, file_upload):
    started, release, finished = Event(), Event(), Event()

    class SlowProcessor:
        def execute(self, document):
            started.set()
            try:
                if not release.wait(timeout=3):
                    raise RuntimeError("API event loop was blocked by document processing")
                raise GraphPersistenceFailedError(uuid4())
            finally:
                finished.set()

    processor = SlowProcessor()
    app.dependency_overrides[get_ingest_and_extract_document] = lambda: processor
    app.dependency_overrides[get_ingest_document_file] = lambda: IngestDocumentFile(
        FileDocumentStore(tmp_path)
    )
    app.dependency_overrides[require_authenticated] = lambda: "test-user"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            if file_upload:
                upload = asyncio.create_task(client.post(
                    "/documents/files", files={"file": ("note.txt", b"A slow note")},
                ))
            else:
                upload = asyncio.create_task(client.post(
                    "/documents", json={"content": "A slow note", "source": "manual"},
                ))
            try:
                assert await asyncio.to_thread(started.wait, 1)
                assert not finished.is_set()
                health = await asyncio.wait_for(client.get("/health"), timeout=1)
                assert health.status_code == 200
                assert not finished.is_set()
            finally:
                release.set()
                response = await upload
            assert response.status_code == 503
    finally:
        release.set()
        app.dependency_overrides.clear()
