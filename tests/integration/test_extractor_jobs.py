"""Real SQL/graph: orthogonal jobs, shared document protection and partial retries."""

# ruff: noqa: F811
import asyncio
import os
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, update
from test_emotion_layer import layer_database  # noqa: F401
from test_emotion_processing import pipeline, run, upload  # noqa: F401
from test_processing_postgres import store  # noqa: F401

from src.auth.session import require_authenticated
from src.extractors.artifacts import LayerArtifacts
from src.extractors.base import Extractor
from src.extractors.contracts import ExtractorProfile, FrozenModel
from src.main import app
from src.processing.execution import ResourceBusy
from src.processing.models import ProcessingRecord
from src.processing.submissions import SubmissionConflict
from src.use_cases.delete_document import DeleteDocument
from src.use_cases.process_document_extractors import ProcessDocumentExtractors
from src.use_cases.process_extractor import ProcessExtractor
from src.use_cases.request_processing import RequestProcessing
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


class Metric(FrozenModel):
    value: int


@pytest.fixture
async def branches(pipeline):
    env = pipeline
    # The original fixture deliberately pins legacy v3 for its regression tests.
    from src.use_cases.submit_processing import workflow_config

    config = workflow_config()
    config["document_workflow_version"] = 4
    config["extractors"].append(
        {
            "name": "characters",
            "profile": {
                "id": "characters/v1",
                "instructions": "Count characters without a provider",
            },
        }
    )
    env.started = {name: asyncio.Event() for name in ("emotions", "characters")}
    env.release = asyncio.Event()
    env.block = set()
    env.metric_calls = 0
    env.metric_fail = False
    env.metric_permanent = False
    original = env.provider.extract

    async def emotion(document, profile):
        env.started["emotions"].set()
        if "emotions" in env.block:
            await env.release.wait()
        return await original(document, profile)

    env.provider.extract = emotion
    original_factory = env.registry.definitions[("document", 3)].run.__self__.extractor_factory

    class Characters(Extractor):
        name = "characters"

        async def produce(self, document):
            env.metric_calls += 1
            env.started["characters"].set()
            if "characters" in env.block:
                await env.release.wait()
            if env.metric_permanent:
                raise ValueError("unsupported metric")
            return Metric(value=len(document.content)), None

        def validate_payload(self, payload, document):
            result = Metric.model_validate(payload)
            assert result.value == len(document.content)
            return result

        async def write_layer(self, output, payload):
            if env.metric_fail:
                raise ConnectionError("isolated persistence failure")
            await env.client.command("CREATE VERTEX TYPE TestMetric IF NOT EXISTS")
            await env.client.command("CREATE PROPERTY TestMetric.id IF NOT EXISTS STRING")
            await env.client.command("CREATE INDEX IF NOT EXISTS ON TestMetric (id) UNIQUE")
            await env.client.command("CREATE EDGE TYPE HAS_TEST_METRIC IF NOT EXISTS")
            async with env.client.transaction() as transaction:
                response = await transaction.command(
                    """
                MATCH (document:Document {id:$document})
                MERGE (metric:TestMetric {id:$id})
                SET metric.document_id=$document, metric.layer='characters', metric.value=$value
                MERGE (document)-[edge:HAS_TEST_METRIC {id:$id}]->(metric)
                SET edge.layer='characters'
                RETURN metric.id AS id, metric.value AS value
                """,
                    {
                        "document": str(output.document_id),
                        "id": str(output.run_id),
                        "value": payload.value,
                    },
                    language="cypher",
                )
                assert response["result"] == [{"id": str(output.run_id), "value": payload.value}]

    def factory(runtime, spec, *, extracting):
        if spec["name"] == "emotions":
            return original_factory(runtime, spec, extracting=extracting)
        return Characters(
            runtime.document_store,
            LayerArtifacts(runtime.context.filesystem_root / "layers"),
            ExtractorProfile.model_validate(spec["profile"]),
        )

    env.registry.register(
        "document",
        4,
        ProcessDocumentExtractors(
            env.registry.definitions[("document", 3)].run.__self__.runtime_factory
        ).definition,
    )
    env.registry.register(
        "extractor",
        1,
        ProcessExtractor(
            env.registry.definitions[("document", 3)].run.__self__.runtime_factory, factory
        ).definition,
    )
    return env


async def fork(env):
    document, parent = await upload(env)
    assert parent.workflow_version == 4
    waiting = await run(env, parent)
    assert waiting.status == "waiting" and waiting.stage == "extractor_processing"
    children = await env.repo.extractor_children(parent.id, env.owner)
    assert {child.extractor_name for child in children} == {"emotions", "characters"}
    assert len({child.extraction_run_id for child in children}) == 2
    assert all(child.parent_processing_id == parent.id for child in children)
    assert env.provider.calls == 0 and env.metric_calls == 0
    assert (await env.repo.latest(env.owner, document.id, "document")).id == parent.id
    return document, waiting, {child.extractor_name: child for child in children}


async def test_two_layers_run_concurrently_block_delete_and_finish_coordinator(branches):
    env = branches
    document, parent, children = await fork(env)
    env.block = {"emotions", "characters"}
    tasks = [asyncio.create_task(run(env, child)) for child in children.values()]
    try:
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in env.started.values())), 5)
        # Both jobs entered their own algorithms while holding the same document guard.
        for child in children.values():
            async with env.repo.resource_guard(child.id) as locked:
                assert not locked
        async with env.repo.lock_resource(env.owner, document.id) as locked:
            assert not locked
        with pytest.raises(SubmissionConflict, match="processing_active"):
            await DeleteDocument(
                env.runtime.document_store, env.graph, env.repo, env.owner
            ).execute(document.id)
        assert (await env.repo.get(parent.id, env.owner)).status == "waiting"
    finally:
        env.release.set()
        results = await asyncio.gather(*tasks)
    assert all(result.status == "completed" for result in results)
    assert env.provider.calls == 1 and env.metric_calls == 1
    assert (await run(env, parent)).status == "completed"
    assert len((await env.client.query("SELECT FROM Emotion"))["result"]) == 2
    assert len((await env.client.query("SELECT FROM TestMetric"))["result"]) == 1
    # Duplicates cannot fork a second set or reexecute completed branches.
    await run(env, parent)
    for child in children.values():
        await run(env, child)
    assert len(await env.repo.extractor_children(parent.id, env.owner)) == 2
    assert env.provider.calls == 1 and env.metric_calls == 1
    await DeleteDocument(
        env.runtime.document_store,
        env.graph,
        env.repo,
        env.owner,
        LayerArtifacts(env.runtime.context.filesystem_root / "layers"),
    ).execute(document.id)
    assert not (await env.client.query("SELECT FROM Emotion"))["result"]
    assert not (await env.client.query("SELECT FROM TestMetric"))["result"]
    for child in children.values():
        await run(env, child)
    assert not (await env.client.query("SELECT FROM Emotion"))["result"]


async def test_parent_retry_only_restarts_failed_persistence_and_preserves_success(branches):
    env = branches
    _, parent, children = await fork(env)
    env.execute.max_attempts = 1
    env.metric_fail = True
    assert (await run(env, children["emotions"])).status == "completed"
    failed = await run(env, children["characters"])
    assert failed.status == "failed" and failed.stage == "persistence" and failed.retryable
    parent = await run(env, parent)
    assert (
        parent.status == "failed" and parent.error_code == "extractors_failed" and parent.retryable
    )
    success = await env.repo.get(children["emotions"].id, env.owner)
    env.metric_fail = False
    retry = await RequestProcessing(env.repo, env.runtime).retry(parent.id, uuid4())
    assert retry.status == "waiting"
    current = await env.repo.get(success.id, env.owner)
    assert (current.status, current.generation, current.attempts) == (
        success.status,
        success.generation,
        success.attempts,
    )
    assert (await run(env, failed)).status == "completed"
    assert (await run(env, parent)).status == "completed"
    assert env.provider.calls == 1 and env.metric_calls == 1


async def test_retry_one_branch_while_other_is_running_and_api_is_owner_scoped(branches):
    env = branches
    _, parent, children = await fork(env)
    env.block = {"emotions"}
    env.metric_fail = True
    env.execute.max_attempts = 1
    task = asyncio.create_task(run(env, children["emotions"]))
    try:
        await asyncio.wait_for(env.started["emotions"].wait(), 5)
        failed = await run(env, children["characters"])
        assert failed.status == "failed"
        env.metric_fail = False
        key = uuid4()
        requested = await RequestProcessing(env.repo, env.runtime).retry(failed.id, key)
        assert requested.status == "queued"
        duplicate = await RequestProcessing(env.repo, env.runtime).retry(failed.id, key)
        assert duplicate.generation == requested.generation
        assert (await run(env, requested)).status == "completed"
        assert (await env.repo.get(parent.id, env.owner)).status == "waiting"
        assert env.metric_calls == 1
        app.dependency_overrides.update(
            {require_authenticated: lambda: "owner", get_workspace_runtime: lambda: env.runtime}
        )
        from src.api.routes import processing as routes

        original = routes.get_repository
        routes.get_repository = lambda: env.repo
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="http://test"
            ) as client:
                response = await client.get(f"/processing/{parent.id}/extractors")
                assert response.status_code == 200
                assert {row["extractor_name"] for row in response.json()} == {
                    "emotions",
                    "characters",
                }
                assert all("config" not in row for row in response.json())
                assert (await client.get(f"/processing/{uuid4()}/extractors")).status_code == 404
                env.runtime.context.user_id = uuid4()
                assert (await client.get(f"/processing/{parent.id}/extractors")).status_code == 404
                env.runtime.context.user_id = env.owner
        finally:
            routes.get_repository = original
            app.dependency_overrides.clear()
    finally:
        env.release.set()
        await task
    assert (await run(env, parent)).status == "completed"


async def test_permanent_branch_failure_does_not_cancel_other_layer(branches):
    env = branches
    _, parent, children = await fork(env)
    env.metric_permanent = True
    results = await asyncio.gather(*(run(env, child) for child in children.values()))
    assert {result.status for result in results} == {"completed", "failed"}
    failed = next(result for result in results if result.status == "failed")
    assert not failed.retryable
    parent = await run(env, parent)
    assert parent.status == "failed" and not parent.retryable
    assert env.provider.calls == 1
    with pytest.raises(SubmissionConflict, match="processing_not_retryable"):
        await RequestProcessing(env.repo, env.runtime).retry(parent.id, uuid4())


async def test_expired_worker_does_not_block_other_layer_or_duplicate_artifact(branches):
    env = branches
    _, parent, children = await fork(env)
    env.block = {"emotions"}
    old = asyncio.create_task(run(env, children["emotions"]))
    try:
        await asyncio.wait_for(env.started["emotions"].wait(), 5)
        async with env.repo.sessions.begin() as session:
            await session.execute(
                update(ProcessingRecord)
                .where(ProcessingRecord.id == children["emotions"].id)
                .values(lease_expires_at=func.now() - timedelta(seconds=10))
            )
        assert await env.repo.recover() == 1
        recovered = await env.repo.get(children["emotions"].id, env.owner)
        with pytest.raises(ResourceBusy):
            await run(env, recovered)
        assert (await run(env, children["characters"])).status == "completed"
    finally:
        env.release.set()
        await old
    assert (await run(env, recovered)).status == "completed"
    assert env.provider.calls == 1
    assert (await run(env, parent)).status == "completed"


async def test_audio_retry_resumes_failed_layer_without_transcribing_or_repeating_success(branches):
    from src.use_cases.submit_processing import SubmitAudioNote

    env = branches
    env.execute.max_attempts = 1
    env.metric_fail = True
    note, audio = await SubmitAudioNote(env.submit, env.runtime, 1000).execute(
        "note.webm", "audio/webm", b"fixture", None, uuid4()
    )
    audio = await run(env, audio)
    coordinator = await env.repo.child(audio)
    await run(env, coordinator)
    children = await env.repo.extractor_children(coordinator.id, env.owner)
    for child in children:
        await run(env, child)
    assert (await run(env, coordinator)).status == "failed"
    audio = await run(env, audio)
    assert audio.status == "failed" and audio.retryable
    env.metric_fail = False
    await RequestProcessing(env.repo, env.runtime).retry(audio.id, uuid4())
    retrying = [
        child
        for child in await env.repo.extractor_children(coordinator.id, env.owner)
        if child.status == "queued"
    ]
    assert len(retrying) == 1 and retrying[0].extractor_name == "characters"
    await run(env, retrying[0])
    assert (await run(env, coordinator)).status == "completed"
    assert (await run(env, audio)).status == "completed"
    assert env.transcriber.calls == env.provider.calls == env.metric_calls == 1
    assert (await env.runtime.audio_note_store.get(note.id)).transcript == env.original.content


async def test_failed_fork_rolls_back_children_and_resumes_from_document_checkpoint(
    branches, monkeypatch
):
    from sqlalchemy.exc import SQLAlchemyError

    env = branches
    _, parent = await upload(env)
    original = env.repo.schedule

    def fail_schedule(session, record):
        if record.workflow == "extractor" and record.extractor_name == "characters":
            raise SQLAlchemyError("isolated outbox failure")
        original(session, record)

    monkeypatch.setattr(env.repo, "schedule", fail_schedule)
    with pytest.raises(SQLAlchemyError):
        await run(env, parent)
    assert not await env.repo.extractor_children(parent.id, env.owner)
    current = await env.repo.get(parent.id, env.owner)
    assert current.stage == "extractor_processing"  # The verified original is already durable.
    monkeypatch.setattr(env.repo, "schedule", original)
    async with env.repo.sessions.begin() as session:
        await session.execute(
            update(ProcessingRecord)
            .where(ProcessingRecord.id == parent.id)
            .values(lease_expires_at=func.now() - timedelta(seconds=10))
        )
    assert await env.repo.recover() == 1
    assert (await run(env, parent)).status == "waiting"
    children = await env.repo.extractor_children(parent.id, env.owner)
    assert len(children) == 2
    for child in children:
        assert (await run(env, child)).status == "completed"
    assert (await run(env, parent)).status == "completed"
    assert env.provider.calls == env.metric_calls == 1
