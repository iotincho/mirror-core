from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from src.auth.session import require_authenticated
from src.dependencies import get_extract_persist_and_embed_document
from src.domain.documents import Document
from src.embeddings.contracts import EmbeddingSpec, EmbeddingVector
from src.extraction.contracts import Concept, Evidence, ExtractionResult
from src.main import app
from src.services.document_store import FileDocumentStore
from src.services.embedding_provider import EmbeddingProvider
from src.services.extraction_store import FileExtractionStore
from src.services.graph_store import GraphStore
from src.services.structured_extractor import ProviderExtraction, TokenUsage
from src.use_cases.embed_claims import EmbedClaims
from src.use_cases.embed_documents import EmbedDocument
from src.use_cases.extract_and_persist_document import ExtractAndPersistDocument
from src.use_cases.extract_document import ExtractDocument
from src.use_cases.extract_persist_and_embed_document import ExtractPersistAndEmbedDocument


class FakeExtractor:
    provider_name = "fake"
    model_name = "fake-model"

    def extract(self, document: Document, profile) -> ProviderExtraction:
        quote = "autonomía"
        start = document.content.index(quote)
        return ProviderExtraction(
            result=ExtractionResult(
                concepts=[
                    Concept(
                        id="concept_1",
                        name=quote,
                        evidence=[
                            Evidence(start_char=start, end_char=start + len(quote), quote=quote)
                        ],
                    )
                ],
                entities=[],
                claims=[],
                relationships=[],
            ),
            provider=self.provider_name,
            model=self.model_name,
            usage=TokenUsage(),
        )


class FakeGraphStore(GraphStore):
    def __init__(self) -> None:
        self.persisted: list[tuple[Document, object]] = []

    def persist(self, document: Document, extraction: object) -> None:
        self.persisted.append((document, extraction))

    def delete_document(self, document_id: str) -> None:
        return None

    def persist_claim_embeddings(self, records, spec) -> None:
        return None

    def search_claim_embeddings(self, vector, spec, limit):
        return []

    def persist_document_embedding(self, record, spec) -> None:
        return None

    def search_document_embeddings(self, vector, spec, limit):
        return []


class FakeEmbeddingProvider(EmbeddingProvider):
    spec = EmbeddingSpec(provider="fake", model="fake-model", dimensions=2)

    def embed(self, texts: list[str]) -> list[EmbeddingVector]:
        return [EmbeddingVector(vector=[0.1, 0.2], spec=self.spec) for _ in texts]


@pytest.mark.anyio
async def test_create_extraction_persists_the_completed_run_in_the_graph(tmp_path) -> None:
    document = Document(
        id=uuid4(),
        content="Quiero más autonomía.",
        source="test",
        metadata={},
        created_at=datetime.now(UTC),
    )
    document_store = FileDocumentStore(tmp_path / "documents")
    document_store.save(document)

    graph_store = FakeGraphStore()

    async def override_extract_persist_and_embed_document() -> ExtractPersistAndEmbedDocument:
        return ExtractPersistAndEmbedDocument(
            ExtractAndPersistDocument(
                ExtractDocument(
                    document_store,
                    FileExtractionStore(tmp_path / "extractions"),
                    FakeExtractor(),
                ),
                graph_store,
            ),
            EmbedClaims(FakeEmbeddingProvider(), graph_store),
            EmbedDocument(FakeEmbeddingProvider(), graph_store),
        )

    app.dependency_overrides[get_extract_persist_and_embed_document] = (
        override_extract_persist_and_embed_document
    )
    app.dependency_overrides[require_authenticated] = lambda: "test-user"
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/documents/{document.id}/extractions",
                json={"profile": "v1"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["status"] == "completed"
    assert response.json()["result"]["concepts"][0]["name"] == "autonomía"
    assert graph_store.persisted[0][0].id == document.id


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
