"""Text/audio handoff and durable parallel embedding jobs with real SQL and graph."""

# ruff: noqa: F811
import os
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest
from test_document_embedding_layer import Provider
from test_emotion_layer import layer_database  # noqa: F401
from test_emotion_processing import pipeline, run, upload  # noqa: F401
from test_processing_postgres import store  # noqa: F401

from src.extractors.document_embedding_store import ArcadeDBDocumentEmbeddingStore
from src.extractors.document_embeddings import EMBEDDINGS_PROFILE, EmbeddingConfiguration
from src.processing.workflows import workflow_extractor
from src.use_cases.process_document_extractors import ProcessDocumentExtractors
from src.use_cases.process_extractor import ProcessExtractor

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


@pytest.mark.parametrize("source", ["text", "audio"])
async def test_note_upload_runs_embeddings_and_resumes_ambiguous_persistence(
    pipeline, monkeypatch, source
):
    from src.use_cases.request_processing import RequestProcessing
    from src.use_cases.submit_processing import SubmitAudioNote, workflow_config

    env = pipeline
    configuration = EmbeddingConfiguration(segmentation_model="test", dimensions=3)
    config = workflow_config()
    config["document_workflow_version"] = 4
    config["extractors"].append(
        {
            "name": "document_embeddings",
            "profile": EMBEDDINGS_PROFILE.model_dump(),
            "configuration": configuration.model_dump(),
            "force": False,
        }
    )
    provider = Provider()
    monkeypatch.setattr(
        "src.processing.workflows.embedding_provider_configured", lambda model: provider
    )
    monkeypatch.setattr(
        "src.processing.workflows.emotion_provider_configured", lambda *args: env.provider
    )

    @asynccontextmanager
    async def runtime_factory(user_id):
        assert user_id == env.owner
        yield env.runtime

    env.registry.register("document", 4, ProcessDocumentExtractors(runtime_factory).definition)
    env.registry.register(
        "extractor", 1, ProcessExtractor(runtime_factory, workflow_extractor).definition
    )
    audio_parent = None
    if source == "text":
        document, parent = await upload(env)
    else:
        note, audio_parent = await SubmitAudioNote(env.submit, env.runtime, 1000).execute(
            "note.webm", "audio/webm", b"isolated fixture", None, uuid4()
        )
        audio_parent = await run(env, audio_parent)
        parent = await env.repo.child(audio_parent)
        document = await env.runtime.document_store.get(parent.resource_id)
        assert env.transcriber.calls == 1

    parent = await run(env, parent)
    assert parent.status == "waiting"
    children = await env.repo.extractor_children(parent.id, env.owner)
    assert {child.extractor_name for child in children} == {"emotions", "document_embeddings"}
    persist = ArcadeDBDocumentEmbeddingStore.persist
    attempts = 0

    async def ambiguous(self, output, payload):
        nonlocal attempts
        await persist(self, output, payload)
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("commit response lost")

    monkeypatch.setattr(ArcadeDBDocumentEmbeddingStore, "persist", ambiguous)
    embedding = next(child for child in children if child.extractor_name == "document_embeddings")
    emotion = next(child for child in children if child.extractor_name == "emotions")
    embedding = await run(env, embedding)
    assert embedding.stage == "persistence" and embedding.status == "retrying"
    assert provider.calls == 1
    emotion = await run(env, emotion)
    assert emotion.status == "completed"
    embedding = await run(env, embedding)
    assert embedding.status == "completed"
    assert provider.calls == 1 and env.provider.calls == 1
    parent = await run(env, parent)
    assert parent.status == "completed"
    results = await ArcadeDBDocumentEmbeddingStore(env.client).search([1, 0, 0], configuration)
    assert [match.document_id for match in results] == [document.id]

    if audio_parent is not None:
        assert (await run(env, audio_parent)).status == "completed"
        original_audio = await env.runtime.audio_note_store.get(note.id)
        assert original_audio.transcript == env.original.content
        assert original_audio.document_id == document.id
        assert env.transcriber.calls == 1

    reprocess = await RequestProcessing(env.repo, env.runtime).reprocess_document(
        document.id, uuid4()
    )
    assert (
        next(
            spec for spec in reprocess.config["extractors"] if spec["name"] == "document_embeddings"
        )["force"]
        is True
    )
    assert config["extractors"][-1]["force"] is False
    reprocess = await run(env, reprocess)
    for child in await env.repo.extractor_children(reprocess.id, env.owner):
        assert (await run(env, child)).status == "completed"
    assert (await run(env, reprocess)).status == "completed"
    assert provider.calls == 2
