"""Deferred uploads and real state machines, with isolated PostgreSQL and files."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, update
from test_processing_postgres import anyio_backend, store  # noqa: F401, F811

from src.api.routes import processing as routes
from src.auth.session import require_authenticated
from src.domain.documents import NewDocument
from src.main import app
from src.processing.execution import ExecuteProcessing, WorkflowRegistry
from src.processing.models import ProcessingReceipt, ProcessingRecord
from src.processing.submissions import SubmissionConflict, SubmissionRepository
from src.services.audio_note_store import FileAudioNoteStore
from src.services.document_store import FileDocumentStore
from src.services.graph_store import GraphPersistenceError
from src.use_cases.delete_document import DeleteDocument
from src.use_cases.process_audio_note import ProcessAudioNote
from src.use_cases.process_document import ProcessDocument
from src.use_cases.request_processing import RequestProcessing
from src.use_cases.submit_processing import (
    SubmitAudioNote,
    SubmitDocument,
    recover_submissions,
    workflow_config,
)
from src.workspaces.dependencies import get_workspace_runtime

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("PROCESSING_TEST_DATABASE_URL"),
        reason="requires isolated PostgreSQL",
    ),
]


class FakeProviders:
    provider_name, model_name = "fake", "fake-model"

    def __init__(self):
        self.extractions = self.transcriptions = self.embeddings = 0
        self.delay = 0

    async def extract(self, *args):
        raise AssertionError("document workflow must not extract")

    async def transcribe(self, path):
        self.transcriptions += 1
        return "Quiero más autonomía."

    async def embed(self, *args):
        raise AssertionError("document workflow must not embed")


class FakeGraph:
    def __init__(self):
        self.runs, self.claims, self.documents = {}, {}, {}
        self.failure = None

    async def persist_document(self, document):
        self.documents[str(document.id)] = document
        if self.failure == "graph":
            self.failure = None
            raise GraphPersistenceError("commit response lost") from httpx.ReadTimeout("lost")

    async def delete_document(self, document_id):
        self.documents.pop(document_id, None)

    async def close(self):
        pass


@pytest.fixture
async def ingestion(store, tmp_path, monkeypatch):  # noqa: F811
    repo, owner = store
    providers, graph = FakeProviders(), FakeGraph()
    config = {**workflow_config(), "extractors": [], "document_workflow_version": 2}
    config.update(
        llm_provider="fake",
        llm_model="fake-model",
    )
    monkeypatch.setattr(
        "src.use_cases.submit_processing.workflow_config",
        lambda profile="v4": {
            **config,
            **({"profile": profile} if profile != "v4" else {}),
        },
    )
    monkeypatch.setattr("src.bootstrap.acceptance.workflow_config", lambda: dict(config))
    runtime = SimpleNamespace(
        context=SimpleNamespace(user_id=owner, filesystem_root=tmp_path),
        document_store=FileDocumentStore(tmp_path / "documents"),
        audio_note_store=FileAudioNoteStore(tmp_path / "audio-notes"),
        graph_store=graph,
    )

    @asynccontextmanager
    async def factory(user_id):
        assert user_id == owner
        yield runtime

    registry = WorkflowRegistry()
    from src.processing.execution import WorkflowDefinition
    from src.processing.workflows import retired_extraction

    registry.register("document", 1, WorkflowDefinition(retired_extraction, frozenset()))

    def provider_factory(config):
        return providers

    registry.register("document", 2, ProcessDocument(factory).definition)
    registry.register("audio", 1, ProcessAudioNote(factory, provider_factory).definition)
    registry.register("audio", 2, ProcessAudioNote(factory, provider_factory).definition)
    return SimpleNamespace(
        repo=repo,
        owner=owner,
        providers=providers,
        graph=graph,
        runtime=runtime,
        factory=factory,
        executor=ExecuteProcessing(repo, registry),
        submissions=SubmissionRepository(repo),
        config=config,
    )


async def submit(env, key=None, document_id=None):
    return await SubmitDocument(env.submissions, env.runtime).execute(
        NewDocument(id=document_id, content="Quiero más autonomía."), key or uuid4()
    )


async def run_current(env, record):
    current = await env.repo.get(record.id, env.owner)
    async with env.repo.sessions.begin() as session:
        await session.execute(
            update(ProcessingRecord)
            .where(ProcessingRecord.id == record.id)
            .values(available_at=func.now())
        )
    await env.executor(record.id, current.generation)
    return await env.repo.get(record.id, env.owner)


async def test_upload_commits_base_graph_without_models_and_is_idempotent(ingestion):
    env = ingestion
    key = uuid4()
    original, record = await submit(env, key)
    repeated, same = await submit(env, key)
    assert original.id == repeated.id and record.id == same.id
    assert (record.status, env.providers.extractions, env.providers.embeddings) == ("queued", 0, 0)
    assert env.graph.documents[str(original.id)] == original
    assert not env.graph.runs
    different_key, original_job = await submit(env, uuid4(), original.id)
    assert different_key.id == original.id and original_job.id == record.id
    with pytest.raises(SubmissionConflict, match="idempotency_conflict"):
        await SubmitDocument(env.submissions, env.runtime).execute(
            NewDocument(content="Otra nota"), key
        )


async def test_upload_waits_for_graph_commit_and_excludes_deletion(ingestion, monkeypatch):
    env = ingestion
    started, release = asyncio.Event(), asyncio.Event()
    persist = env.graph.persist_document

    async def slow_commit(document):
        started.set()
        await release.wait()
        await persist(document)

    monkeypatch.setattr(env.graph, "persist_document", slow_commit)
    upload = asyncio.create_task(submit(env))
    try:
        await asyncio.wait_for(started.wait(), 5)
        original = (await env.runtime.document_store.list())[0]
        assert not upload.done()
        assert not await env.repo.list_for_owner(env.owner)
        delete = DeleteDocument(env.runtime.document_store, env.graph, env.repo, env.owner)
        with pytest.raises(SubmissionConflict, match="processing_active"):
            await delete.execute(original.id)
    finally:
        release.set()
        accepted, record = await upload
    assert env.graph.documents[str(accepted.id)] == accepted
    assert record.status == "queued"
    assert env.providers.extractions == env.providers.embeddings == 0


async def test_upload_ambiguous_graph_commit_retains_original_and_retries_once(ingestion):
    env = ingestion
    key = uuid4()
    env.graph.failure = "graph"
    with pytest.raises(GraphPersistenceError):
        await submit(env, key)
    original = (await env.runtime.document_store.list())[0]
    assert str(original.id) in env.graph.documents
    assert not await env.repo.list_for_owner(env.owner)
    repeated, record = await submit(env, key)
    assert repeated == original and record.status == "queued"
    assert len(await env.repo.list_for_owner(env.owner)) == 1
    assert len(env.graph.documents) == 1
    assert len(await env.runtime.document_store.list()) == 1


async def test_recovery_requires_graph_commit_before_accepting_pending_originals(
    ingestion, monkeypatch
):
    env = ingestion
    persist = env.graph.persist_document
    monkeypatch.setattr(
        env.graph, "persist_document", AsyncMock(side_effect=GraphPersistenceError("unavailable"))
    )
    with pytest.raises(GraphPersistenceError):
        await submit(env)
    original = (await env.runtime.document_store.list())[0]
    await recover_submissions(env.submissions, env.factory)
    assert not await env.repo.list_for_owner(env.owner)
    assert not env.graph.documents
    async with env.repo.sessions.begin() as session:
        await session.execute(
            update(ProcessingReceipt)
            .where(ProcessingReceipt.user_id == env.owner)
            .values(lease_expires_at=func.clock_timestamp())
        )
    monkeypatch.setattr(env.graph, "persist_document", persist)
    await recover_submissions(env.submissions, env.factory)
    assert env.graph.documents[str(original.id)] == original
    assert len(await env.repo.list_for_owner(env.owner)) == 1


async def test_cancelled_upload_can_recover_without_losing_the_original(ingestion, monkeypatch):
    env = ingestion
    started = asyncio.Event()
    persist = env.graph.persist_document

    async def interrupted(document):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(env.graph, "persist_document", interrupted)
    key = uuid4()
    upload = asyncio.create_task(submit(env, key))
    await asyncio.wait_for(started.wait(), 5)
    upload.cancel()
    with pytest.raises(asyncio.CancelledError):
        await upload
    original = (await env.runtime.document_store.list())[0]
    assert not await env.repo.list_for_owner(env.owner)
    monkeypatch.setattr(env.graph, "persist_document", persist)
    await recover_submissions(env.submissions, env.factory)
    repeated, record = await submit(env, key)
    assert repeated == original and env.graph.documents[str(original.id)] == original
    assert len(await env.repo.list_for_owner(env.owner)) == 1
    assert record.status == "queued"


async def test_pending_recovery_reads_original_under_the_deletion_guard(ingestion, monkeypatch):
    env = ingestion
    env.graph.failure = "graph"
    with pytest.raises(GraphPersistenceError):
        await submit(env)
    original = (await env.runtime.document_store.list())[0]
    started, release = asyncio.Event(), asyncio.Event()
    get = env.runtime.document_store.get

    async def slow_get(identifier):
        started.set()
        await release.wait()
        return await get(identifier)

    monkeypatch.setattr(env.runtime.document_store, "get", slow_get)
    recovery = asyncio.create_task(recover_submissions(env.submissions, env.factory))
    try:
        await asyncio.wait_for(started.wait(), 5)
        delete = DeleteDocument(env.runtime.document_store, env.graph, env.repo, env.owner)
        with pytest.raises(SubmissionConflict, match="processing_active"):
            await delete.execute(original.id)
    finally:
        release.set()
        await recovery
    assert len(await env.repo.list_for_owner(env.owner)) == 1
    assert env.graph.documents[str(original.id)] == original


async def test_accepted_upload_replay_does_not_rewrite_the_graph(ingestion, monkeypatch):
    env = ingestion
    key = uuid4()
    original, record = await submit(env, key)
    persist = AsyncMock(side_effect=GraphPersistenceError("graph unavailable after acceptance"))
    monkeypatch.setattr(env.graph, "persist_document", persist)
    repeated, same = await submit(env, key)
    assert repeated == original and same.id == record.id
    persist.assert_not_awaited()


async def test_document_completes_without_models_or_extractions(ingestion):
    env = ingestion
    original, record = await submit(env)
    current = await run_current(env, record)
    assert (current.status, current.stage) == ("completed", "done")
    assert current.document_id == original.id and current.extraction_run_id is None
    assert current.completed_at is not None
    assert (env.providers.extractions, env.providers.embeddings) == (0, 0)
    assert len(env.graph.documents) == 1 and not env.graph.runs and not env.graph.claims
    await env.executor(record.id, 1)
    assert len(env.graph.documents) == 1
    assert (await env.runtime.document_store.get(original.id)).title is None


async def test_ambiguous_document_commit_replays_without_models(ingestion):
    env = ingestion
    _, record = await submit(env)
    env.graph.failure = "graph"
    assert (await run_current(env, record)).status == "retrying"
    assert (await run_current(env, record)).status == "completed"
    assert env.providers.extractions == env.providers.embeddings == 0
    assert len(env.graph.documents) == 1


async def test_audio_hands_off_to_child_and_reuses_transcript(ingestion):
    env = ingestion
    note, parent = await SubmitAudioNote(env.submissions, env.runtime, 1024).execute(
        "voice.webm", "audio/webm", b"audio", None, uuid4()
    )
    waiting = await run_current(env, parent)
    assert waiting.status == "waiting" and waiting.child_processing_id
    updated = await env.runtime.audio_note_store.get(note.id)
    assert updated.status == "completed" and updated.document_id == note.id
    assert str(note.id) in env.graph.documents
    child = await env.repo.child(waiting)
    assert child.document_id == note.id and child.parent_processing_id == parent.id
    await run_current(env, child)
    complete = await run_current(env, parent)
    assert complete.status == "completed"
    assert env.providers.transcriptions == 1
    assert (await env.runtime.document_store.get(note.id)).source == "pwa_audio"


async def test_audio_graph_failure_defers_document_link_without_retranscribing(ingestion):
    env = ingestion
    note, parent = await SubmitAudioNote(env.submissions, env.runtime, 1024).execute(
        "voice.webm", "audio/webm", b"audio", None, uuid4()
    )
    env.graph.failure = "graph"
    retrying = await run_current(env, parent)
    assert retrying.status == "retrying" and retrying.error_code == "graph_unavailable"
    assert (await env.runtime.audio_note_store.get(note.id)).document_id is None
    assert await env.repo.child(retrying) is None
    original = await env.runtime.document_store.get(note.id)
    waiting = await run_current(env, retrying)
    assert waiting.status == "waiting"
    assert (await env.runtime.audio_note_store.get(note.id)).document_id == note.id
    assert env.graph.documents[str(note.id)] == original
    assert env.providers.transcriptions == 1
    child = await env.repo.child(waiting)
    await run_current(env, child)
    complete = await run_current(env, parent)
    assert complete.status == "completed"
    assert env.providers.transcriptions == 1
    assert (await env.runtime.document_store.get(note.id)).source == "pwa_audio"


async def test_parent_retry_resumes_child_without_retranscribing(ingestion):
    env = ingestion
    note, parent = await SubmitAudioNote(env.submissions, env.runtime, 1024).execute(
        "voice.webm", "audio/webm", b"audio", None, uuid4()
    )
    waiting = await run_current(env, parent)
    child = await env.repo.child(waiting)
    env.graph.failure = "graph"
    await run_current(env, child)
    # Exhausted transient errors remain eligible for a manual retry.
    async with env.repo.sessions.begin() as session:
        row = await session.get(ProcessingRecord, child.id)
        row.status, row.retryable, row.error_code = "failed", True, "graph_unavailable"
    await env.repo.recover_parents()
    failed = await run_current(env, parent)
    assert failed.status == "failed" and failed.retryable
    resumed = await RequestProcessing(env.repo, env.runtime).retry(parent.id, uuid4())
    assert resumed.status == "waiting"
    await run_current(env, child)
    assert (await run_current(env, parent)).status == "completed"
    assert env.providers.transcriptions == 1
    assert (await env.runtime.audio_note_store.get(note.id)).document_error is None


async def test_receipt_recovery_closes_gap_after_file_write_before_sql_commit(
    ingestion, monkeypatch
):
    env = ingestion
    key = uuid4()
    original_accept = env.submissions.accept
    monkeypatch.setattr(
        env.submissions, "accept", AsyncMock(side_effect=ConnectionError("SQL down"))
    )
    with pytest.raises(ConnectionError):
        await submit(env, key)
    originals = await env.runtime.document_store.list()
    assert len(originals) == 1
    async with env.repo.sessions() as session:
        receipt = await session.scalar(
            select(ProcessingReceipt).where(ProcessingReceipt.user_id == env.owner)
        )
        assert receipt.processing_id is None
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ProcessingRecord)
                .where(ProcessingRecord.user_id == env.owner)
            )
            == 0
        )
    monkeypatch.setattr(env.submissions, "accept", original_accept)
    await recover_submissions(env.submissions, env.factory)
    repeated, record = await submit(env, key)
    assert repeated.id == originals[0].id and record.status == "queued"


async def test_concurrent_upload_has_one_receipt_owner(ingestion, monkeypatch):
    env = ingestion
    started, release = asyncio.Event(), asyncio.Event()
    save = env.runtime.document_store.save

    async def slow_save(document):
        started.set()
        await release.wait()
        await save(document)

    monkeypatch.setattr(env.runtime.document_store, "save", slow_save)
    key = uuid4()
    first = asyncio.create_task(submit(env, key))
    await started.wait()
    with pytest.raises(SubmissionConflict, match="upload_in_progress"):
        await submit(env, key)
    release.set()
    await first
    assert len(await env.runtime.document_store.list()) == 1


async def test_delete_and_reextract_reject_active_job_then_allow_completed(ingestion):
    env = ingestion
    original, record = await submit(env)
    delete = DeleteDocument(env.runtime.document_store, env.graph, env.repo, env.owner)
    with pytest.raises(SubmissionConflict, match="processing_active"):
        await delete.execute(original.id)
    with pytest.raises(ValueError, match="processing_active"):
        await RequestProcessing(env.repo, env.runtime).reprocess_document(original.id, uuid4())
    await run_current(env, record)
    second = await RequestProcessing(env.repo, env.runtime).reprocess_document(original.id, uuid4())
    assert second.id != record.id
    await run_current(env, second)
    await delete.execute(original.id)
    assert not await env.runtime.document_store.list()
    assert (await env.repo.get(second.id, env.owner)).resource_deleted


async def test_http_accepted_location_status_owner_and_size_limits(ingestion, monkeypatch):
    env = ingestion
    app.dependency_overrides[get_workspace_runtime] = lambda: env.runtime
    app.dependency_overrides[require_authenticated] = lambda: "test-user"
    monkeypatch.setattr(routes, "get_repository", lambda: env.repo)
    key = str(uuid4())
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            accepted = await client.post(
                "/v2/documents",
                json={"content": "Quiero más autonomía."},
                headers={"Idempotency-Key": key},
            )
            assert accepted.status_code == 202, accepted.text
            body = accepted.json()
            assert accepted.headers["Location"].endswith(body["processing"]["id"])
            assert env.providers.extractions == 0
            status = await client.get(accepted.headers["Location"])
            assert status.status_code == 200 and status.json()["status"] == "queued"
            page = await client.get("/processing?active=true&limit=1")
            assert len(page.json()["items"]) == 1
            assert (await client.get(f"/processing/{uuid4()}")).status_code == 404
            no_key = await client.post("/v2/documents", json={"content": "nota"})
            assert no_key.status_code == 422
            conflict = await client.post(
                "/v2/documents", json={"content": "Otra nota"}, headers={"Idempotency-Key": key}
            )
            assert conflict.status_code == 409
            records = await env.repo.list_for_owner(env.owner)
            await run_current(env, records[0])
            repeated = await client.post(
                "/v2/documents",
                json={"content": "Quiero más autonomía."},
                headers={"Idempotency-Key": key},
            )
            assert repeated.status_code == 200
            assert repeated.json()["processing"]["id"] == body["processing"]["id"]
            snapshot = await client.get(f"/v2/documents/{body['document']['id']}")
            assert snapshot.json()["processing"]["status"] == "completed"
            # Workspaces are independent even when a caller knows another job's UUID.
            other_runtime = SimpleNamespace(
                **{
                    **env.runtime.__dict__,
                    "context": SimpleNamespace(
                        user_id=uuid4(), filesystem_root=env.runtime.context.filesystem_root
                    ),
                }
            )
            app.dependency_overrides[get_workspace_runtime] = lambda: other_runtime
            assert (await client.get(accepted.headers["Location"])).status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("file_upload", [False, True])
async def test_http_graph_failure_returns_503_and_replays_the_same_original(
    ingestion, monkeypatch, file_upload
):
    env = ingestion
    app.dependency_overrides[get_workspace_runtime] = lambda: env.runtime
    app.dependency_overrides[require_authenticated] = lambda: "test-user"
    monkeypatch.setattr(routes, "get_repository", lambda: env.repo)
    key = str(uuid4())
    path = "/v2/documents/files" if file_upload else "/v2/documents"
    payload = (
        {"files": {"file": ("note.txt", b"Synthetic test note", "text/plain")}}
        if file_upload else {"json": {"content": "Synthetic test note"}}
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            env.graph.failure = "graph"
            failed = await client.post(path, headers={"Idempotency-Key": key}, **payload)
            assert failed.status_code == 503
            assert "same Idempotency-Key" in failed.json()["detail"]
            assert not await env.repo.list_for_owner(env.owner)
            original = (await env.runtime.document_store.list())[0]
            retried = await client.post(path, headers={"Idempotency-Key": key}, **payload)
            assert retried.status_code == 202, retried.text
            assert retried.json()["document"]["id"] == str(original.id)
            assert env.graph.documents[str(original.id)] == original
            assert len(await env.repo.list_for_owner(env.owner)) == 1
            assert env.providers.extractions == env.providers.embeddings == 0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.skipif(
    not os.getenv("PROCESSING_TEST_ARCADEDB_URL"), reason="requires isolated ArcadeDB"
)
async def test_real_arcadedb_document_write_and_replay(ingestion, monkeypatch):
    from src.dependencies import get_document_store, get_graph_store
    from src.graph.arcadedb.store import ArcadeDBGraphStore

    env = ingestion
    graph = ArcadeDBGraphStore(
        os.environ["PROCESSING_TEST_ARCADEDB_URL"],
        "processing_test",
        "root",
        os.getenv("PROCESSING_TEST_ARCADEDB_PASSWORD", "processing-test"),
    )
    env.runtime.graph_store = graph
    try:
        app.dependency_overrides[get_workspace_runtime] = lambda: env.runtime
        app.dependency_overrides[require_authenticated] = lambda: "test-user"
        app.dependency_overrides[get_document_store] = lambda: env.runtime.document_store
        app.dependency_overrides[get_graph_store] = lambda: graph
        monkeypatch.setattr(routes, "get_repository", lambda: env.repo)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://test"
        ) as client:
            accepted = await client.post(
                "/v2/documents", json={"content": "Synthetic graph availability test"},
                headers={"Idempotency-Key": str(uuid4())},
            )
            assert accepted.status_code == 202, accepted.text
            identifier = accepted.json()["document"]["id"]
            # No worker has run yet: the original's graph must already be readable.
            immediate = await client.get(f"/documents/{identifier}/emotions/graph")
            assert immediate.status_code == 200, immediate.text
            assert immediate.json()["root_id"] == f"Document:{identifier}"
            assert len(immediate.json()["nodes"]) == 1 and not immediate.json()["edges"]
        records = await env.repo.list_for_owner(env.owner)
        record = records[0]
        original = await env.runtime.document_store.get(record.resource_id)
        current = await run_current(env, record)
        assert current.status == "completed", (current.stage, current.error_code)
        await graph.persist_document(original)
        response = await graph._client.query(
            "SELECT id, content FROM Document WHERE id = :id", {"id": str(original.id)}
        )
        assert response["result"] == [{"id": str(original.id), "content": original.content}]
        assert env.providers.extractions == env.providers.embeddings == 0
    finally:
        app.dependency_overrides.clear()
        await graph.close()


@pytest.mark.skipif(
    not all(
        os.getenv(name)
        for name in (
            "PROCESSING_TEST_RABBITMQ_URL",
            "PROCESSING_TEST_ARCADEDB_URL",
        )
    ),
    reason="requires isolated RabbitMQ and ArcadeDB",
)
async def test_outbox_dispatcher_and_workers_finish_document_and_audio(ingestion, tmp_path):
    import signal
    import subprocess
    import sys
    from pathlib import Path

    from taskiq_aio_pika import AioPikaBroker

    env = ingestion
    original, document_job = await submit(env)
    note, audio_job = await SubmitAudioNote(env.submissions, env.runtime, 1024).execute(
        "voice.webm", "audio/webm", b"audio", None, uuid4()
    )
    queue = f"deferred.test.{uuid4().hex}"
    environment = {
        **os.environ,
        "DATABASE_URL": os.environ["PROCESSING_TEST_DATABASE_URL"],
        "RABBITMQ_URL": os.environ["PROCESSING_TEST_RABBITMQ_URL"],
        "PROCESSING_QUEUE_NAME": queue,
        "PROCESSING_CONCURRENCY": "2",
        "PROCESSING_TEST_WORKSPACE_ROOT": str(env.runtime.context.filesystem_root),
        "PYTHONPATH": str(Path(__file__).parent.resolve()),
    }
    commands = [
        [
            sys.executable,
            "-m",
            "taskiq",
            "worker",
            "src.processing.broker:broker",
            "src.processing.tasks",
            "deferred_worker_fixture",
            "--workers",
            "2",
            "--max-async-tasks",
            "2",
            "--ack-type",
            "manual",
        ],
        [sys.executable, "-m", "src.processing.dispatcher"],
    ]
    processes, logs = [], []
    try:
        for index, command in enumerate(commands):
            log = (tmp_path / f"process-{index}.log").open("w")
            logs.append(log)
            processes.append(
                subprocess.Popen(
                    command,
                    env=environment,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            )
        for _ in range(450):
            document = await env.repo.get(document_job.id, env.owner)
            audio = await env.repo.get(audio_job.id, env.owner)
            if document.status == audio.status == "completed":
                break
            if any(process.poll() is not None for process in processes):
                break
            await asyncio.sleep(0.1)
        for log in logs:
            log.flush()
        evidence = "\n".join(path.read_text() for path in tmp_path.glob("process-*.log"))
        assert document.status == audio.status == "completed", evidence
        assert document.document_id == original.id and audio.document_id == note.id
        child = await env.repo.child(audio)
        assert child.status == "completed"
        assert (await env.runtime.audio_note_store.get(note.id)).transcript
    finally:
        for process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        for log in logs:
            log.close()
        broker = AioPikaBroker(
            os.environ["PROCESSING_TEST_RABBITMQ_URL"],
            queue_name=queue,
            exchange_name=queue,
            declare_queues_kwargs={"durable": True},
            declare_exchange_kwargs={"durable": True},
        )
        await broker.startup()
        for name in (queue, f"{queue}.dead_letter", f"{queue}.delay"):
            await broker.write_channel.queue_delete(name)
        await broker.write_channel.exchange_delete(queue)
        await broker.shutdown()


async def test_successful_alias_key_cannot_be_reused_for_another_document(ingestion):
    env = ingestion
    original, _ = await submit(env)
    alias = uuid4()
    await submit(env, alias, original.id)
    with pytest.raises(SubmissionConflict, match="idempotency_conflict"):
        await SubmitDocument(env.submissions, env.runtime).execute(
            NewDocument(content="Otra nota"), alias
        )


async def test_audio_raw_file_recovery_completes_metadata_before_accepting(ingestion, monkeypatch):
    env = ingestion
    write_metadata = env.runtime.audio_note_store._write_metadata
    monkeypatch.setattr(
        env.runtime.audio_note_store,
        "_write_metadata",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk unavailable")),
    )
    with pytest.raises(OSError):
        await SubmitAudioNote(env.submissions, env.runtime, 1024).execute(
            "voice.webm", "audio/webm", b"audio", None, uuid4()
        )
    assert len(list((env.runtime.context.filesystem_root / "audio-notes").glob("*.webm"))) == 1
    monkeypatch.setattr(env.runtime.audio_note_store, "_write_metadata", write_metadata)
    await recover_submissions(env.submissions, env.factory)
    rows = await env.repo.list_for_owner(env.owner)
    assert len(rows) == 1 and rows[0].status == "queued"
    assert (await env.runtime.audio_note_store.get(rows[0].resource_id)).size_bytes == 5


async def test_legacy_audio_recovery_skips_transcription(ingestion):
    from src.domain.audio_notes import new_audio_note

    env = ingestion
    note = new_audio_note("voice.webm", "audio/webm", 5, None).model_copy(
        update={
            "status": "completed",
            "transcript": "Quiero más autonomía.",
            "transcription_provider": "legacy",
            "transcription_model": "legacy",
        }
    )
    await env.runtime.audio_note_store.create(note, b"audio")
    record = await RequestProcessing(env.repo, env.runtime).recover_audio(note.id, uuid4())
    waiting = await run_current(env, record)
    child = await env.repo.child(waiting)
    await run_current(env, child)
    assert (await run_current(env, record)).status == "completed"
    assert env.providers.transcriptions == 0


async def test_retry_key_and_reextract_key_replay_while_worker_holds_resource(ingestion):
    env = ingestion
    original, first = await submit(env)
    await run_current(env, first)
    key = uuid4()
    request = RequestProcessing(env.repo, env.runtime)
    second = await request.reprocess_document(original.id, key)
    async with env.repo.lock_resource(env.owner, original.id) as acquired:
        assert acquired
        repeated = await RequestProcessing(env.repo, env.runtime).reprocess_document(
            original.id, key
        )
        assert repeated.id == second.id
        retry = RequestProcessing(env.repo, env.runtime)
        current = await retry.retry(second.id, uuid4())
        assert current.status == "queued" and not retry.changed


async def test_http_files_audio_limit_and_sql_failure_keep_original(ingestion, monkeypatch):
    from sqlalchemy.exc import OperationalError

    env = ingestion
    app.dependency_overrides[get_workspace_runtime] = lambda: env.runtime
    app.dependency_overrides[require_authenticated] = lambda: "test-user"
    monkeypatch.setattr(routes, "get_repository", lambda: env.repo)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            file = await client.post(
                "/v2/documents/files",
                files={"file": ("note.md", b"Una nota", "text/markdown")},
                headers={"Idempotency-Key": str(uuid4())},
            )
            assert file.status_code == 202, file.text
            audio = await client.post(
                "/v2/audio-notes",
                files={"file": ("voice.webm", b"audio", "audio/webm")},
                headers={"Idempotency-Key": str(uuid4())},
            )
            assert audio.status_code == 202, audio.text
            assert audio.json()["processing"]["workflow"] == "audio"
            settings = routes.get_settings().model_copy(update={"audio_max_upload_bytes": 3})
            monkeypatch.setattr(routes, "get_settings", lambda: settings)
            too_large = await client.post(
                "/v2/audio-notes",
                files={"file": ("voice.webm", b"audio", "audio/webm")},
                headers={"Idempotency-Key": str(uuid4())},
            )
            assert too_large.status_code == 413
            key = str(uuid4())
            accept = SubmissionRepository.accept

            async def sql_failed(*args):
                raise OperationalError("commit", {}, RuntimeError("SQL unavailable"))

            monkeypatch.setattr(SubmissionRepository, "accept", sql_failed)
            failed = await client.post(
                "/v2/documents",
                json={"content": "No perder original"},
                headers={"Idempotency-Key": key},
            )
            assert failed.status_code == 503
            monkeypatch.setattr(SubmissionRepository, "accept", accept)
            recovered = await client.post(
                "/v2/documents",
                json={"content": "No perder original"},
                headers={"Idempotency-Key": key},
            )
            assert recovered.status_code == 202, recovered.text
            assert len(await env.runtime.document_store.list()) == 2
    finally:
        app.dependency_overrides.clear()


async def test_legacy_document_is_retired_and_explicit_retry_only_persists_original(ingestion):
    env = ingestion
    original, record = await submit(env)
    async with env.repo.sessions.begin() as session:
        old = await session.get(ProcessingRecord, record.id)
        old.workflow_version, old.stage = 1, "extraction"
    failed = await run_current(env, record)
    assert failed.status == "failed" and failed.error_code == "extraction_retired"
    assert env.providers.extractions == 0
    assert (await env.runtime.document_store.get(original.id)).content == original.content
    retry = await RequestProcessing(env.repo, env.runtime).retry(record.id, uuid4())
    assert retry.workflow_version == 2 and retry.stage == "document_persistence"
    assert (await run_current(env, retry)).status == "completed"
    assert env.providers.extractions == env.providers.embeddings == 0


async def test_legacy_audio_parent_recovers_retired_child_without_retranscribing(ingestion):
    env = ingestion
    note, parent = await SubmitAudioNote(env.submissions, env.runtime, 1024).execute(
        "voice.webm", "audio/webm", b"audio", None, uuid4()
    )
    async with env.repo.sessions.begin() as session:
        row = await session.get(ProcessingRecord, parent.id)
        row.workflow_version = 1
    waiting = await run_current(env, parent)
    child = await env.repo.child(waiting)
    async with env.repo.sessions.begin() as session:
        row = await session.get(ProcessingRecord, child.id)
        row.workflow_version, row.stage = 1, "extraction"
    assert (await run_current(env, child)).error_code == "extraction_retired"
    failed = await run_current(env, parent)
    assert failed.status == "failed" and not failed.retryable
    resumed = await RequestProcessing(env.repo, env.runtime).retry(parent.id, uuid4())
    assert resumed.status == "waiting"
    assert (await run_current(env, child)).status == "completed"
    assert (await run_current(env, parent)).status == "completed"
    assert env.providers.transcriptions == 1 and env.providers.extractions == 0
    assert (await env.runtime.audio_note_store.get(note.id)).document_error is None


async def test_archive_import_queues_v4_children_and_replays_without_duplicates(ingestion):
    from datetime import UTC, datetime

    from src.domain.documents import Document
    from src.use_cases.document_archive import DocumentArchive, DocumentArchiveTransfer
    from src.use_cases.process_document_extractors import ProcessDocumentExtractors

    env = ingestion
    originals = [
        Document(
            id=uuid4(),
            content="Documento archivado",
            source="archive",
            metadata={},
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        for _ in range(2)
    ]
    archive = DocumentArchive(
        exported_at=datetime.now(UTC), documents=[doc.model_dump() for doc in originals]
    )
    transfer = DocumentArchiveTransfer(
        env.runtime.document_store, env.repo, env.owner, graph=env.runtime.graph_store
    )
    assert await transfer.import_archive(archive) == {"imported": 2, "existing": 0, "total": 2}
    records = await env.repo.list_for_owner(env.owner)
    assert len(records) == 2
    registry = WorkflowRegistry()
    registry.register("document", 4, ProcessDocumentExtractors(env.factory).definition)
    executor = ExecuteProcessing(env.repo, registry)
    for record in records:
        assert record.workflow_version == 4 and record.status == "queued"
        await executor(record.id, record.generation)
        current = await env.repo.get(record.id, env.owner)
        assert current.status == "waiting"
        children = await env.repo.extractor_children(record.id, env.owner)
        assert {child.extractor_name for child in children} == {
            "emotions", "document_embeddings", "document_title"
        }
    assert await transfer.import_archive(archive) == {"imported": 0, "existing": 2, "total": 2}
    assert len(await env.repo.list_for_owner(env.owner)) == 8
    for original in originals:
        assert await env.runtime.document_store.get(original.id) == original


async def test_archive_pending_receipt_recovers_after_accept_failure(ingestion, monkeypatch):
    from datetime import UTC, datetime

    from sqlalchemy.exc import OperationalError

    from src.domain.documents import Document
    from src.use_cases.document_archive import DocumentArchive, DocumentArchiveTransfer

    env = ingestion
    original = Document(
        id=uuid4(),
        content="No perder",
        source="archive",
        metadata={},
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    archive = DocumentArchive(exported_at=datetime.now(UTC), documents=[original.model_dump()])
    transfer = DocumentArchiveTransfer(
        env.runtime.document_store, env.repo, env.owner, graph=env.runtime.graph_store
    )
    accept = SubmissionRepository.accept

    async def failed(*args):
        raise OperationalError("commit", {}, RuntimeError("SQL unavailable"))

    monkeypatch.setattr(SubmissionRepository, "accept", failed)
    with pytest.raises(OperationalError):
        await transfer.import_archive(archive)
    assert await env.runtime.document_store.get(original.id) == original
    monkeypatch.setattr(SubmissionRepository, "accept", accept)
    await recover_submissions(env.submissions, env.factory)
    records = await env.repo.list_for_owner(env.owner)
    assert len(records) == 1 and records[0].workflow_version == 4
    assert records[0].resource_id == original.id
    assert await transfer.import_archive(archive) == {"imported": 0, "existing": 1, "total": 1}
    assert len(await env.repo.list_for_owner(env.owner)) == 1
