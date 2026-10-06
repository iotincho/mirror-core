import httpx
import pytest

from src.auth.session import require_authenticated
from src.dependencies import (
    get_ingest_and_extract_document,
    get_ingest_document_file,
    get_list_documents,
)
from src.domain.documents import Document
from src.extraction.contracts import Concept, Evidence, ExtractionResult
from src.main import app
from src.services.document_store import FileDocumentStore
from src.services.extraction_store import FileExtractionStore
from src.services.structured_extractor import ProviderExtraction, TokenUsage
from src.use_cases.extract_document import ExtractDocument
from src.use_cases.ingest_and_extract_document import IngestAndExtractDocument
from src.use_cases.ingest_document import IngestDocument
from src.use_cases.ingest_document_file import IngestDocumentFile
from src.use_cases.list_documents import ListDocuments


class FakeExtractor:
    provider_name = "fake"
    model_name = "fake-model"

    async def extract(self, document: Document, profile) -> ProviderExtraction:
        quote = "autonomía" if "autonomía" in document.content else document.content
        start = document.content.index(quote)
        return ProviderExtraction(
            result=ExtractionResult(
                title="Una reflexión personal",
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


def processing_use_case(tmp_path) -> IngestAndExtractDocument:
    document_store = FileDocumentStore(tmp_path / "documents")
    return IngestAndExtractDocument(
        ingest_document=IngestDocument(document_store),
        extract_document=ExtractDocument(
            document_store,
            FileExtractionStore(tmp_path / "extractions"),
            FakeExtractor(),
        ),
    )


@pytest.mark.anyio
async def test_create_document_delegates_to_use_case_and_returns_created_document(tmp_path) -> None:
    async def override_process_document() -> IngestAndExtractDocument:
        return processing_use_case(tmp_path)

    app.dependency_overrides[get_ingest_and_extract_document] = override_process_document
    app.dependency_overrides[get_list_documents] = lambda: ListDocuments(
        FileDocumentStore(tmp_path / "documents")
    )
    app.dependency_overrides[require_authenticated] = lambda: "test-user"

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/documents",
                json={
                    "content": "Estoy evaluando un cambio.",
                    "source": "manual",
                    "authored_at": "2024-01-10T09:30:00-03:00",
                },
            )
            listed = await client.get("/documents")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["document"]["content"] == "Estoy evaluando un cambio."
    assert body["document"]["source"] == "manual"
    assert body["document"]["title"] == "Una reflexión personal"
    assert body["extraction"]["result"]["title"] == "Una reflexión personal"
    assert listed.status_code == 200
    assert listed.json()[0]["title"] == body["document"]["title"]
    assert body["document"]["authored_at"] == "2024-01-10T09:30:00-03:00"
    assert body["document"]["created_at"] != body["document"]["authored_at"]
    assert body["extraction"]["status"] == "completed"
    assert (tmp_path / "documents" / f"{body['document']['id']}.json").is_file()


@pytest.mark.anyio
async def test_create_document_from_markdown_file(tmp_path) -> None:
    async def override_ingest_document_file() -> IngestDocumentFile:
        return IngestDocumentFile(FileDocumentStore(tmp_path / "documents"))

    async def override_process_document() -> IngestAndExtractDocument:
        return processing_use_case(tmp_path)

    app.dependency_overrides[get_ingest_document_file] = override_ingest_document_file
    app.dependency_overrides[get_ingest_and_extract_document] = override_process_document
    app.dependency_overrides[require_authenticated] = lambda: "test-user"

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/documents/files",
                data={"authored_at": "2024-01-10T09:30:00-03:00"},
                files={
                    "file": (
                        "reflexion.md",
                        b"# Una nota\n\nContenido original",
                        "text/markdown",
                    )
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201, response.text
    assert response.json()["document"]["metadata"] == {"filename": "reflexion.md", "format": "md"}
    assert response.json()["document"]["authored_at"] == "2024-01-10T09:30:00-03:00"
    assert response.json()["extraction"]["status"] == "completed"
    assert response.json()["document"]["title"] == "Una reflexión personal"
    assert (tmp_path / "documents" / f"{response.json()['document']['id']}.json").is_file()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
