"""Audio replies retain their invitation through durable uploads and worker retries."""

# ruff: noqa: F811
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select
from test_deferred_ingestion import ingestion, run_current  # noqa: F401
from test_processing_postgres import anyio_backend, store  # noqa: F401

from src.adapters.storage.postgres.invitation_models import Invitation, InvitationResponse
from src.api.routes import processing as routes
from src.bootstrap.auth import require_authenticated
from src.bootstrap.workspaces import get_workspace_runtime
from src.core.exteriorization.models import InvitationError
from src.main import app
from src.processing.models import ProcessingReceipt
from src.processing.submissions import SubmissionConflict
from src.use_cases.submit_processing import SubmitAudioNote, recover_submissions

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("PROCESSING_TEST_DATABASE_URL"), reason="requires isolated PostgreSQL"
    ),
]


@pytest.fixture
async def question(ingestion):
    env = ingestion
    now = datetime.now(UTC)
    invitation = Invitation(
        id=uuid4(),
        user_id=env.owner,
        kind="test",
        local_date=now.date(),
        timezone="UTC",
        scheduled_at=now,
        expires_at=now + timedelta(days=15),
        occurrence_key=str(uuid4()),
        candidate_id="audio-test",
        category="generic",
        question="¿Cómo te sentís?",
        engine_version="test",
        catalog_version="test",
    )
    async with env.repo.sessions.begin() as session:
        session.add(invitation)
    try:
        yield invitation.id
    finally:
        async with env.repo.sessions.begin() as session:
            await session.execute(
                delete(InvitationResponse).where(InvitationResponse.user_id == env.owner)
            )
            await session.execute(delete(Invitation).where(Invitation.id == invitation.id))


async def links(env):
    async with env.repo.sessions() as session:
        return list(
            await session.scalars(
                select(InvitationResponse).where(InvitationResponse.user_id == env.owner)
            )
        )


async def upload(env, question, key=None):
    return await SubmitAudioNote(env.submissions, env.runtime, 1024).execute(
        "voice.webm", "audio/webm", b"audio", None, key or uuid4(), invitation_id=question
    )


async def test_audio_answer_links_after_graph_persistence_and_retries_once(ingestion, question):
    env = ingestion
    key = uuid4()
    note, parent = await upload(env, question, key)
    assert note.invitation_id == question
    repeated, same_job = await upload(env, question, key)
    assert repeated.id == note.id and same_job.id == parent.id
    assert await links(env) == []
    env.graph.failure = "graph"
    retrying = await run_current(env, parent)
    assert retrying.status == "retrying"
    assert await links(env) == []
    waiting = await run_current(env, parent)
    assert waiting.status == "waiting"
    document = await env.runtime.document_store.get(note.id)
    assert document.content == "Quiero más autonomía."
    assert document.metadata["invitation_id"] == str(question)
    assert env.graph.documents[str(note.id)].metadata["invitation_id"] == str(question)
    assert [(link.document_id, link.invitation_id) for link in await links(env)] == [
        (note.id, question)
    ]
    await run_current(env, await env.repo.child(waiting))
    assert (await run_current(env, parent)).status == "completed"
    assert env.providers.transcriptions == 1
    assert len(await links(env)) == 1
    with pytest.raises(SubmissionConflict, match="idempotency_conflict"):
        await upload(env, None, key)


async def test_audio_answer_receipt_recovers_question_after_interrupted_accept(
    ingestion, question, monkeypatch
):
    env = ingestion
    accept = env.submissions.accept

    async def fail(receipt):
        raise RuntimeError("interrupted SQL accept")

    monkeypatch.setattr(env.submissions, "accept", fail)
    key = uuid4()
    with pytest.raises(RuntimeError, match="interrupted SQL accept"):
        await upload(env, question, key)
    receipt = await env.submissions.get(env.owner, "upload_audio", key)
    assert receipt.manifest["invitation_id"] == str(question)
    # Simulate recovery with only the durable original and receipt left on disk/SQL.
    note = await env.runtime.audio_note_store.get(receipt.resource_id)
    env.runtime.audio_note_store._metadata_path(note.id).unlink()
    monkeypatch.setattr(env.submissions, "accept", accept)
    await recover_submissions(env.submissions, env.factory)
    restored, parent = await upload(env, question, key)
    assert restored.invitation_id == question
    assert (await run_current(env, parent)).status == "waiting"
    assert len(await links(env)) == 1


async def test_audio_answer_rejects_foreign_question_before_reserving(ingestion, question):
    env = ingestion
    runtime = SimpleNamespace(context=SimpleNamespace(user_id=uuid4()))
    key = uuid4()
    with pytest.raises(InvitationError, match="invitation_not_found"):
        await SubmitAudioNote(env.submissions, runtime, 1024).execute(
            "voice.webm", "audio/webm", b"audio", None, key, invitation_id=question
        )
    assert await env.submissions.get(runtime.context.user_id, "upload_audio", key) is None
    assert await links(env) == []


async def test_audio_answer_link_rolls_back_with_failed_child_handoff(
    ingestion, question, monkeypatch
):
    env = ingestion
    note, parent = await upload(env, question)
    schedule = env.repo.schedule

    def interrupted(session, record):
        if record.parent_processing_id == parent.id:
            raise ConnectionError("interrupted child handoff")
        schedule(session, record)

    monkeypatch.setattr(env.repo, "schedule", interrupted)
    retrying = await run_current(env, parent)
    assert retrying.status == "retrying"
    assert await links(env) == []
    assert await env.repo.child(retrying) is None
    assert (await env.runtime.document_store.get(note.id)).metadata["invitation_id"] == str(
        question
    )
    monkeypatch.setattr(env.repo, "schedule", schedule)
    waiting = await run_current(env, parent)
    assert waiting.status == "waiting"
    assert len(await links(env)) == 1
    assert env.providers.transcriptions == 1


@pytest.mark.parametrize(
    "mode, expected",
    [
        ("answer", 202),
        ("ordinary", 202),
        ("missing", 404),
        ("foreign", 404),
        ("invalid", 422),
    ],
)
async def test_http_audio_invitation_contract(ingestion, question, monkeypatch, mode, expected):
    env = ingestion
    runtime = env.runtime
    if mode == "foreign":
        runtime = SimpleNamespace(
            **{
                **env.runtime.__dict__,
                "context": SimpleNamespace(user_id=uuid4()),
            }
        )
    app.dependency_overrides[get_workspace_runtime] = lambda: runtime
    app.dependency_overrides[require_authenticated] = lambda: "test-user"
    monkeypatch.setattr(routes, "get_repository", lambda: env.repo)
    value = "invalid" if mode == "invalid" else str(uuid4() if mode == "missing" else question)
    data = {} if mode == "ordinary" else {"invitation_id": value}
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v2/audio-notes",
                data=data,
                files={"file": ("voice.webm", b"audio", "audio/webm")},
                headers={"Idempotency-Key": str(uuid4())},
            )
            assert response.status_code == expected, response.text
            if expected == 202:
                audio = response.json()["audio_note"]
                assert audio["invitation_id"] == (None if mode == "ordinary" else str(question))
                snapshot = await client.get(f"/v2/audio-notes/{audio['id']}")
                assert snapshot.json()["invitation_id"] == audio["invitation_id"]
            else:
                async with env.repo.sessions() as session:
                    assert (
                        await session.scalar(
                            select(ProcessingReceipt.id).where(
                                ProcessingReceipt.user_id == env.owner
                            )
                        )
                        is None
                    )
    finally:
        app.dependency_overrides.clear()
