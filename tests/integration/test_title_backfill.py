"""Title-only backfill with real transactions and graph writes; no paid provider calls."""

# ruff: noqa: F811
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from test_document_title_processing import titled  # noqa: F401
from test_emotion_layer import layer_database  # noqa: F401
from test_emotion_processing import pipeline, run, upload  # noqa: F401
from test_processing_postgres import store  # noqa: F401

from src.domain.documents import NewDocument, build_document
from src.processing.execution import ExecuteProcessing
from src.processing.models import (
    ProcessingEvent,
    ProcessingOutbox,
    ProcessingReceipt,
    ProcessingRecord,
)
from src.services.document_store import FileDocumentStore
from src.use_cases.backfill_document_titles import BackfillDocumentTitles, TitleBackfillResult

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


async def counts(env):
    async with env.repo.sessions() as session:
        result = {}
        for model in (ProcessingReceipt, ProcessingRecord, ProcessingEvent):
            result[model.__name__] = await session.scalar(
                select(func.count()).select_from(model).where(model.user_id == env.owner)
            )
        result["outbox"] = await session.scalar(
            select(func.count())
            .select_from(ProcessingOutbox)
            .join(ProcessingRecord, ProcessingRecord.id == ProcessingOutbox.processing_id)
            .where(ProcessingRecord.user_id == env.owner)
        )
        return result


async def fork_title(env, result):
    parent = await env.repo.get(result.processing_id, env.owner)
    assert [part["name"] for part in parent.config["extractors"]] == ["document_title"]
    parent = await run(env, parent)
    assert parent.status == "waiting"
    children = await env.repo.extractor_children(parent.id, env.owner)
    assert len(children) == 1 and children[0].extractor_name == "document_title"
    return parent, children[0]


async def test_preview_is_read_only_apply_only_titles_and_repeat_continues_the_next_batch(titled):
    env = titled
    titled_doc = env.original.model_copy(update={"id": uuid4(), "title": "Título que se conserva"})
    old_doc = build_document(NewDocument(content="Material anterior sin grafo", source="imported"))
    await env.runtime.document_store.save(titled_doc)
    await env.runtime.document_store.save(old_doc)
    backfill = BackfillDocumentTitles(env.repo, env.runtime)
    before = await counts(env)
    preview = await backfill.run(limit=1)
    assert preview["counts"] == {"eligible": 1, "deferred": 1, "titled": 1}
    assert await counts(env) == before
    assert env.title_provider.extract.await_count == 0
    applied = await backfill.run(apply=True, limit=1)
    assert applied["counts"].get("queued") == 1 and applied["counts"].get("deferred") == 1
    result = next(row for row in applied["documents"] if row["status"] == "queued")
    from uuid import UUID

    queued = TitleBackfillResult(
        UUID(result["document_id"]), "queued", UUID(result["processing_id"])
    )
    parent, child = await fork_title(env, queued)
    assert (await run(env, child)).status == "completed"
    assert (await run(env, parent)).status == "completed"
    assert env.title_provider.extract.await_count == 1
    second = await backfill.run(apply=True, limit=1)
    assert second["counts"].get("queued") == 1 and second["counts"].get("completed") == 1
    assert (await env.runtime.document_store.get(titled_doc.id)) == titled_doc
    assert env.provider.calls == 0 and env.transcriber.calls == 0


async def test_missing_graph_is_created_before_title_without_modifying_original_or_other_layers(
    titled,
):
    env = titled
    doc = build_document(
        NewDocument(content="Un original histórico", metadata={"origin": "backup"})
    )
    await env.runtime.document_store.save(doc)
    result = await BackfillDocumentTitles(env.repo, env.runtime).execute(doc.id, apply=True)
    parent, child = await fork_title(env, result)
    await run(env, child)
    await run(env, parent)
    current = await env.runtime.document_store.get(doc.id)
    assert current.title and current.model_dump(exclude={"title"}) == doc.model_dump(
        exclude={"title"}
    )
    rows = (await env.client.query("SELECT title FROM Document WHERE id=:id", {"id": str(doc.id)}))[
        "result"
    ]
    assert rows == [{"title": current.title}]
    assert env.title_provider.extract.await_count == 1
    assert env.provider.calls == 0 and env.transcriber.calls == 0


async def test_concurrent_invocations_never_create_duplicate_jobs_or_outbox(titled):
    env = titled
    backfill = BackfillDocumentTitles(env.repo, env.runtime)
    results = await asyncio.gather(
        *(backfill.execute(env.original.id, apply=True) for _ in range(2))
    )
    assert sum(result.status == "queued" for result in results) == 1
    replay = await backfill.execute(env.original.id, apply=True)
    queued = next(result for result in results if result.status == "queued")
    assert replay.status == "already_scheduled" and replay.processing_id == queued.processing_id
    assert await counts(env) == {
        "ProcessingReceipt": 1,
        "ProcessingRecord": 1,
        "ProcessingEvent": 1,
        "outbox": 1,
    }


async def test_busy_missing_deleted_and_foreign_documents_are_not_enqueued(titled, tmp_path):
    env = titled
    doc, parent = await upload(env)
    backfill = BackfillDocumentTitles(env.repo, env.runtime)
    assert (await backfill.execute(doc.id, apply=True)).status == "busy"
    await env.repo.mark_deleted(
        env.owner, doc.id
    )  # Simulate interrupted deletion with file retained.
    assert (await backfill.execute(doc.id, apply=True)).status == "deleted"
    assert (await backfill.execute(uuid4(), apply=True)).status == "missing"
    other = SimpleNamespace(
        context=SimpleNamespace(user_id=uuid4()),
        document_store=FileDocumentStore(tmp_path / "other"),
    )
    assert (
        await BackfillDocumentTitles(env.repo, other).execute(doc.id, apply=True)
    ).status == "missing"
    assert (await counts(env))["ProcessingRecord"] == 1


async def test_projection_failure_resumes_same_job_and_artifact_even_with_canonical_title(
    titled, monkeypatch
):
    env = titled
    env.execute = ExecuteProcessing(env.repo, env.registry, max_attempts=1)
    backfill = BackfillDocumentTitles(env.repo, env.runtime)
    result = await backfill.execute(env.original.id, apply=True)
    parent, child = await fork_title(env, result)
    env.title_store.update_title.side_effect = ConnectionError("temporary graph outage")
    failed = await run(env, child)
    assert failed.status == "failed" and failed.stage == "persistence" and failed.retryable
    parent = await run(env, parent)
    assert parent.status == "failed"
    assert (await env.runtime.document_store.get(env.original.id)).title
    assert (await backfill.execute(env.original.id)).status == "retryable"
    other = await env.repo.create(
        user_id=env.owner,
        workflow="document",
        workflow_version=2,
        stage="document_persistence",
        resource_kind="document",
        resource_id=env.original.id,
    )
    assert (await backfill.execute(env.original.id, apply=True)).status == "busy"
    # A stale preview cannot bypass the idle check inside the retry's resource guard.
    inspect = backfill.inspect
    monkeypatch.setattr(
        backfill,
        "inspect",
        AsyncMock(
            return_value=TitleBackfillResult(
                env.original.id,
                "retryable",
                parent.id,
            )
        ),
    )
    assert (await backfill.execute(env.original.id, apply=True)).status == "busy"
    monkeypatch.setattr(backfill, "inspect", inspect)
    assert (await run(env, other)).status == "completed"
    env.title_store.update_title.side_effect = env.title_write
    retry = await backfill.execute(env.original.id, apply=True)
    assert retry.status == "retried" and retry.processing_id == parent.id
    await run(env, await env.repo.get(parent.id, env.owner))
    current_child = (await env.repo.extractor_children(parent.id, env.owner))[0]
    assert (
        current_child.id == child.id and current_child.extraction_run_id == child.extraction_run_id
    )
    assert (await run(env, current_child)).status == "completed"
    assert (await run(env, parent)).status == "completed"
    assert env.title_provider.extract.await_count == 1
    assert (await backfill.execute(env.original.id, apply=True)).status == "completed"


async def test_permanent_failure_is_reported_without_starting_a_new_llm_run(titled):
    env = titled
    backfill = BackfillDocumentTitles(env.repo, env.runtime)
    result = await backfill.execute(env.original.id, apply=True)
    parent, child = await fork_title(env, result)
    env.title_provider.extract.side_effect = ValueError("invalid title")
    assert (await run(env, child)).status == "failed"
    await run(env, parent)
    assert (await backfill.execute(env.original.id, apply=True)).status == "failed"
    assert env.title_provider.extract.await_count == 1
    assert (await env.runtime.document_store.get(env.original.id)).title is None


async def test_interrupted_submission_rolls_back_receipt_job_event_and_outbox(titled, monkeypatch):
    env = titled
    backfill = BackfillDocumentTitles(env.repo, env.runtime)
    before = await counts(env)

    def interrupt(*_):
        raise RuntimeError("interrupted outbox write")

    schedule = env.repo.schedule
    monkeypatch.setattr(env.repo, "schedule", interrupt)
    with pytest.raises(RuntimeError, match="interrupted"):
        await backfill.execute(env.original.id, apply=True)
    assert await counts(env) == before
    monkeypatch.setattr(env.repo, "schedule", schedule)
    assert (await backfill.execute(env.original.id, apply=True)).status == "queued"


async def test_title_assigned_after_preview_is_preserved_under_guard(titled, monkeypatch):
    env = titled
    backfill = BackfillDocumentTitles(env.repo, env.runtime)
    monkeypatch.setattr(
        backfill,
        "inspect",
        AsyncMock(return_value=TitleBackfillResult(env.original.id, "eligible")),
    )
    await env.runtime.document_store.update_title(
        env.original.id, "Título asignado concurrentemente"
    )
    assert (await backfill.execute(env.original.id, apply=True)).status == "titled"
    assert (await counts(env))["ProcessingReceipt"] == 0
    assert (
        await env.runtime.document_store.get(env.original.id)
    ).title == "Título asignado concurrentemente"
