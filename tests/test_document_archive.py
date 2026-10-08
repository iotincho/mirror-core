from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from src.api.routes.document_archive import get_archive_store
from src.auth.session import require_authenticated
from src.domain.documents import Document
from src.main import app
from src.processing.runtime import get_repository
from src.processing.submissions import SubmissionConflict, fingerprint
from src.services.document_store import FileDocumentStore
from src.use_cases.document_archive import ArchiveConflict, DocumentArchive, DocumentArchiveTransfer
from src.workspaces.dependencies import get_workspace_runtime


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Processing:
    @asynccontextmanager
    async def lock_resource(self, user, resource):
        yield True

    async def assert_inactive(self, user, resource):
        pass


class Submissions:
    def __init__(self):
        self.receipts = {}
        self.jobs = []
        self.fail = False

    async def accepted(self, user_id, operation, key, request_hash):
        receipt = self.receipts.get((user_id, key))
        return receipt if receipt and receipt.accepted_at else None

    async def reserve(self, **values):
        key = values["user_id"], values["key"]
        if key not in self.receipts:
            self.receipts[key] = SimpleNamespace(**values, accepted_at=None)
        receipt = self.receipts[key]
        if receipt.request_hash != values["request_hash"]:
            raise SubmissionConflict("idempotency_conflict")
        return receipt

    async def accept(self, receipt):
        if self.fail:
            raise RuntimeError("SQL unavailable")
        if receipt.accepted_at is None:
            self.jobs.append(receipt)
            receipt.accepted_at = datetime.now(UTC)

    async def release(self, receipt):
        pass


def document():
    return Document(
        id=uuid4(),
        title="Título original",
        content="Texto completo\ncon acentos: ñ",
        source="audio",
        metadata={"origen": "voz"},
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        authored_at=datetime(2024, 12, 20, tzinfo=UTC),
    )


@pytest.mark.anyio
async def test_roundtrip_all_fields_and_retry_enqueues_once_after_partial_write(tmp_path):
    original = FileDocumentStore(tmp_path / "old")
    doc = document()
    await original.save(doc)
    archive = DocumentArchive.model_validate_json(
        (await DocumentArchiveTransfer(original).export()).model_dump_json()
    )
    restored, submissions = FileDocumentStore(tmp_path / "new"), Submissions()
    transfer = DocumentArchiveTransfer(
        restored, processing=Processing(), user_id=uuid4(), submissions=submissions
    )
    submissions.fail = True
    with pytest.raises(RuntimeError, match="SQL unavailable"):
        await transfer.import_archive(archive)
    assert await restored.get(doc.id) == doc
    submissions.fail = False
    assert await transfer.import_archive(archive) == {"imported": 0, "existing": 1, "total": 1}
    assert await transfer.import_archive(archive) == {"imported": 0, "existing": 1, "total": 1}
    assert len(submissions.jobs) == 1
    receipt = submissions.jobs[0]
    assert receipt.resource_id == doc.id
    assert receipt.operation == "import_document"
    assert receipt.request_hash == fingerprint(doc.model_dump(mode="json"))
    assert receipt.config["document_workflow_version"] == 4
    assert {item["name"] for item in receipt.config["extractors"]} == {
        "emotions",
        "document_embeddings",
    }
    assert len(await restored.list()) == 1


@pytest.mark.anyio
async def test_conflict_preflight_writes_nothing(tmp_path):
    store, submissions = FileDocumentStore(tmp_path), Submissions()
    old, new = document(), document()
    await store.save(old)
    changed = old.model_copy(update={"content": "distinto"})
    archive = DocumentArchive(
        exported_at=datetime.now(UTC), documents=[new.model_dump(), changed.model_dump()]
    )
    with pytest.raises(ArchiveConflict):
        await DocumentArchiveTransfer(
            store, processing=Processing(), user_id=uuid4(), submissions=submissions
        ).import_archive(archive)
    assert await store.list() == [old]
    assert not submissions.receipts


def test_rejects_duplicate_unknown_fields_version_and_naive_dates():
    doc = document().model_dump(mode="json")
    base = {
        "format": "el-espejo-documents",
        "version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "documents": [doc],
    }
    variants = [
        dict(base, version=2),
        dict(base, documents=[doc, doc]),
        dict(base, documents=[dict(doc, user_id=str(uuid4()))]),
        dict(base, documents=[dict(doc, created_at="2025-01-01T00:00:00")]),
    ]
    for invalid in variants:
        with pytest.raises(ValidationError):
            DocumentArchive.model_validate(invalid)


@pytest.mark.anyio
async def test_authenticated_download_upload_and_invalid_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.use_cases.document_archive.SubmissionRepository", lambda processing: Submissions()
    )
    store = FileDocumentStore(tmp_path)
    doc = document()
    await store.save(doc)
    app.dependency_overrides[require_authenticated] = lambda: "owner"
    app.dependency_overrides[get_archive_store] = lambda: store
    app.dependency_overrides[get_workspace_runtime] = lambda: SimpleNamespace(
        document_store=store, graph_store=None, context=SimpleNamespace(user_id=uuid4())
    )
    app.dependency_overrides[get_repository] = Processing
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            response = await client.get("/documents/export")
            assert response.status_code == 200
            assert "attachment" in response.headers["Content-Disposition"]
            assert response.headers["Cache-Control"] == "no-store"
            assert response.json()["documents"][0] == doc.model_dump(mode="json")
            uploaded = await client.post(
                "/documents/import",
                files={"file": ("backup.json", response.content, "application/json")},
            )
            assert uploaded.status_code == 200
            assert uploaded.json() == {"imported": 0, "existing": 1, "total": 1}
            invalid = await client.post(
                "/documents/import",
                files={"file": ("backup.json", b'{"sensitive":"do not echo"}', "application/json")},
            )
            assert invalid.status_code == 422 and "do not echo" not in invalid.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_offline_export_is_importable_without_database(tmp_path):
    from scripts.export_document_archives import export_all

    owner = uuid4()
    root = tmp_path / "workspaces"
    store = FileDocumentStore(root / str(owner) / "documents")
    original = document()
    await store.save(original)
    output = tmp_path / "exports"
    assert export_all(root, output) == {str(owner): 1}
    archive = DocumentArchive.model_validate_json((output / f"{owner}.json").read_bytes())
    assert archive.documents[0].model_dump() == original.model_dump()
    assert (output / f"{owner}.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        export_all(root, output)


@pytest.mark.anyio
async def test_export_store_scoped_to_user_without_active_graph(tmp_path, monkeypatch):
    import src.api.routes.document_archive as routes

    owner, other = uuid4(), uuid4()
    one, two = document(), document()
    await FileDocumentStore(tmp_path / str(owner) / "documents").save(one)
    await FileDocumentStore(tmp_path / str(other) / "documents").save(two)

    class Repository:
        def __init__(self, session):
            pass

        async def get(self, user):
            return SimpleNamespace(status="suspended", arcadedb_instance_key="test")

    monkeypatch.setattr(routes, "WorkspaceRepository", Repository)
    monkeypatch.setattr(
        routes,
        "get_settings",
        lambda: SimpleNamespace(arcadedb_instance_key="test", workspaces_path=tmp_path),
    )
    store = await routes.get_archive_store(SimpleNamespace(id=owner), None)
    archive = await DocumentArchiveTransfer(store).export()
    assert [doc.id for doc in archive.documents] == [one.id]


@pytest.mark.anyio
async def test_archive_routes_require_authentication():
    from fastapi import HTTPException

    from src.user_management.dependencies import current_active_user

    def unauthorized():
        raise HTTPException(401, "Unauthorized")

    app.dependency_overrides[current_active_user] = unauthorized
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            assert (await client.get("/documents/export")).status_code == 401
            assert (
                await client.post(
                    "/documents/import", files={"file": ("backup.json", b"{}", "application/json")}
                )
            ).status_code == 401
    finally:
        app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_each_document_enqueued_and_replay_ignores_own_active_job(tmp_path):
    store, submissions, processing = FileDocumentStore(tmp_path), Submissions(), Processing()
    docs = [document(), document()]
    archive = DocumentArchive(
        exported_at=datetime.now(UTC), documents=[d.model_dump() for d in docs]
    )
    transfer = DocumentArchiveTransfer(
        store, processing=processing, user_id=uuid4(), submissions=submissions
    )
    assert await transfer.import_archive(archive) == {"imported": 2, "existing": 0, "total": 2}
    processing.assert_inactive = AsyncMock(side_effect=ValueError("processing_active"))
    assert await transfer.import_archive(archive) == {"imported": 0, "existing": 2, "total": 2}
    assert len(submissions.jobs) == 2
    processing.assert_inactive.assert_not_called()
    assert {job.resource_id for job in submissions.jobs} == {d.id for d in docs}
    for doc in docs:
        assert await store.get(doc.id) == doc


@pytest.mark.anyio
async def test_import_rejects_unrelated_active_processing(tmp_path):
    store, submissions, processing = FileDocumentStore(tmp_path), Submissions(), Processing()
    processing.assert_inactive = AsyncMock(side_effect=ValueError("processing_active"))
    doc = document()
    archive = DocumentArchive(exported_at=datetime.now(UTC), documents=[doc.model_dump()])
    transfer = DocumentArchiveTransfer(
        store, processing=processing, user_id=uuid4(), submissions=submissions
    )
    with pytest.raises(ArchiveConflict, match="procesamiento"):
        await transfer.import_archive(archive)
    assert not await store.list()
    assert not submissions.jobs
