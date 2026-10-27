"""Atomic batch acceptance, replay, ownership and coordination against real PostgreSQL."""

# ruff: noqa: F811

import asyncio
import os
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, update
from test_processing_postgres import anyio_backend, store  # noqa: F401

from src.adapters.storage.filesystem.documents import FileDocumentStore
from src.adapters.storage.postgres.models import (
    ProcessingOutbox,
    ProcessingReceipt,
    ProcessingRecord,
)
from src.bootstrap.auth import require_authenticated
from src.bootstrap.processing import build_processing_requests as RequestProcessing
from src.bootstrap.processing import get_repository
from src.bootstrap.public_api import app
from src.bootstrap.workspaces import get_workspace_runtime
from src.core.documents.ports import DocumentNotFoundError
from src.core.domain.documents import NewDocument, build_document
from src.core.processing.submissions import SubmissionConflict

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("PROCESSING_TEST_DATABASE_URL"), reason="requires isolated PostgreSQL"
    ),
]


@pytest.fixture
async def batch(store, tmp_path):
    repo, owner = store
    runtime = SimpleNamespace(
        context=SimpleNamespace(user_id=owner), document_store=FileDocumentStore(tmp_path)
    )
    notes = [build_document(NewDocument(content=f"Nota {index}")) for index in range(30)]
    for note in notes:
        await runtime.document_store.save(note)
    await runtime.document_store.update_title(notes[0].id, "Título conservado")
    return repo, runtime, notes, RequestProcessing(repo, runtime)


async def count(repo, model):
    async with repo.sessions() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def test_batch_exceeds_pool_capacity_and_replay_keeps_jobs_and_configuration(batch):
    repo, runtime, notes, request = batch
    key = uuid4()
    ids = [note.id for note in notes]
    jobs = await asyncio.wait_for(request.reprocess_documents(ids, key), timeout=15)
    assert len(jobs) == 30 and all(job.status == "queued" for job in jobs)
    titled = next(job for job in jobs if job.resource_id == notes[0].id)
    assert {spec["name"] for spec in titled.config["extractors"]} == {
        "emotions",
        "document_embeddings",
    }
    untitled = next(job for job in jobs if job.resource_id == notes[1].id)
    assert {spec["name"] for spec in untitled.config["extractors"]} == {
        "emotions",
        "document_embeddings",
        "document_title",
    }
    assert all(
        next(spec for spec in job.config["extractors"] if spec["name"] == "document_embeddings")[
            "force"
        ]
        for job in jobs
    )
    replay = await request.reprocess_documents(list(reversed(ids)), key)
    assert [job.id for job in replay] == [job.id for job in jobs]
    assert await count(repo, ProcessingRecord) == 30
    assert await count(repo, ProcessingOutbox) == 30
    assert await count(repo, ProcessingReceipt) == 1
    assert (await runtime.document_store.get(notes[0].id)).title == "Título conservado"
    with pytest.raises(SubmissionConflict, match="idempotency_conflict"):
        await request.reprocess_documents(ids[:1], key)
    # A completed selection may deliberately be processed again with a new identity.
    async with repo.sessions.begin() as session:
        await session.execute(update(ProcessingRecord).values(status="completed"))
    new = await request.reprocess_documents(ids, uuid4())
    assert {job.id for job in new}.isdisjoint(job.id for job in jobs)


async def test_invalid_foreign_and_active_selection_enqueue_nothing(batch):
    repo, runtime, notes, request = batch
    ids = [notes[0].id, notes[1].id]
    with pytest.raises(DocumentNotFoundError):
        await request.reprocess_documents(ids + [uuid4()], uuid4())
    assert await count(repo, ProcessingRecord) == 0
    assert await count(repo, ProcessingReceipt) == 0
    with pytest.raises(ValueError, match="Duplicate"):
        await request.reprocess_documents(ids + ids, uuid4())
    existing = await request.reprocess_document(notes[0].id, uuid4())
    with pytest.raises(ValueError, match="processing_active"):
        await request.reprocess_documents(ids, uuid4())
    assert await count(repo, ProcessingRecord) == 1
    assert await count(repo, ProcessingOutbox) == 1
    assert (await repo.get(existing.id, runtime.context.user_id)).status == "queued"


async def test_locked_selection_rolls_back_and_releases_all_guards(batch):
    repo, runtime, notes, request = batch
    ids = sorted(note.id for note in notes)
    async with repo.lock_resource(runtime.context.user_id, ids[-1]) as acquired:
        assert acquired
        with pytest.raises(SubmissionConflict, match="processing_active"):
            await request.reprocess_documents(ids, uuid4())
    assert await count(repo, ProcessingRecord) == 0
    assert len(await request.reprocess_documents(ids, uuid4())) == 30


async def test_batch_api_validation_ownership_and_replay(batch, monkeypatch):
    repo, runtime, notes, _ = batch
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[require_authenticated] = lambda: runtime.context
    app.dependency_overrides[get_workspace_runtime] = lambda: runtime
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            endpoint = "/v2/documents/reprocess"
            key = {"Idempotency-Key": str(uuid4())}
            assert (
                await client.post(endpoint, json={"document_ids": []}, headers=key)
            ).status_code == 422
            ids = [str(note.id) for note in notes[:2]]
            foreign = await client.post(
                endpoint, json={"document_ids": ids + [str(uuid4())]}, headers=key
            )
            assert foreign.status_code == 404
            assert await count(repo, ProcessingRecord) == 0
            result = await client.post(endpoint, json={"document_ids": ids}, headers=key)
            assert result.status_code == 202
            body = result.json()
            assert len(body["items"]) == 2
            assert all("config" not in item for item in body["items"])
            replay = await client.post(endpoint, json={"document_ids": ids}, headers=key)
            assert replay.json() == body
            conflict = await client.post(
                endpoint, json={"document_ids": ids}, headers={"Idempotency-Key": str(uuid4())}
            )
            assert conflict.status_code == 409
    finally:
        app.dependency_overrides.clear()


async def test_outbox_failure_rolls_back_the_entire_batch(batch, monkeypatch):
    repo, _, notes, request = batch
    schedule = repo.schedule
    calls = 0

    def interrupted(session, record):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("interrupted batch acceptance")
        schedule(session, record)

    monkeypatch.setattr(repo, "schedule", interrupted)
    with pytest.raises(RuntimeError, match="interrupted batch"):
        await request.reprocess_documents([note.id for note in notes[:3]], uuid4())
    assert await count(repo, ProcessingRecord) == 0
    assert await count(repo, ProcessingOutbox) == 0
    assert await count(repo, ProcessingReceipt) == 0
