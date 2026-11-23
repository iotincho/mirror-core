"""Journal provenance across SQL acceptance, originals, audio handoff and replay."""

# ruff: noqa: F811
import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url
from test_deferred_ingestion import ingestion, run_current  # noqa: F401
from test_processing_postgres import anyio_backend, store  # noqa: F401

from src.adapters.storage.postgres.accounts import User
from src.adapters.storage.postgres.invitation_models import Invitation
from src.adapters.storage.postgres.journal_models import JournalEntryRecord, JournalInvitationRecord
from src.adapters.storage.postgres.journals import PostgresJournals
from src.adapters.storage.postgres.models import ProcessingReceipt, ProcessingRecord
from src.adapters.storage.postgres.workspace_models import UserWorkspace
from src.bootstrap.acceptance import (
    SubmitAudioNote,
    SubmitDocument,
    recover_submissions,
)
from src.bootstrap.archives import DocumentArchiveTransfer
from src.bootstrap.auth import require_authenticated
from src.bootstrap.processing import get_repository
from src.bootstrap.public_api import app
from src.bootstrap.workspaces import get_workspace_runtime
from src.core.documents.archive import ArchivedDocument, DocumentArchive
from src.core.domain.documents import NewDocument
from src.core.journals.contracts import ActivateRun, AdjustRun, ChangeLifecycle
from src.core.journals.entries import metadata_reference, reference_metadata
from src.core.journals.errors import JournalError
from src.core.journals.templates import PREPARATION_TEMPLATE
from src.core.processing.errors import StorageUnavailable
from src.core.processing.submissions import SubmissionConflict
from src.use_cases.journals.manage import ManageJournals
from src.use_cases.journals.query import QueryJournals

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("PROCESSING_TEST_DATABASE_URL"),
        reason="requires isolated processing PostgreSQL",
    ),
]


@pytest.fixture
async def journal(ingestion):
    env = ingestion
    assert make_url(os.environ["PROCESSING_TEST_DATABASE_URL"]).database.startswith("journals_test")
    repository = PostgresJournals(env.repo.sessions)
    await repository.install_template(PREPARATION_TEMPLATE)
    manage = ManageJournals(repository, enabled=True)
    receipt = await manage.activate(
        env.owner,
        ActivateRun(
            template_id=PREPARATION_TEMPLATE.id,
            template_version=1,
            timezone="UTC",
        ),
        uuid4(),
    )
    context = await QueryJournals(repository, enabled=True).resolve(env.owner, datetime.now(UTC))
    env.journal_manage, env.journal_receipt = manage, receipt
    try:
        yield context.reference
    finally:
        app.dependency_overrides.clear()


async def entries(env):
    async with env.repo.sessions() as session:
        return list(
            await session.scalars(
                select(JournalEntryRecord).where(
                    JournalEntryRecord.owner_id == env.owner,
                )
            )
        )


async def close_journal(env):
    await env.journal_manage.lifecycle(
        env.owner,
        env.journal_receipt.run_id,
        ChangeLifecycle(action="close", expected_revision=1),
        uuid4(),
    )


async def invitation(env, reference=None):
    now = datetime.now(UTC)
    row = Invitation(
        id=uuid4(),
        user_id=env.owner,
        kind="test",
        local_date=now.date(),
        timezone="UTC",
        scheduled_at=now,
        expires_at=now + timedelta(days=1),
        occurrence_key=str(uuid4()),
        candidate_id="synthetic",
        category="generic",
        question="¿Qué querés explorar hoy?",
        engine_version="test",
        catalog_version="1",
    )
    async with env.repo.sessions.begin() as session:
        session.add(row)
        await session.flush()
        if reference is not None:
            session.add(
                JournalInvitationRecord(
                    invitation_id=row.id,
                    owner_id=env.owner,
                    run_id=reference.run_id,
                    revision=reference.run_revision,
                    stage_id=reference.stage_id,
                )
            )
    return row.id


async def test_text_keeps_historical_capture_after_close_and_replays_by_key_and_resource_id(
    ingestion,
    journal,
):
    env, reference = ingestion, journal
    await close_journal(env)
    document = NewDocument(id=uuid4(), content="Una exploración sintética.")
    key = uuid4()
    case = SubmitDocument(env.submissions, env.runtime)
    original, record = await case.execute(document, key, journal_reference=reference)
    assert metadata_reference(original.metadata) == reference
    stored = await entries(env)
    assert len(stored) == 1 and stored[0].revision == 1 and stored[0].stage_id == reference.stage_id
    for replay_key in (key, uuid4()):
        replay, same = await case.execute(document, replay_key, journal_reference=reference)
        assert replay == original and same.id == record.id
    with pytest.raises(SubmissionConflict, match="idempotency_conflict"):
        await case.execute(document, key)
    assert env.providers.transcriptions == env.providers.extractions == 0


async def test_free_notes_stay_free_and_a_previous_receipt_cannot_acquire_a_journal(
    ingestion, journal
):
    env = ingestion
    document, key = NewDocument(content="Una nota libre sintética."), uuid4()
    original, _ = await SubmitDocument(env.submissions, env.runtime).execute(document, key)
    assert metadata_reference(original.metadata) is None
    with pytest.raises(SubmissionConflict, match="idempotency_conflict"):
        await SubmitDocument(env.submissions, env.runtime).execute(
            document, key, journal_reference=journal
        )
    assert await entries(env) == []


@pytest.mark.parametrize("mismatch", ["run_id", "stage_id", "run_revision"])
async def test_foreign_or_invalid_reference_is_rejected_before_any_reservation(
    ingestion, journal, mismatch
):
    env = ingestion
    bad = journal.model_copy(update={mismatch: 999 if mismatch == "run_revision" else uuid4()})
    with pytest.raises(JournalError, match="journal_reference_not_found"):
        await SubmitDocument(env.submissions, env.runtime).execute(
            NewDocument(content="Contenido sintético"),
            uuid4(),
            journal_reference=bad,
        )
    async with env.repo.sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ProcessingReceipt)
                .where(
                    ProcessingReceipt.user_id == env.owner,
                )
            )
            == 0
        )


async def test_invitation_derives_context_and_rejects_free_or_different_associations(
    ingestion, journal
):
    env = ingestion
    linked, free = await invitation(env, journal), await invitation(env)
    doc, _ = await SubmitDocument(env.submissions, env.runtime).execute(
        NewDocument(content="Respuesta contextual sintética"),
        uuid4(),
        invitation_id=linked,
    )
    assert metadata_reference(doc.metadata) == journal
    with pytest.raises(JournalError, match="journal_reference_conflict"):
        await SubmitDocument(env.submissions, env.runtime).execute(
            NewDocument(content="Respuesta contradictoria"),
            uuid4(),
            invitation_id=free,
            journal_reference=journal,
        )


async def test_accept_failure_rolls_back_entry_job_and_outbox_then_recovers_without_provider(
    ingestion,
    journal,
    monkeypatch,
):
    from src.adapters.storage.postgres import journal_entries

    env, key = ingestion, uuid4()
    original_bind = journal_entries.bind_journal_entry

    async def fail(*args):
        await original_bind(*args)
        raise StorageUnavailable("synthetic interruption after membership")

    monkeypatch.setattr(journal_entries, "bind_journal_entry", fail)
    with pytest.raises(StorageUnavailable):
        await SubmitDocument(env.submissions, env.runtime).execute(
            NewDocument(content="Original que sobrevive a un fallo SQL"),
            key,
            journal_reference=journal,
        )
    assert len(await env.runtime.document_store.list()) == 1
    assert await entries(env) == []
    async with env.repo.sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ProcessingRecord)
                .where(
                    ProcessingRecord.user_id == env.owner,
                )
            )
            == 0
        )
    monkeypatch.setattr(journal_entries, "bind_journal_entry", original_bind)
    await close_journal(env)
    await recover_submissions(env.submissions, env.factory)
    assert len(await entries(env)) == 1
    assert (await env.submissions.get(env.owner, "upload_document", key)).accepted_at is not None
    assert env.providers.transcriptions == env.providers.extractions == 0


async def test_audio_metadata_recovery_and_graph_retry_preserve_reference_without_retranscription(
    ingestion,
    journal,
    monkeypatch,
):
    env, key = ingestion, uuid4()
    accept = env.submissions.accept

    async def fail(receipt):
        raise StorageUnavailable("synthetic SQL interruption")

    monkeypatch.setattr(env.submissions, "accept", fail)
    with pytest.raises(StorageUnavailable):
        await SubmitAudioNote(env.submissions, env.runtime, 1024).execute(
            "voice.webm",
            "audio/webm",
            b"audio",
            None,
            key,
            journal_reference=journal,
        )
    receipt = await env.submissions.get(env.owner, "upload_audio", key)
    (env.runtime.context.filesystem_root / "audio-notes" / f"{receipt.resource_id}.json").unlink()
    monkeypatch.setattr(env.submissions, "accept", accept)
    await close_journal(env)
    await recover_submissions(env.submissions, env.factory)
    recovered = await env.submissions.get(env.owner, "upload_audio", key)
    note = await env.runtime.audio_note_store.get(receipt.resource_id)
    assert note.journal_reference == journal
    assert len(await entries(env)) == 1
    parent = await env.repo.get(recovered.processing_id, env.owner)
    env.graph.failure = "graph"
    assert (await run_current(env, parent)).status == "retrying"
    waiting = await run_current(env, parent)
    assert waiting.status == "waiting"
    assert metadata_reference((await env.runtime.document_store.get(note.id)).metadata) == journal
    assert {row.resource_kind for row in await entries(env)} == {"audio", "document"}
    await run_current(env, await env.repo.child(waiting))
    assert (await run_current(env, parent)).status == "completed"
    assert env.providers.transcriptions == 1


async def test_deletion_removes_membership_and_replay_cannot_resurrect_it(ingestion, journal):
    env, key = ingestion, uuid4()
    document = NewDocument(content="Original sintético para borrar")
    original, _ = await SubmitDocument(env.submissions, env.runtime).execute(
        document, key, journal_reference=journal
    )
    await env.repo.mark_deleted(env.owner, original.id)
    assert await entries(env) == []
    with pytest.raises(SubmissionConflict, match="resource_deleted"):
        await SubmitDocument(env.submissions, env.runtime).execute(
            document, key, journal_reference=journal
        )
    assert await entries(env) == []


async def test_import_checks_all_historical_references_before_writing_and_preserves_valid_originals(
    ingestion,
    journal,
):
    env = ingestion
    good = ArchivedDocument(
        id=uuid4(),
        content="Archivo sintético",
        source="manual",
        metadata=reference_metadata(journal),
        created_at=datetime.now(UTC),
    )
    bad = good.model_copy(
        update={
            "id": uuid4(),
            "metadata": reference_metadata(
                journal.model_copy(update={"run_id": uuid4()}),
            ),
        }
    )
    transfer = DocumentArchiveTransfer(
        env.runtime.document_store, env.repo, env.owner, env.submissions, graph=env.graph
    )
    with pytest.raises(JournalError, match="journal_reference_not_found"):
        await transfer.import_archive(
            DocumentArchive(exported_at=datetime.now(UTC), documents=[good, bad])
        )
    assert await env.runtime.document_store.list() == []
    archive = DocumentArchive(exported_at=datetime.now(UTC), documents=[good])
    assert (await transfer.import_archive(archive))["imported"] == 1
    assert (await transfer.import_archive(archive))["existing"] == 1
    assert (await transfer.export()).documents[0] == good
    assert len(await entries(env)) == 1


@pytest.mark.parametrize("kind", ["text", "audio"])
async def test_http_typed_reference_round_trip_and_safe_invalid_reference(ingestion, journal, kind):
    env = ingestion
    app.dependency_overrides[get_workspace_runtime] = lambda: env.runtime
    app.dependency_overrides[require_authenticated] = lambda: "test-user"
    app.dependency_overrides[get_repository] = lambda: env.repo
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:

        async def request(reference):
            if kind == "text":
                return await client.post(
                    "/v2/documents",
                    json={
                        "content": "PRIVATE_SYNTHETIC_TEXT",
                        "journal_reference": reference.model_dump(mode="json"),
                    },
                    headers={"Idempotency-Key": str(uuid4())},
                )
            return await client.post(
                "/v2/audio-notes",
                data={"journal_reference": reference.model_dump_json()},
                files={"file": ("voice.webm", b"audio", "audio/webm")},
                headers={"Idempotency-Key": str(uuid4())},
            )

        rejected = await request(journal.model_copy(update={"run_id": uuid4()}))
        assert rejected.status_code == 404 and "PRIVATE_SYNTHETIC_TEXT" not in rejected.text
        result = await request(journal)
        assert result.status_code == 202, result.text
        if kind == "text":
            assert (
                result.json()["document"]["metadata"]["journal_reference"]
                == journal.model_dump_json()
            )
        else:
            assert result.json()["audio_note"]["journal_reference"] == journal.model_dump(
                mode="json"
            )


async def test_admin_adjustment_between_validation_and_reservation_keeps_the_capture_revision(
    ingestion,
    journal,
    monkeypatch,
):
    env = ingestion
    case = SubmitDocument(env.submissions, env.runtime)
    resolved, proceed = asyncio.Event(), asyncio.Event()
    resolve = case.journal_capture.resolve

    async def delayed(*args, **kwargs):
        reference = await resolve(*args, **kwargs)
        resolved.set()
        await proceed.wait()
        return reference

    monkeypatch.setattr(case.journal_capture, "resolve", delayed)
    task = asyncio.create_task(
        case.execute(
            NewDocument(content="Captura sintética anterior al ajuste"),
            uuid4(),
            journal_reference=journal,
        )
    )
    try:
        await asyncio.wait_for(resolved.wait(), 3)
        await env.journal_manage.adjust(
            env.owner,
            env.journal_receipt.run_id,
            AdjustRun(
                expected_revision=1,
                remaining_stages=PREPARATION_TEMPLATE.stages,
                instructions="Un foco nuevo después de la captura",
            ),
            uuid4(),
        )
        proceed.set()
        document, _ = await asyncio.wait_for(task, 3)
        assert metadata_reference(document.metadata).run_revision == 1
        assert (await entries(env))[0].revision == 1
    finally:
        proceed.set()
        await asyncio.gather(task, return_exceptions=True)


async def test_real_foreign_journal_is_rejected_before_creating_an_original(ingestion, journal):
    env, foreign = ingestion, uuid4()
    async with env.repo.sessions.begin() as session:
        session.add(User(id=foreign, email=f"{foreign}@example.com", hashed_password="unused"))
        await session.flush()
        session.add(
            UserWorkspace(
                user_id=foreign,
                arcadedb_instance_key="test",
                database_name=f"test_{foreign.hex}",
                graph_username=f"test_{foreign.hex}",
                graph_secret_ciphertext="unused",
                status="active",
            )
        )
    try:
        repository = PostgresJournals(env.repo.sessions)
        await ManageJournals(repository, enabled=True).activate(
            foreign,
            ActivateRun(template_id=PREPARATION_TEMPLATE.id, template_version=1, timezone="UTC"),
            uuid4(),
        )
        foreign_ref = (
            await QueryJournals(repository, enabled=True).resolve(
                foreign,
                datetime.now(UTC),
            )
        ).reference
        with pytest.raises(JournalError, match="journal_reference_not_found"):
            await SubmitDocument(env.submissions, env.runtime).execute(
                NewDocument(content="Referencia ajena sintética"),
                uuid4(),
                journal_reference=foreign_ref,
            )
        assert await env.runtime.document_store.list() == []
    finally:
        async with env.repo.sessions.begin() as session:
            await session.execute(delete(User).where(User.id == foreign))


async def test_audio_membership_and_child_roll_back_together_after_failed_handoff(
    ingestion,
    journal,
    monkeypatch,
):
    from src.adapters.storage.postgres import journal_entries

    env = ingestion
    _, parent = await SubmitAudioNote(env.submissions, env.runtime, 1024).execute(
        "voice.webm",
        "audio/webm",
        b"audio",
        None,
        uuid4(),
        journal_reference=journal,
    )
    bind = journal_entries.bind_derived_journal_entry

    async def interrupted(*args):
        await bind(*args)
        raise ConnectionError("synthetic interrupted handoff")

    monkeypatch.setattr(journal_entries, "bind_derived_journal_entry", interrupted)
    retrying = await run_current(env, parent)
    assert retrying.status == "retrying" and await env.repo.child(retrying) is None
    assert [row.resource_kind for row in await entries(env)] == ["audio"]
    monkeypatch.setattr(journal_entries, "bind_derived_journal_entry", bind)
    waiting = await run_current(env, parent)
    assert waiting.status == "waiting"
    assert {row.resource_kind for row in await entries(env)} == {"audio", "document"}
    assert env.providers.transcriptions == 1
