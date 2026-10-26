"""Title jobs against isolated PostgreSQL and ArcadeDB, using a deterministic provider."""

# ruff: noqa: F811
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from test_emotion_layer import layer_database  # noqa: F401
from test_emotion_processing import pipeline, run, upload  # noqa: F401
from test_processing_postgres import store  # noqa: F401

from src.adapters.storage.arcadedb.document_titles import ArcadeDBDocumentTitleStore
from src.adapters.storage.filesystem.layer_artifacts import LayerArtifacts
from src.bootstrap.acceptance import SubmitAudioNote, recover_submissions
from src.bootstrap.archives import DocumentArchive, DocumentArchiveTransfer
from src.bootstrap.processing import build_document_coordinator as ProcessDocumentExtractors
from src.bootstrap.processing import build_extractor_processor as ProcessExtractor
from src.bootstrap.processing import build_processing_requests as RequestProcessing
from src.core.extractors.contracts import ExtractorProfile, ProviderMetadata
from src.core.extractors.document_title import TITLE_PROFILE, DocumentTitle
from src.core.processing.submissions import fingerprint
from src.use_cases.extraction.document_title import DocumentTitleExtractor

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
async def titled(pipeline, monkeypatch):
    env = pipeline
    config = env.registry.definitions[("document", 3)].run.__self__
    runtime_factory, emotion_factory = config.runtime_factory, config.extractor_factory
    # Reuse the fixture's accepted emotion configuration and add the independent title job.
    from src.bootstrap.acceptance import workflow_config

    accepted = workflow_config()
    accepted["document_workflow_version"] = 4
    accepted["extractors"].append(
        {
            "name": "document_title",
            "profile": TITLE_PROFILE.model_dump(),
            "provider": "fake",
            "model": "title-test",
        }
    )
    env.title_provider = SimpleNamespace(
        provider_name="fake",
        model_name="title-test",
        extract=AsyncMock(
            return_value=(
                DocumentTitle(title="Alegría y miedo en un día"),
                ProviderMetadata(provider="fake", model="title-test"),
            )
        ),
    )
    env.title_store = ArcadeDBDocumentTitleStore(env.client)
    env.title_write = env.title_store.update_title
    env.title_store.update_title = AsyncMock(side_effect=env.title_write)

    def factory(runtime, spec, *, extracting):
        if spec["name"] == "emotions":
            return emotion_factory(runtime, spec, extracting=extracting)
        return DocumentTitleExtractor(
            runtime.document_store,
            LayerArtifacts(runtime.context.filesystem_root / "layers"),
            env.title_store,
            env.title_provider if extracting else None,
            profile=ExtractorProfile.model_validate(spec["profile"]),
        )

    env.registry.register("document", 4, ProcessDocumentExtractors(runtime_factory).definition)
    env.registry.register("extractor", 1, ProcessExtractor(runtime_factory, factory).definition)
    env.runtime_factory = runtime_factory
    monkeypatch.setattr("src.bootstrap.archives.workflow_config", lambda: accepted)
    return env


async def children(env, parent):
    parent = await run(env, parent)
    assert parent.status == "waiting"
    parts = await env.repo.extractor_children(parent.id, env.owner)
    return parent, {part.extractor_name: part for part in parts}


async def graph_title(env, document):
    rows = (
        await env.client.query(
            "SELECT title, content FROM Document WHERE id=:id", {"id": str(document.id)}
        )
    )["result"]
    assert len(rows) == 1 and rows[0]["content"] == document.content
    return rows[0].get("title")


async def test_title_available_before_emotions_and_replay_never_repeats_provider(titled):
    env = titled
    document, parent = await upload(env)
    assert document.title is None and env.title_provider.extract.await_count == 0
    parent, parts = await children(env, parent)
    title = await run(env, parts["document_title"])
    assert title.status == "completed"
    current = await env.runtime.document_store.get(document.id)
    assert current.title == "Alegría y miedo en un día"
    assert await graph_title(env, document) == current.title
    assert current.model_dump(exclude={"title"}) == document.model_dump(exclude={"title"})
    assert (await env.repo.get(parts["emotions"].id, env.owner)).status == "queued"
    assert env.provider.calls == 0
    await run(env, title)
    assert env.title_provider.extract.await_count == 1
    await run(env, parts["emotions"])
    assert (await run(env, parent)).status == "completed"


async def test_failed_graph_projection_retries_only_title_persistence(titled):
    env = titled
    document, parent = await upload(env)
    parent, parts = await children(env, parent)
    await run(env, parts["emotions"])
    env.title_store.update_title.side_effect = ConnectionError("isolated graph failure")
    title = await run(env, parts["document_title"])
    assert title.status == "retrying" and title.stage == "persistence"
    assert (await env.runtime.document_store.get(document.id)).title == "Alegría y miedo en un día"
    assert await graph_title(env, document) is None
    env.title_store.update_title.side_effect = env.title_write
    assert (await run(env, title)).status == "completed"
    assert env.title_provider.extract.await_count == 1 and env.provider.calls == 1
    assert (await run(env, parent)).status == "completed"


async def test_audio_title_reprocess_and_import_keep_transcript_and_existing_title(titled):
    env = titled
    authored = datetime(2024, 6, 12, tzinfo=UTC)
    note, audio = await SubmitAudioNote(env.submit, env.runtime, 1000).execute(
        "voice.wav", "audio/wav", b"test-audio", authored, uuid4()
    )
    audio = await run(env, audio)
    parent = await env.repo.get(audio.child_processing_id, env.owner)
    parent, parts = await children(env, parent)
    for part in parts.values():
        await run(env, part)
    assert (await run(env, parent)).status == "completed"
    assert (await run(env, audio)).status == "completed"
    doc = await env.runtime.document_store.get(note.id)
    assert doc.title == "Alegría y miedo en un día" and doc.authored_at == authored
    assert env.transcriber.calls == 1
    reprocess = await RequestProcessing(env.repo, env.runtime).reprocess_document(doc.id, uuid4())
    reprocess, parts = await children(env, reprocess)
    for part in parts.values():
        await run(env, part)
    await run(env, reprocess)
    assert env.title_provider.extract.await_count == 1 and env.transcriber.calls == 1
    transfer = DocumentArchiveTransfer(
        env.runtime.document_store, env.repo, env.owner, env.submit, graph=env.runtime.graph_store
    )
    backup = DocumentArchive(
        exported_at=datetime.now(UTC),
        documents=[doc.model_copy(update={"title": None}).model_dump()],
    )
    assert (await transfer.import_archive(backup))["existing"] == 1
    assert (await env.runtime.document_store.get(doc.id)).title == doc.title
    assert (await transfer.import_archive(await transfer.export()))["existing"] >= 1


async def test_interrupted_import_recovery_and_legacy_receipt_replay(titled):
    env = titled
    doc = env.original.model_copy(update={"title": None, "id": uuid4()})
    from src.bootstrap.acceptance import imported_document_identity, workflow_config

    receipt = await env.submit.reserve(
        user_id=env.owner,
        operation="import_document",
        key=doc.id,
        request_hash=imported_document_identity(doc),
        resource_kind="document",
        resource_id=doc.id,
        config=workflow_config(),
        manifest={"archive_identity": "original/1"},
    )
    await env.runtime.document_store.save(doc)
    await env.runtime.document_store.update_title(doc.id, "Título conservado")
    await env.submit.release(receipt)
    await recover_submissions(env.submit, env.runtime_factory)
    recovered = await env.submit.get(env.owner, "import_document", doc.id)
    assert recovered.accepted_at is not None
    parent = await env.repo.get(recovered.processing_id, env.owner)
    parent, parts = await children(env, parent)
    for part in parts.values():
        await run(env, part)
    await run(env, parent)
    assert env.title_provider.extract.await_count == 0
    # Simulate an accepted pre-title-feature import receipt, whose hash included title.
    from src.adapters.storage.postgres.models import ProcessingReceipt

    async with env.repo.sessions.begin() as session:
        legacy = await session.get(ProcessingReceipt, recovered.id)
        legacy.request_hash = fingerprint(doc.model_dump(mode="json"))
        legacy.manifest = {}
    transfer = DocumentArchiveTransfer(
        env.runtime.document_store, env.repo, env.owner, env.submit, graph=env.runtime.graph_store
    )
    backup = DocumentArchive(exported_at=datetime.now(UTC), documents=[doc.model_dump()])
    assert (await transfer.import_archive(backup))["existing"] == 1
    assert (await transfer.import_archive(await transfer.export()))["existing"] >= 1
    assert (await env.runtime.document_store.get(doc.id)).title == "Título conservado"
