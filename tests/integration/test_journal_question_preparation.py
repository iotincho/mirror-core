"""Journal-scoped preparation and atomic publication, with real SQL and fake providers."""

# ruff: noqa: F811
import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.engine import make_url
from test_exteriorization_postgres import anyio_backend, store  # noqa: F401
from test_question_preparations import environment  # noqa: F401
from test_question_preparations import ready as ready_v1

from src.adapters.storage.filesystem.processing_artifacts import ProcessingArtifacts
from src.adapters.storage.postgres.accounts import User
from src.adapters.storage.postgres.invitation_models import (
    Invitation,
    InvitationPreference,
    PushSubscription,
)
from src.adapters.storage.postgres.invitation_transaction import InvitationTransaction
from src.adapters.storage.postgres.journal_entries import bind_journal_entry
from src.adapters.storage.postgres.journal_models import JournalInvitationRecord
from src.adapters.storage.postgres.journals import PostgresJournals
from src.adapters.storage.postgres.models import ProcessingRecord
from src.adapters.storage.postgres.notification_models import Notification
from src.adapters.storage.postgres.question_preparation_models import QuestionPreparation
from src.adapters.storage.postgres.question_preparations import PostgresQuestionPreparations
from src.core.domain.documents import Document
from src.core.exteriorization.personalization import TopicProposals
from src.core.exteriorization.question_contracts import InvitationFeedbackChoice
from src.core.journals.catalogs import goal_hash
from src.core.journals.contracts import (
    ActivateRun,
    AdjustRun,
    ChangeLifecycle,
    EditIntention,
    EntryReference,
)
from src.core.journals.entries import reference_metadata
from src.core.journals.preparation_catalog import PREPARATION_TEMPLATE_V2
from src.core.processing.errors import StorageUnavailable
from src.use_cases.exteriorization.prepare_journal_questions import PrepareJournalQuestions
from src.use_cases.exteriorization.schedule_invitations import ScheduleInvitations
from src.use_cases.exteriorization.select_prepared_questions import select_proposals
from src.use_cases.journals.manage import ManageJournals
from src.use_cases.journals.query import QueryJournals

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("INVITATIONS_TEST_DATABASE_URL"),
        reason="requires isolated journal questions PostgreSQL",
    ),
]


@pytest.fixture
async def journal_env(environment):
    env = environment
    assert make_url(os.environ["INVITATIONS_TEST_DATABASE_URL"]).database.startswith(
        "journals_test"
    )
    journal_repo = PostgresJournals(env.repo.sessions)
    await journal_repo.install_template(PREPARATION_TEMPLATE_V2)
    env.manage = ManageJournals(journal_repo, enabled=True)
    env.journal_query = QueryJournals(journal_repo, enabled=True)
    env.activation = await env.manage.activate(
        env.owner,
        ActivateRun(
            template_id=PREPARATION_TEMPLATE_V2.id,
            template_version=2,
            timezone="UTC",
        ),
        uuid4(),
    )
    env.journal_context = await env.journal_query.resolve(env.owner, env.due)
    env.preparations = PostgresQuestionPreparations(env.repo.sessions, journals_enabled=True)
    env.workflow = PrepareJournalQuestions(
        env.preparations,
        env.originals,
        lambda owner, identifier: ProcessingArtifacts(env.tmp_path / str(identifier)),
        lambda _: env.provider,
        select_proposals,
    )
    env.registry.register("question_preparation", 2, env.workflow.definition)
    return env


async def add_note(env, *, reference=None, content="Quiero explorar mis expectativas.", age_days=0):
    reference = reference or env.journal_context.reference
    note = Document(
        id=uuid4(),
        content=content,
        source="pwa_note",
        metadata=reference_metadata(reference),
        created_at=env.now - timedelta(days=age_days),
    )
    await env.documents.save(note)
    async with env.repo.sessions.begin() as session:
        await bind_journal_entry(session, env.owner, "document", note.id, reference, env.now)
    return note


def propose(note):
    return TopicProposals(
        proposals=[
            dict(
                existing_topic_id=None,
                label="Mis expectativas",
                basis="explicit",
                intent="explore",
                effort="low",
                evidence=[dict(document_id=note.id, start=0, end=len(note.content))],
                questions=dict(
                    gentle="¿Qué expectativa tenés presente?",
                    middle="¿Qué de esa expectativa querés explorar hoy?",
                    deep="¿Qué lugar te gustaría darle a esa expectativa?",
                ),
            )
        ]
    )


async def reserve(env):
    assert await env.preparations.schedule(env.configuration, env.due - timedelta(minutes=10)) == 1
    async with env.repo.sessions() as session:
        return await session.scalar(
            select(QuestionPreparation).where(
                QuestionPreparation.user_id == env.owner,
                QuestionPreparation.status == "pending",
            )
        )


async def ready(env):
    row = await reserve(env)
    await env.executor(row.processing_id, 1)
    async with env.repo.sessions() as session:
        row = await session.get(QuestionPreparation, row.id)
        assert row.status == "ready"
    return row


async def publish(env):
    count = await ScheduleInvitations(
        env.repo, env.selector, journal_contexts=env.journal_query
    ).execute(env.due)
    async with env.repo.sessions() as session:
        row = await session.scalar(
            select(Invitation).where(
                Invitation.user_id == env.owner,
                Invitation.scheduled_at == env.due,
            )
        )
    return count, row


async def test_first_day_without_entries_uses_curated_journal_and_never_invokes_provider(
    journal_env,
):
    env = journal_env
    await ready(env)
    assert not env.provider.propose.called
    count, invitation = await publish(env)
    assert count == 1 and invitation.category == "journal"
    assert all(group["source"] == "generic" for group in invitation.question_set["question_groups"])
    async with env.repo.sessions() as session:
        context = await session.get(JournalInvitationRecord, invitation.id)
        assert context.run_id == env.activation.run_id and context.revision == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.user_id == env.owner,
                )
            )
            >= 1
        )


async def test_personal_generation_gets_journal_goal_and_only_its_notes_including_old_originals(
    journal_env,
):
    env = journal_env
    note = await add_note(env, age_days=60)
    env.provider.propose.return_value = (propose(note), {})
    await ready(env)
    data = env.provider.propose.call_args.args[0]
    assert {source["document_id"] for source in data["sources"]} == {str(note.id)}
    assert data["journal_context"]["stage_objective"] == env.journal_context.stage_objective
    assert str(env.document.id) not in {source["document_id"] for source in data["sources"]}
    count, row = await publish(env)
    assert count == 1 and row.source == "personalized"
    assert any(group["source"] == "generic" for group in row.question_set["question_groups"])


async def test_notes_from_other_journey_and_free_notes_are_excluded(journal_env):
    env = journal_env
    old_note = await add_note(env, content="Texto que pertenece a otro recorrido.")
    await env.manage.lifecycle(
        env.owner,
        env.activation.run_id,
        ChangeLifecycle(expected_revision=1, action="pause"),
        uuid4(),
    )
    env.activation = await env.manage.activate(
        env.owner,
        ActivateRun(
            template_id=PREPARATION_TEMPLATE_V2.id,
            template_version=2,
            timezone="UTC",
        ),
        uuid4(),
    )
    env.journal_context = await env.journal_query.resolve(env.owner, env.due)
    note = await add_note(env)
    env.provider.propose.return_value = (propose(note), {})
    await ready(env)
    supplied = {item["document_id"] for item in env.provider.propose.call_args.args[0]["sources"]}
    assert supplied == {str(note.id)} and str(old_note.id) not in supplied


async def test_concurrent_reservations_and_publishers_keep_one_context_and_one_occurrence(
    journal_env,
):
    env = journal_env
    counts = await asyncio.gather(
        *[
            env.preparations.schedule(env.configuration, env.due - timedelta(minutes=10))
            for _ in range(4)
        ]
    )
    assert sum(counts) == 1
    publishers = await asyncio.gather(
        *[
            ScheduleInvitations(env.repo, env.selector, journal_contexts=env.journal_query).execute(
                env.due
            )
            for _ in range(4)
        ]
    )
    assert sum(publishers) == 1
    async with env.repo.sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(JournalInvitationRecord)
                .where(
                    JournalInvitationRecord.owner_id == env.owner,
                )
            )
            == 1
        )


async def test_intention_revision_invalidates_ready_preparation_and_reserves_another(journal_env):
    env = journal_env
    old = await ready(env)
    await env.manage.edit_intention(
        env.owner,
        env.activation.run_id,
        EditIntention(expected_revision=1, text="Entender mis expectativas"),
        uuid4(),
    )
    assert await env.preparations.live(env.owner, old.id) is None
    new = await reserve(env)
    assert new.id != old.id and new.context_key != old.context_key
    assert new.configuration["journal_reference"]["run_revision"] == 2
    assert "Entender mis expectativas" not in str(new.configuration)
    async with env.repo.sessions() as session:
        assert (await session.get(QuestionPreparation, old.id)).status == "obsolete"


async def test_edit_during_provider_call_cannot_publish_or_accept_the_obsolete_result(journal_env):
    env = journal_env
    note = await add_note(env)

    async def delayed(data):
        await env.manage.edit_intention(
            env.owner,
            env.activation.run_id,
            EditIntention(expected_revision=1, text="Una intención revisada"),
            uuid4(),
        )
        return propose(note), {}

    env.provider.propose.side_effect = delayed
    row = await reserve(env)
    await env.executor(row.processing_id, 1)
    async with env.repo.sessions() as session:
        assert (await session.get(QuestionPreparation, row.id)).status != "ready"
    count, invitation = await publish(env)
    assert count == 1 and invitation.source == "generic" and invitation.category == "journal"
    async with env.repo.sessions() as session:
        assert (await session.get(JournalInvitationRecord, invitation.id)).revision == 2


async def test_goal_edit_requires_catalog_review_and_omits_instead_of_using_free_questions(
    journal_env,
):
    env = journal_env
    await env.manage.adjust(
        env.owner,
        env.activation.run_id,
        AdjustRun(
            expected_revision=1,
            remaining_stages=PREPARATION_TEMPLATE_V2.stages,
            instructions="Un foco distinto después de la sesión",
        ),
        uuid4(),
    )
    assert await env.preparations.schedule(env.configuration, env.now) == 0
    count, row = await publish(env)
    assert count == 0 and row is None
    assert (await publish(env))[0] == 0


async def test_catalog_review_restores_fallback_under_a_new_revision(journal_env):
    env = journal_env
    instructions = "Explorar ejemplos recientes sin suponer causas."
    await env.manage.adjust(
        env.owner,
        env.activation.run_id,
        AdjustRun(
            expected_revision=1,
            remaining_stages=PREPARATION_TEMPLATE_V2.stages,
            instructions=instructions,
        ),
        uuid4(),
    )
    catalogs = tuple(
        item.model_copy(
            update={
                "goal_hash": goal_hash(
                    PREPARATION_TEMPLATE_V2.purpose,
                    instructions,
                    next(
                        stage
                        for stage in PREPARATION_TEMPLATE_V2.stages
                        if stage.key == item.stage_key
                    ),
                )
            }
        )
        for item in PREPARATION_TEMPLATE_V2.catalogs
    )
    await env.manage.adjust(
        env.owner,
        env.activation.run_id,
        AdjustRun(
            expected_revision=2, remaining_stages=PREPARATION_TEMPLATE_V2.stages, catalogs=catalogs
        ),
        uuid4(),
    )
    count, row = await publish(env)
    assert count == 1
    async with env.repo.sessions() as session:
        assert (await session.get(JournalInvitationRecord, row.id)).revision == 3


async def test_closing_before_publication_uses_free_catalog_without_reusing_journal_proposals(
    journal_env,
):
    env = journal_env
    note = await add_note(env)
    env.provider.propose.return_value = (propose(note), {})
    prepared = await ready(env)
    await env.manage.lifecycle(
        env.owner,
        env.activation.run_id,
        ChangeLifecycle(expected_revision=1, action="close"),
        uuid4(),
    )
    assert await env.preparations.live(env.owner, prepared.id) is None
    count, row = await publish(env)
    assert count == 1 and row.source == "generic" and row.category != "journal"
    async with env.repo.sessions() as session:
        assert await session.get(JournalInvitationRecord, row.id) is None


async def test_disabled_journals_omit_active_context_instead_of_silently_using_free(journal_env):
    env = journal_env
    env.journal_query.enabled = False
    env.preparations.journals_enabled = False
    assert await env.preparations.schedule(env.configuration, env.now) == 0
    assert (await publish(env))[0] == 0


async def test_closed_catalog_topics_are_not_reopened_by_repeating_the_template(journal_env):
    from src.use_cases.exteriorization.configure_invitations import ConfigureInvitations

    env = journal_env
    count, row = await publish(env)
    assert count == 1
    service = ConfigureInvitations(env.repo)
    for group in row.question_set["question_groups"]:
        await service.activity.feedback(
            env.owner,
            row.id,
            InvitationFeedbackChoice(
                invitation_question_id=group["questions"][1]["id"], value="do_not_prompt"
            ),
            uuid4(),
        )
    await env.manage.lifecycle(
        env.owner,
        env.activation.run_id,
        ChangeLifecycle(expected_revision=1, action="close"),
        uuid4(),
    )
    await env.manage.activate(
        env.owner,
        ActivateRun(
            template_id=PREPARATION_TEMPLATE_V2.id,
            template_version=2,
            timezone="UTC",
        ),
        uuid4(),
    )
    env.due += timedelta(days=1)
    async with env.repo.sessions.begin() as session:
        preference = await session.get(InvitationPreference, env.owner)
        preference.next_due_at = env.due
    assert (await publish(env))[0] == 0


async def test_preparation_uses_the_stage_at_due_time_when_it_changes_during_anticipation(
    journal_env,
):
    env = journal_env
    await env.manage.lifecycle(
        env.owner,
        env.activation.run_id,
        ChangeLifecycle(expected_revision=1, action="close"),
        uuid4(),
    )
    actual = datetime.now(UTC)
    boundary = (actual + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    offset = boundary.hour if boundary.hour <= 12 else boundary.hour - 24
    zone = f"Etc/GMT{offset:+d}"
    previous_week = ManageJournals(
        PostgresJournals(env.repo.sessions), enabled=True, clock=lambda: actual - timedelta(days=6)
    )
    env.activation = await previous_week.activate(
        env.owner,
        ActivateRun(
            template_id=PREPARATION_TEMPLATE_V2.id,
            template_version=2,
            timezone=zone,
        ),
        uuid4(),
    )
    env.due = boundary + timedelta(minutes=1)
    async with env.repo.sessions.begin() as session:
        (await session.get(InvitationPreference, env.owner)).next_due_at = env.due
    current = await env.journal_query.resolve(env.owner, actual)
    target = await env.journal_query.resolve(env.owner, env.due)
    assert current.reference.stage_id != target.reference.stage_id
    prepared = await ready(env)
    assert prepared.configuration["journal_reference"]["stage_id"] == str(target.reference.stage_id)
    count, row = await publish(env)
    assert count == 1
    async with env.repo.sessions() as session:
        assert (
            await session.get(JournalInvitationRecord, row.id)
        ).stage_id == target.reference.stage_id


async def test_provider_failure_uses_curated_journal_without_retries_or_payload_exposure(
    journal_env,
):
    env = journal_env
    await add_note(env)
    env.provider.propose.side_effect = RuntimeError("PRIVATE_SYNTHETIC_PROVIDER_PAYLOAD")
    row = await reserve(env)
    await env.executor(row.processing_id, 1)
    async with env.repo.sessions() as session:
        job = await session.get(ProcessingRecord, row.processing_id)
        assert job.status == "failed" and "PRIVATE" not in job.error_code
    count, invitation = await publish(env)
    assert count == 1 and invitation.category == "journal" and invitation.source == "generic"
    assert env.provider.propose.await_count == 1


async def test_recovering_acceptance_reuses_the_durable_proposals_without_another_call(
    journal_env, monkeypatch
):
    env = journal_env
    note = await add_note(env)
    env.provider.propose.return_value = (propose(note), {})
    row = await reserve(env)
    accept = env.preparations.accept

    async def interrupted(*args):
        raise OSError("synthetic failure before SQL checkpoint")

    monkeypatch.setattr(env.preparations, "accept", interrupted)
    with pytest.raises(StorageUnavailable):
        await env.executor(row.processing_id, 1)
    assert env.provider.propose.await_count == 1
    monkeypatch.setattr(env.preparations, "accept", accept)
    async with env.repo.sessions.begin() as session:
        job = await session.get(ProcessingRecord, row.processing_id)
        # Recover the abandoned lease using the existing repository recovery.
        job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await env.processing.recover()
    async with env.repo.sessions() as session:
        job = await session.get(ProcessingRecord, row.processing_id)
        generation = job.generation
    await env.executor(row.processing_id, generation)
    assert env.provider.propose.await_count == 1
    async with env.repo.sessions() as session:
        assert (await session.get(QuestionPreparation, row.id)).status == "ready"


async def test_publication_rolls_back_context_inbox_and_push_outbox_together(
    journal_env, monkeypatch
):
    env = journal_env
    async with env.repo.sessions.begin() as session:
        session.add(
            PushSubscription(
                user_id=env.owner,
                endpoint="https://push.example.test/synthetic",
                p256dh="synthetic",
                auth="synthetic",
                session_fingerprint="synthetic",
            )
        )
    enqueue = InvitationTransaction.enqueue_push

    async def interrupted(self, *args, **kwargs):
        await enqueue(self, *args, **kwargs)
        raise ConnectionError("synthetic publication interruption")

    monkeypatch.setattr(InvitationTransaction, "enqueue_push", interrupted)
    with pytest.raises(ConnectionError):
        await publish(env)
    async with env.repo.sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(JournalInvitationRecord)
                .where(
                    JournalInvitationRecord.owner_id == env.owner,
                )
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Invitation)
                .where(
                    Invitation.user_id == env.owner,
                    Invitation.kind == "scheduled",
                )
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ProcessingRecord)
                .where(
                    ProcessingRecord.user_id == env.owner,
                    ProcessingRecord.workflow == "invitation_push",
                )
            )
            == 0
        )
    monkeypatch.setattr(InvitationTransaction, "enqueue_push", enqueue)
    assert (await publish(env))[0] == 1


async def test_removed_membership_cannot_supply_evidence_even_if_original_survived_deletion(
    journal_env,
):
    env = journal_env
    note = await add_note(env)
    env.provider.propose.return_value = (propose(note), {})
    await ready(env)
    await env.processing.mark_deleted(env.owner, note.id)
    assert (await env.documents.get(note.id)).content == note.content
    count, row = await publish(env)
    assert count == 1 and row.source == "generic" and row.category == "journal"
    assert env.provider.propose.await_count == 1


async def test_deleted_membership_is_revalidated_when_accepting_ready_preparation(
    journal_env, monkeypatch
):
    env = journal_env
    note = await add_note(env)
    env.provider.propose.return_value = (propose(note), {})
    accept = env.preparations.accept

    async def delete_before_accept(*arguments):
        await env.processing.mark_deleted(env.owner, note.id)
        return await accept(*arguments)

    monkeypatch.setattr(env.preparations, "accept", delete_before_accept)
    row = await reserve(env)
    await env.executor(row.processing_id, 1)
    async with env.repo.sessions() as session:
        assert (await session.get(QuestionPreparation, row.id)).status == "pending"
    count, invitation = await publish(env)
    assert count == 1 and invitation.source == "generic" and invitation.category == "journal"
    assert env.provider.propose.await_count == 1


async def test_stage_inventory_excludes_future_stages_then_prioritizes_current_over_previous(
    journal_env,
):
    env = journal_env
    current = await add_note(env)
    async with PostgresJournals(env.repo.sessions).transaction(env.owner) as transaction:
        run = await transaction.run(env.activation.run_id)
    future = EntryReference(run_id=run.id, run_revision=1, stage_id=run.stages[1].id)
    following = await add_note(
        env, reference=future, content="Otra nota sintética para una etapa posterior."
    )
    rows, _, _ = await env.preparations.inventory(
        env.owner, datetime.now(UTC), journal_reference=env.journal_context.reference
    )
    assert [row[0] for row in rows] == [current.id]
    await env.manage.lifecycle(
        env.owner,
        env.activation.run_id,
        ChangeLifecycle(expected_revision=1, action="advance"),
        uuid4(),
    )
    context = await env.journal_query.resolve(env.owner, env.due)
    rows, _, _ = await env.preparations.inventory(
        env.owner, datetime.now(UTC), journal_reference=context.reference
    )
    assert [row[0] for row in rows] == [following.id, current.id]


async def test_inactive_account_cannot_prepare_or_publish_journal_questions(journal_env):
    env = journal_env
    async with env.repo.sessions.begin() as session:
        await session.execute(update(User).where(User.id == env.owner).values(is_active=False))
    assert await env.preparations.schedule(env.configuration, env.now) == 0
    assert (await publish(env))[0] == 0


async def test_every_fourth_personalized_occurrence_starts_with_journal_catalog(journal_env):
    env = journal_env
    note = await add_note(env)
    env.provider.propose.return_value = (propose(note), {})
    initial = env.due
    sources = []
    for day in range(4):
        env.due = initial + timedelta(days=day)
        async with env.repo.sessions.begin() as session:
            preference = await session.get(InvitationPreference, env.owner)
            preference.next_due_at = env.due
            preference.updated_at = env.due - timedelta(minutes=11)
        await ready(env)
        count, row = await publish(env)
        assert count == 1
        sources.append(row.source)
        if day == 3:
            assert row.category == "journal"
            assert row.question_set["question_groups"][0]["source"] == "generic"
            assert any(
                group["source"] == "personalized" for group in row.question_set["question_groups"]
            )
    assert sources == ["personalized", "personalized", "personalized", "generic"]


async def test_free_v1_preparation_is_not_consumed_after_a_journal_is_activated(environment):
    env = environment
    prepared = await ready_v1(env)
    async with env.repo.sessions() as session:
        original_config = (await session.get(ProcessingRecord, prepared.processing_id)).config
    repository = PostgresJournals(env.repo.sessions)
    await repository.install_template(PREPARATION_TEMPLATE_V2)
    await ManageJournals(repository, enabled=True).activate(
        env.owner,
        ActivateRun(
            template_id=PREPARATION_TEMPLATE_V2.id,
            template_version=2,
            timezone="UTC",
        ),
        uuid4(),
    )
    assert await env.preparations.live(env.owner, prepared.id) is None
    env.journal_query = QueryJournals(repository, enabled=True)
    count, row = await publish(env)
    assert count == 1 and row.source == "generic" and row.category == "journal"
    assert env.provider.propose.await_count == 1
    async with env.repo.sessions() as session:
        job = await session.get(ProcessingRecord, prepared.processing_id)
        assert job.workflow_version == 1 and job.config == original_config
