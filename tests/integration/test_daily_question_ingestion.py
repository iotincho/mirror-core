"""Variant provenance survives new/v1 receipts, text/audio recovery and HTTP acceptance."""

# ruff: noqa: F811 (imported pytest fixtures)

import os
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select, update
from test_deferred_ingestion import ingestion, run_current  # noqa: F401
from test_exteriorization_postgres import due_now
from test_processing_postgres import anyio_backend, store  # noqa: F401

from src.adapters.storage.postgres.invitation_models import Invitation, InvitationResponse
from src.adapters.storage.postgres.invitations import InvitationRepository
from src.bootstrap.acceptance import (
    SubmitAudioNote,
    SubmitDocument,
    audio_manifest,
    audio_metadata,
    document_identity,
    recover_submissions,
)
from src.bootstrap.auth import require_authenticated
from src.bootstrap.processing import get_repository
from src.bootstrap.public_api import app
from src.bootstrap.workspaces import get_workspace_runtime
from src.core.domain.documents import Document, NewDocument
from src.core.exteriorization.question_contracts import InvitationFeedbackChoice
from src.core.processing.submissions import SubmissionConflict, fingerprint
from src.use_cases.exteriorization.configure_invitations import ConfigureInvitations
from src.use_cases.exteriorization.schedule_invitations import ScheduleInvitations

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("PROCESSING_TEST_DATABASE_URL"),
        reason="requires isolated PostgreSQL",
    ),
]


@pytest.fixture
async def invitation(ingestion):
    env = ingestion
    repo = InvitationRepository(env.repo.sessions)
    service = ConfigureInvitations(repo)
    await service.configure(env.owner, True, "20:30", "UTC")
    assert await ScheduleInvitations(repo).execute(await due_now(repo, env.owner)) == 1
    async with repo.sessions() as session:
        identifier = await session.scalar(
            select(Invitation.id).where(Invitation.user_id == env.owner)
        )
    try:
        yield await service.get_invitation(env.owner, identifier), service
    finally:
        app.dependency_overrides.clear()
        async with repo.sessions.begin() as session:
            await session.execute(
                delete(InvitationResponse).where(InvitationResponse.user_id == env.owner)
            )
            await session.execute(delete(Invitation).where(Invitation.user_id == env.owner))


async def link(env):
    async with env.repo.sessions() as session:
        return await session.scalar(
            select(InvitationResponse).where(InvitationResponse.user_id == env.owner)
        )


async def test_text_keeps_selected_variant_even_after_topic_closes(ingestion, invitation):
    env = ingestion
    question, service = invitation
    variant = question.questions.question_groups[0].questions[2]
    await service.activity.feedback(
        env.owner,
        question.id,
        InvitationFeedbackChoice(
            invitation_question_id=variant.id,
            value="closed",
        ),
        uuid4(),
    )
    document = NewDocument(content="Una respuesta ficticia sobre cambios.")
    key = uuid4()
    case = SubmitDocument(env.submissions, env.runtime)
    original, job = await case.execute(
        document, key, invitation_id=question.id, invitation_question_id=variant.id
    )
    assert original.metadata["invitation_question_id"] == str(variant.id)
    assert (await link(env)).invitation_question_id == variant.id
    replay, same = await case.execute(
        document, key, invitation_id=question.id, invitation_question_id=variant.id
    )
    assert replay == original and same.id == job.id
    with pytest.raises(SubmissionConflict, match="idempotency_conflict"):
        await case.execute(document, key, invitation_id=question.id)
    await env.repo.mark_deleted(env.owner, original.id)
    assert await link(env) is None


async def test_omitted_and_explicit_default_have_the_same_new_request_identity(
    ingestion, invitation
):
    env = ingestion
    question, _ = invitation
    document = NewDocument(content="Mi respuesta ficticia.")
    key = uuid4()
    case = SubmitDocument(env.submissions, env.runtime)
    first, job = await case.execute(document, key, invitation_id=question.id)
    repeated, same = await case.execute(
        document,
        key,
        invitation_id=question.id,
        invitation_question_id=question.default_question_id,
    )
    assert repeated == first and same.id == job.id
    receipt = await env.submissions.get(env.owner, "upload_document", key)
    assert receipt.manifest["invitation_question_id"] == str(question.default_question_id)


@pytest.mark.parametrize("accepted", [False, True])
async def test_v1_document_receipt_keeps_original_hash_and_supports_default_replay(
    ingestion, invitation, accepted
):
    env = ingestion
    question, _ = invitation
    key = uuid4()
    document = NewDocument(
        id=uuid4(), content="Respuesta v1 ficticia.", metadata={"invitation_id": str(question.id)}
    )
    old_hash = document_identity(document)
    receipt = await env.submissions.reserve(
        user_id=env.owner,
        operation="upload_document",
        key=key,
        request_hash=old_hash,
        resource_kind="document",
        resource_id=document.id,
        config=env.config,
        manifest={"invitation_id": str(question.id)},
    )
    original = Document(
        **document.model_dump(exclude={"id"}), id=receipt.resource_id, created_at=receipt.created_at
    )
    await env.runtime.document_store.save(original)
    await env.graph.persist_document(original)
    if accepted:
        await env.submissions.accept(receipt)
        async with env.repo.sessions.begin() as session:
            await session.execute(
                update(InvitationResponse)
                .where(InvitationResponse.document_id == original.id)
                .values(invitation_question_id=None)
            )
    else:
        await env.submissions.release(receipt)
    case = SubmitDocument(env.submissions, env.runtime)
    restored, job = await case.execute(
        document,
        key,
        invitation_id=question.id,
        invitation_question_id=question.default_question_id,
    )
    assert restored == original
    current = await env.submissions.get(env.owner, "upload_document", key)
    assert current.request_hash == old_hash
    assert current.manifest == {"invitation_id": str(question.id)}
    if accepted:
        alias, same = await case.execute(document, uuid4(), invitation_id=question.id)
        assert alias == original and same.id == job.id
    with pytest.raises(SubmissionConflict, match="idempotency_conflict"):
        await case.execute(
            document,
            key,
            invitation_id=question.id,
            invitation_question_id=question.questions.question_groups[0].questions[2].id,
        )


async def test_audio_variant_recovers_after_interrupted_accept_and_graph_retry(
    ingestion, invitation, monkeypatch
):
    env = ingestion
    question, _ = invitation
    variant = question.questions.question_groups[0].questions[0]
    key = uuid4()
    accept = env.submissions.accept

    async def fail(receipt):
        raise RuntimeError("simulated SQL interruption")

    monkeypatch.setattr(env.submissions, "accept", fail)
    case = SubmitAudioNote(env.submissions, env.runtime, 1024)
    with pytest.raises(RuntimeError, match="simulated SQL interruption"):
        await case.execute(
            "voice.webm",
            "audio/webm",
            b"audio",
            None,
            key,
            invitation_id=question.id,
            invitation_question_id=variant.id,
        )
    receipt = await env.submissions.get(env.owner, "upload_audio", key)
    assert receipt.manifest["invitation_question_id"] == str(variant.id)
    env.runtime.audio_note_store._metadata_path(receipt.resource_id).unlink()
    monkeypatch.setattr(env.submissions, "accept", accept)
    await recover_submissions(env.submissions, env.factory)
    note, parent = await case.execute(
        "voice.webm",
        "audio/webm",
        b"audio",
        None,
        key,
        invitation_id=question.id,
        invitation_question_id=variant.id,
    )
    assert note.invitation_question_id == variant.id
    env.graph.failure = "graph"
    assert (await run_current(env, parent)).status == "retrying"
    waiting = await run_current(env, parent)
    assert waiting.status == "waiting"
    assert env.providers.transcriptions == 1
    original = await env.runtime.document_store.get(note.id)
    assert original.metadata["invitation_question_id"] == str(variant.id)
    assert (await link(env)).invitation_question_id == variant.id
    await run_current(env, await env.repo.child(waiting))
    assert (await run_current(env, parent)).status == "completed"
    with pytest.raises(SubmissionConflict, match="idempotency_conflict"):
        await case.execute(
            "voice.webm", "audio/webm", b"audio", None, key, invitation_id=question.id
        )


async def test_v1_audio_receipt_can_replay_with_explicit_default(ingestion, invitation):
    env = ingestion
    question, _ = invitation
    key = uuid4()
    manifest = {
        **audio_manifest("old.webm", "audio/webm", b"audio", None),
        "invitation_id": str(question.id),
    }
    receipt = await env.submissions.reserve(
        user_id=env.owner,
        operation="upload_audio",
        key=key,
        request_hash=fingerprint(manifest),
        resource_kind="audio",
        resource_id=None,
        config=env.config,
        manifest=manifest,
    )
    await env.runtime.audio_note_store.create(audio_metadata(receipt), b"audio")
    job = await env.submissions.accept(receipt)
    note, replay = await SubmitAudioNote(env.submissions, env.runtime, 1024).execute(
        "old.webm",
        "audio/webm",
        b"audio",
        None,
        key,
        invitation_id=question.id,
        invitation_question_id=question.default_question_id,
    )
    assert note.invitation_question_id is None and replay.id == job.id
    assert (await env.submissions.get(env.owner, "upload_audio", key)).request_hash == fingerprint(
        manifest
    )


@pytest.mark.parametrize("kind", ["text", "audio"])
async def test_http_selected_variant_and_invalid_membership(ingestion, invitation, kind):
    env = ingestion
    question, _ = invitation
    variant = question.questions.question_groups[1].questions[2]
    app.dependency_overrides[get_workspace_runtime] = lambda: env.runtime
    app.dependency_overrides[require_authenticated] = lambda: "test-user"
    app.dependency_overrides[get_repository] = lambda: env.repo
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:

        async def request(invitation_id, question_id):
            reference = {"invitation_question_id": str(question_id)}
            if invitation_id is not None:
                reference["invitation_id"] = str(invitation_id)
            if kind == "text":
                return await client.post(
                    "/v2/documents",
                    json={**reference, "content": "Respuesta ficticia HTTP."},
                    headers={"Idempotency-Key": str(uuid4())},
                )
            return await client.post(
                "/v2/audio-notes",
                data=reference,
                files={"file": ("voice.webm", b"audio", "audio/webm")},
                headers={"Idempotency-Key": str(uuid4())},
            )

        assert (await request(None, variant.id)).status_code == 422
        assert (await request(question.id, uuid4())).status_code == 404
        result = await request(question.id, variant.id)
        assert result.status_code == 202, result.text
        body = result.json()
        if kind == "text":
            assert body["document"]["metadata"]["invitation_question_id"] == str(variant.id)
        else:
            assert body["audio_note"]["invitation_question_id"] == str(variant.id)


async def test_late_answer_to_another_depth_updates_same_topic_without_lifting_closure(
    ingestion, invitation
):
    from src.adapters.storage.postgres.invitation_question_models import InvitationInteractionRecord
    from src.core.exteriorization.curated_questions import catalog_topic_id, catalog_topics
    from src.core.exteriorization.question_contracts import InvitationInteractions

    env = ingestion
    question, service = invitation
    middle, deep = question.questions.question_groups[0].questions[1:]
    await service.activity.interactions(
        env.owner,
        question.id,
        InvitationInteractions(
            events=[
                dict(
                    event_id=uuid4(),
                    invitation_question_id=middle.id,
                    kind="shown",
                )
            ]
        ),
        uuid4(),
    )
    async with env.repo.sessions.begin() as session:
        await session.execute(
            update(InvitationInteractionRecord)
            .where(
                InvitationInteractionRecord.user_id == env.owner,
            )
            .values(recorded_at=datetime(2026, 1, 1, tzinfo=UTC))
        )
    topic_id = catalog_topic_id(env.owner, question.candidate_id)
    async with service.repository.transaction() as tx:
        before = next(
            fact
            for fact in await tx.catalog_state(env.owner, catalog_topics(env.owner))
            if fact.topic.id == topic_id
        )
    assert before.last_shown_at is not None and not before.answered
    await service.activity.feedback(
        env.owner,
        question.id,
        InvitationFeedbackChoice(
            invitation_question_id=deep.id,
            value="closed",
        ),
        uuid4(),
    )
    await SubmitDocument(env.submissions, env.runtime).execute(
        NewDocument(content="Una respuesta ficticia tardía."),
        uuid4(),
        invitation_id=question.id,
        invitation_question_id=deep.id,
    )
    async with service.repository.transaction() as tx:
        after = next(
            fact
            for fact in await tx.catalog_state(env.owner, catalog_topics(env.owner))
            if fact.topic.id == topic_id
        )
    assert after.answered and after.topic.status == "closed"
