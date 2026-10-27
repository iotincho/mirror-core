import httpx
import pytest

from src.adapters.storage.filesystem.documents import FileDocumentStore
from src.bootstrap.auth import require_authenticated
from src.bootstrap.public_api import app
from src.bootstrap.public_dependencies import get_list_documents
from src.core.domain.documents import NewDocument, build_document
from src.use_cases.documents.list_documents import ListDocuments


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_originals_remain_readable_and_legacy_upload_is_retired(tmp_path):
    store = FileDocumentStore(tmp_path)
    document = build_document(NewDocument(content="Mi documento original"))
    await store.save(document)
    app.dependency_overrides[require_authenticated] = lambda: "owner"
    app.dependency_overrides[get_list_documents] = lambda: ListDocuments(store)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            assert (await client.post("/documents", json={"content": "nuevo"})).status_code == 410
            assert (await client.post("/documents/files")).status_code == 410
            response = await client.get("/documents")
            assert response.status_code == 200
            assert response.json()[0]["content"] == document.content
        assert len(await store.list()) == 1
    finally:
        app.dependency_overrides.clear()
