"""Concurrent authenticated GETs coordinate durable title work without invoking an LLM."""

# ruff: noqa: F811
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from test_document_title_processing import titled  # noqa: F401
from test_emotion_layer import layer_database  # noqa: F401
from test_emotion_processing import pipeline, run, upload  # noqa: F401
from test_processing_postgres import store  # noqa: F401
from test_title_backfill import counts, fork_title

from src.api.routes import processing as routes
from src.auth.session import require_authenticated
from src.domain.documents import NewDocument, build_document
from src.main import app
from src.processing.execution import ExecuteProcessing
from src.services.document_store import FileDocumentStore
from src.use_cases.backfill_document_titles import BackfillDocumentTitles, TitleBackfillResult
from src.use_cases.request_processing import RequestProcessing
from src.use_cases.submit_processing import document_identity, document_title_specification
from src.workspaces.dependencies import get_workspace_runtime

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not (os.getenv("PROCESSING_TEST_DATABASE_URL") and os.getenv("EMOTIONS_TEST_ARCADEDB_URL")),
        reason="requires isolated PostgreSQL and ArcadeDB",
    ),
]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def reads(titled, monkeypatch):
    env = titled
    env.read_settings = SimpleNamespace(
        document_title_read_limit=2,
        llm_provider="openai",
        openai_model="title-test",
        openai_api_key="unused-fake-key",
    )
    monkeypatch.setattr(
        "src.use_cases.ensure_document_titles.get_settings", lambda: env.read_settings
    )
    monkeypatch.setattr(routes, "get_repository", lambda: env.repo)
    monkeypatch.setattr("src.processing.runtime.get_repository", lambda: env.repo)
    app.dependency_overrides[require_authenticated] = lambda: "owner"
    app.dependency_overrides[get_workspace_runtime] = lambda: env.runtime
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            yield env, client
    finally:
        app.dependency_overrides.clear()


async def test_simultaneous_detail_and_lists_enqueue_exactly_one_job_and_do_not_wait_for_llm(reads):
    env, client = reads
    paths = [f"/v2/documents/{env.original.id}", "/v2/documents", "/documents"] * 2
    responses = await asyncio.gather(*(client.get(path) for path in paths))
    assert all(response.status_code == 200 for response in responses)
    assert await counts(env) == {
        "ProcessingReceipt": 1,
        "ProcessingRecord": 1,
        "ProcessingEvent": 1,
        "outbox": 1,
    }
    assert env.title_provider.extract.await_count == 0 and env.provider.calls == 0
    backfill = BackfillDocumentTitles(env.repo, env.runtime)
    result = await backfill.inspect(env.original.id)
    parent, child = await fork_title(env, result)
    await run(env, child)
    await run(env, parent)
    response = await client.get(paths[0])
    assert response.json()["title"] == "Alegría y miedo en un día"
    assert response.json()["content"] == env.original.content
    assert env.title_provider.extract.await_count == 1
    assert (await counts(env))["ProcessingRecord"] == 2  # One coordinator and one title child.


async def test_list_schedules_bounded_batches_and_preserves_existing_titles(reads):
    env, client = reads
    for _ in range(4):
        await env.runtime.document_store.save(
            build_document(NewDocument(content="Una nota antigua"))
        )
    known = build_document(NewDocument(content="Un original con título"))
    await env.runtime.document_store.save(known.model_copy(update={"title": "Título conservado"}))
    for expected in (2, 4, 5, 5):
        response = await client.get("/v2/documents")
        assert response.status_code == 200 and len(response.json()) == 6
        assert (await counts(env))["ProcessingRecord"] == expected
        assert (
            next(doc for doc in response.json() if doc["id"] == str(known.id))["title"]
            == "Título conservado"
        )
    assert env.title_provider.extract.await_count == 0


async def test_normal_upload_owns_title_even_before_children_exist_and_after_terminal_failure(
    reads,
):
    env, client = reads
    await env.runtime.document_store.update_title(env.original.id, "Otra nota ya titulada")
    doc, normal = await upload(env)
    assert (await client.get(f"/v2/documents/{doc.id}")).status_code == 200
    assert (await client.get("/v2/documents")).status_code == 200
    assert (await counts(env))["ProcessingRecord"] == 1
    from sqlalchemy import update

    from src.processing.models import ProcessingRecord

    async with env.repo.sessions.begin() as session:
        await session.execute(
            update(ProcessingRecord)
            .where(ProcessingRecord.id == normal.id)
            .values(
                status="failed",
                retryable=True,
                error_code="extraction_unavailable",
            )
        )
    for _ in range(3):
        assert (await client.get(f"/v2/documents/{doc.id}")).status_code == 200
    assert (await counts(env))["ProcessingRecord"] == 1
    assert env.title_provider.extract.await_count == 0


async def test_reserved_normal_upload_blocks_lazy_title_before_acceptance(reads):
    env, client = reads
    doc = build_document(NewDocument(content="Original publicado antes de aceptar la subida"))
    receipt = await env.submit.reserve(
        user_id=env.owner,
        operation="upload_document",
        key=uuid4(),
        resource_kind="document",
        resource_id=doc.id,
        request_hash=document_identity(doc),
        manifest={},
        config={"document_workflow_version": 4, "extractors": [document_title_specification()]},
    )
    await env.runtime.document_store.save(doc)
    response = await client.get(f"/v2/documents/{doc.id}")
    assert response.status_code == 200 and response.json()["processing"] is None
    assert (await counts(env))["ProcessingRecord"] == 0
    await env.submit.accept(receipt)
    assert (await client.get(f"/v2/documents/{doc.id}")).status_code == 200
    assert (await counts(env))["ProcessingRecord"] == 1


async def test_enqueue_failure_does_not_fail_get_and_next_read_can_retry(
    reads, monkeypatch, caplog
):
    env, client = reads
    schedule = env.repo.schedule

    def unavailable(*_):
        raise OSError("private configuration must not be echoed")

    monkeypatch.setattr(env.repo, "schedule", unavailable)
    response = await client.get(f"/v2/documents/{env.original.id}")
    assert response.status_code == 200 and response.json()["content"] == env.original.content
    assert (await counts(env))["ProcessingRecord"] == 0
    assert "private configuration" not in caplog.text
    monkeypatch.setattr(env.repo, "schedule", schedule)
    assert (await client.get(f"/v2/documents/{env.original.id}")).status_code == 200
    assert (await counts(env))["ProcessingRecord"] == 1


async def test_get_never_restarts_an_exhausted_lazy_title_job(reads):
    env, client = reads
    env.execute = ExecuteProcessing(env.repo, env.registry, max_attempts=1)
    await client.get(f"/v2/documents/{env.original.id}")
    result = await BackfillDocumentTitles(env.repo, env.runtime).inspect(env.original.id)
    parent, child = await fork_title(env, result)
    env.title_provider.extract.side_effect = ConnectionError("provider unavailable")
    assert (await run(env, child)).status == "failed"
    parent = await run(env, parent)
    assert parent.status == "failed" and parent.retryable
    before = await counts(env)
    for path in (f"/v2/documents/{env.original.id}", "/v2/documents", "/documents"):
        assert (await client.get(path)).status_code == 200
    assert await counts(env) == before
    assert env.title_provider.extract.await_count == 1


async def test_unknown_or_other_workspace_notes_are_not_read_or_scheduled(reads, tmp_path):
    env, client = reads
    assert (await client.get(f"/v2/documents/{uuid4()}")).status_code == 404
    other = SimpleNamespace(
        context=SimpleNamespace(user_id=uuid4()),
        document_store=FileDocumentStore(tmp_path / "other"),
    )
    app.dependency_overrides[get_workspace_runtime] = lambda: other
    assert (await client.get(f"/v2/documents/{env.original.id}")).status_code == 404
    assert (await client.get("/v2/documents")).json() == []
    assert (await counts(env))["ProcessingRecord"] == 0


@pytest.mark.parametrize("kind", ["job", "reservation"])
async def test_normal_title_work_enqueued_after_preview_is_rechecked_under_guard(
    reads, monkeypatch, kind
):
    env, _ = reads
    backfill = BackfillDocumentTitles(env.repo, env.runtime)
    monkeypatch.setattr(
        backfill,
        "inspect",
        AsyncMock(return_value=TitleBackfillResult(env.original.id, "eligible")),
    )
    if kind == "job":
        await RequestProcessing(env.repo, env.runtime).reprocess_document(env.original.id, uuid4())
    else:
        await env.submit.reserve(
            user_id=env.owner,
            operation="import_document",
            key=uuid4(),
            resource_kind="document",
            resource_id=env.original.id,
            request_hash=document_identity(env.original),
            manifest={},
            config={"document_workflow_version": 4, "extractors": [document_title_specification()]},
        )
    result = await backfill.execute(env.original.id, apply=True)
    assert result.status == ("busy" if kind == "job" else "already_scheduled")
    assert (await counts(env))["ProcessingRecord"] == (1 if kind == "job" else 0)
