"""Uploads, durable checkpoints and audio handoff with real SQL and graph stores."""

# ruff: noqa: F811
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4, uuid5

import pytest
from sqlalchemy import update
from test_emotion_layer import layer_database  # noqa: F401
from test_processing_postgres import store  # noqa: F401

from src.domain.documents import NewDocument
from src.extractors.artifacts import LayerArtifacts
from src.extractors.contracts import ExtractorProfile
from src.extractors.emotions import EMOTIONS_PROFILE, EmotionExtractor
from src.processing.execution import ExecuteProcessing, WorkflowRegistry
from src.processing.models import ProcessingRecord
from src.processing.submissions import SubmissionRepository
from src.services.audio_note_store import FileAudioNoteStore
from src.use_cases.process_audio_note import ProcessAudioNote
from src.use_cases.process_document import ProcessDocument
from src.use_cases.process_document_layers import ProcessDocumentLayers
from src.use_cases.request_processing import RequestProcessing
from src.use_cases.submit_processing import SubmitAudioNote, SubmitDocument, workflow_config

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
async def pipeline(store, layer_database, monkeypatch):
    repo, owner = store
    extractor, original, client, provider, graph = layer_database
    root = extractor.artifacts.root.parent
    runtime = SimpleNamespace(
        context=SimpleNamespace(user_id=owner, filesystem_root=root),
        document_store=extractor.documents,
        graph_store=graph,
        audio_note_store=FileAudioNoteStore(root / "audio-notes"),
    )
    config = workflow_config()
    config["extractors"] = [
        {
            "name": "emotions",
            "profile": EMOTIONS_PROFILE.model_dump(),
            "provider": "fake",
            "model": "test",
        }
    ]
    monkeypatch.setattr("src.use_cases.submit_processing.workflow_config", lambda: config)
    monkeypatch.setattr("src.use_cases.request_processing.workflow_config", lambda: config)

    @asynccontextmanager
    async def runtime_factory(user_id):
        assert user_id == owner
        yield runtime

    def factory(runtime, specification, *, extracting):
        return EmotionExtractor(
            runtime.document_store,
            LayerArtifacts(root / "layers"),
            graph.database_client,
            provider if extracting else None,
            profile=ExtractorProfile.model_validate(specification["profile"]),
        )

    class Transcriber:
        provider_name, model_name = "fake", "test"
        calls = 0

        async def transcribe(self, path):
            self.calls += 1
            return original.content

    transcriber = Transcriber()
    registry = WorkflowRegistry()
    registry.register("document", 2, ProcessDocument(runtime_factory).definition)
    registry.register("document", 3, ProcessDocumentLayers(runtime_factory, factory).definition)
    registry.register(
        "audio", 2, ProcessAudioNote(runtime_factory, lambda config: transcriber).definition
    )
    return SimpleNamespace(
        repo=repo,
        owner=owner,
        runtime=runtime,
        provider=provider,
        original=original,
        graph=graph,
        client=client,
        registry=registry,
        transcriber=transcriber,
        submit=SubmissionRepository(repo),
        execute=ExecuteProcessing(repo, registry),
    )


async def run(env, record):
    current = await env.repo.get(record.id, env.owner)
    async with env.repo.sessions.begin() as session:
        # Automatic backoff is bypassed only in this isolated test.
        await session.execute(
            update(ProcessingRecord)
            .where(ProcessingRecord.id == current.id)
            .values(available_at=record.created_at)
        )
    await env.execute(current.id, current.generation)
    return await env.repo.get(current.id, env.owner)


async def upload(env, key=None):
    return await SubmitDocument(env.submit, env.runtime).execute(
        NewDocument(content=env.original.content), key or uuid4()
    )


async def test_note_upload_extracts_persists_and_replay_does_not_repeat_provider(pipeline):
    env = pipeline
    key = uuid4()
    document, record = await upload(env, key)
    assert record.workflow_version == 3
    assert env.provider.calls == 0  # Upload request does not execute the model.
    completed = await run(env, record)
    assert completed.status == "completed" and completed.stage == "done"
    assert env.provider.calls == 1
    output = await LayerArtifacts(env.runtime.context.filesystem_root / "layers").get(
        document.id, uuid5(record.id, "emotions")
    )
    assert output is not None and output.profile.id == "emotions/v1"
    nodes = (
        await env.client.query(
            "SELECT FROM Emotion WHERE document_id=:id", {"id": str(document.id)}
        )
    )["result"]
    assert len(nodes) == 2
    _, duplicate = await upload(env, key)
    assert duplicate.id == record.id
    await run(env, record)
    assert env.provider.calls == 1


async def test_persistence_failure_recovers_without_provider_or_reextraction(pipeline):
    env = pipeline
    document, record = await upload(env)
    original_definition = env.registry.get(record)
    original_factory = original_definition.run.__self__.extractor_factory
    failed = False

    def factory(runtime, spec, *, extracting):
        nonlocal failed
        extractor = original_factory(runtime, spec, extracting=extracting)
        if not extracting and not failed:
            failed = True

            async def unavailable(output):
                raise ConnectionError("isolated graph outage")

            extractor.persist = unavailable
        return extractor

    original_definition.run.__self__.extractor_factory = factory
    retrying = await run(env, record)
    assert retrying.status == "retrying" and retrying.stage == "layer_persistence"
    assert env.provider.calls == 1

    def persistence_only(runtime, spec, *, extracting):
        assert not extracting
        return original_factory(runtime, spec, extracting=False)

    original_definition.run.__self__.extractor_factory = persistence_only
    completed = await run(env, retrying)
    assert completed.status == "completed" and env.provider.calls == 1
    assert (await env.runtime.document_store.get(document.id)).content == document.content


async def test_transcribed_audio_uses_emotion_child_and_keeps_transcript(pipeline):
    env = pipeline
    note, parent = await SubmitAudioNote(env.submit, env.runtime, 1000).execute(
        "note.webm", "audio/webm", b"isolated fixture", None, uuid4()
    )
    waiting = await run(env, parent)
    child = await env.repo.child(waiting)
    assert child.workflow_version == 3
    assert waiting.status == "waiting" and env.transcriber.calls == 1
    completed = await run(env, child)
    assert completed.status == "completed" and env.provider.calls == 1
    await run(env, waiting)
    note = await env.runtime.audio_note_store.get(note.id)
    assert note.transcript == env.original.content and note.document_id == child.resource_id
    assert env.transcriber.calls == 1


async def test_reprocess_uses_new_configuration_but_old_job_remains_capture_only(pipeline):
    env = pipeline
    document, record = await upload(env)
    async with env.repo.sessions.begin() as session:
        await session.execute(
            update(ProcessingRecord)
            .where(ProcessingRecord.id == record.id)
            .values(workflow_version=2, config={})
        )
    assert (await run(env, record)).status == "completed"
    assert env.provider.calls == 0
    reprocess = await RequestProcessing(env.repo, env.runtime).reprocess_document(
        document.id, uuid4()
    )
    assert reprocess.workflow_version == 3
    assert (await run(env, reprocess)).status == "completed"
    assert env.provider.calls == 1
