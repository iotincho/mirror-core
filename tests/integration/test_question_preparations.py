"""Real SQL reservations, fencing and fallback races with synthetic originals/providers."""

# ruff: noqa: F811
import asyncio
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update
from test_exteriorization_postgres import anyio_backend, rows, setup, store  # noqa: F401

from src.adapters.storage.filesystem.owner_originals import FileOwnerOriginals
from src.adapters.storage.filesystem.processing_artifacts import ProcessingArtifacts
from src.adapters.storage.postgres.invitation_models import Invitation, InvitationPreference
from src.adapters.storage.postgres.models import ProcessingEvent, ProcessingOutbox, ProcessingRecord
from src.adapters.storage.postgres.question_preparation_models import QuestionPreparation
from src.adapters.storage.postgres.question_preparations import PostgresQuestionPreparations
from src.adapters.storage.postgres.repository import ProcessingRepository
from src.adapters.storage.postgres.state import PostgresExecutionStore
from src.bootstrap.processing import build_executor
from src.core.domain.documents import Document
from src.core.exteriorization.personalization import PreparationConfiguration, TopicProposals
from src.core.exteriorization.question_contracts import InvitationFeedbackChoice
from src.core.processing.errors import LeaseLost, ResourceBusy
from src.core.processing.workflows import WorkflowRegistry
from src.use_cases.exteriorization.prepare_questions import PrepareQuestions
from src.use_cases.exteriorization.schedule_invitations import ScheduleInvitations
from src.use_cases.exteriorization.select_prepared_questions import (
    SelectPreparedQuestions,
    select_proposals,
)
from src.use_cases.processing.context import ExecutionContext

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("INVITATIONS_TEST_DATABASE_URL"), reason="requires isolated PostgreSQL"
    ),
]


@pytest.fixture
async def environment(store, tmp_path):
    repo, owner, service, _ = await setup(store, devices=0)
    now = datetime.now(UTC)
    due = now + timedelta(minutes=10)
    async with repo.sessions.begin() as session:
        preference = await session.get(InvitationPreference, owner)
        preference.next_due_at, preference.updated_at = due, now
    originals = FileOwnerOriginals(tmp_path)
    documents = await originals.documents(owner)
    document = Document(
        id=uuid4(),
        content="Quiero hablar sobre los cambios de este trabajo.",
        source="pwa_note",
        metadata={},
        created_at=now - timedelta(minutes=5),
    )
    await documents.save(document)
    async with repo.sessions.begin() as session:
        session.add(
            ProcessingRecord(
                id=uuid4(),
                user_id=owner,
                workflow="document",
                workflow_version=5,
                resource_kind="document",
                resource_id=document.id,
                status="completed",
                stage="done",
                config={},
                created_at=now - timedelta(minutes=5),
            )
        )
    configuration = PreparationConfiguration(model="synthetic-model")
    result = TopicProposals(
        proposals=[
            dict(
                existing_topic_id=None,
                label="Cambios de este trabajo",
                basis="explicit",
                intent="explore",
                effort="low",
                evidence=[dict(document_id=document.id, start=0, end=40)],
                questions=dict(
                    gentle="¿Qué cambio tenés presente hoy?",
                    middle="¿Qué te gustaría contar de ese cambio?",
                    deep="¿Qué necesitás en esta etapa de cambios?",
                ),
            )
        ]
    )
    provider = SimpleNamespace(propose=AsyncMock(return_value=(result, {})))
    preparations = PostgresQuestionPreparations(repo.sessions)
    workflow = PrepareQuestions(
        preparations,
        originals,
        lambda user, identifier: ProcessingArtifacts(tmp_path / str(identifier)),
        lambda _: provider,
        select_proposals,
    )
    registry = WorkflowRegistry()
    registry.register("question_preparation", 1, workflow.definition)
    processing = ProcessingRepository(repo.sessions, lease_seconds=30)
    executor = build_executor(processing, registry)
    selector = SelectPreparedQuestions(originals)
    env = SimpleNamespace(**locals())
    try:
        yield env
    finally:
        async with repo.sessions.begin() as session:
            await session.execute(
                delete(QuestionPreparation).where(QuestionPreparation.user_id.in_(store[1]))
            )


async def accepted(env):
    assert await env.preparations.schedule(env.configuration, env.now) == 1
    async with env.repo.sessions() as session:
        return await session.scalar(
            select(QuestionPreparation).where(QuestionPreparation.user_id == env.owner)
        )


async def ready(env):
    preparation = await accepted(env)
    await env.executor(preparation.processing_id, 1)
    async with env.repo.sessions() as session:
        row = await session.get(QuestionPreparation, preparation.id)
        assert row.status == "ready"
    return preparation


async def publish(env):
    generated = await ScheduleInvitations(env.repo, env.selector).execute(env.due)
    assert generated == 1
    return next(
        row for row in await rows(env.repo, Invitation, env.owner) if row.scheduled_at == env.due
    )


async def test_concurrent_dispatchers_reserve_one_job_and_outbox_without_provider(environment):
    env = environment
    counts = await asyncio.gather(
        *[env.preparations.schedule(env.configuration, env.now) for _ in range(6)]
    )
    assert sum(counts) == 1
    preparations = await rows(env.repo, QuestionPreparation, env.owner)
    assert len(preparations) == 1
    async with env.repo.sessions() as session:
        assert (
            len(
                list(
                    await session.scalars(
                        select(ProcessingOutbox).where(
                            ProcessingOutbox.processing_id == preparations[0].processing_id
                        )
                    )
                )
            )
            == 1
        )
    env.provider.propose.assert_not_awaited()


async def test_worker_publishes_personal_package_with_catalog_and_hides_internal_work(
    environment,
):
    env = environment
    preparation = await ready(env)
    duplicates = await asyncio.gather(
        env.executor(preparation.processing_id, 1),
        env.executor(preparation.processing_id, 1),
        return_exceptions=True,
    )
    assert all(value is None or isinstance(value, ResourceBusy) for value in duplicates)
    invitation = await publish(env)
    assert invitation.source == "personalized"
    assert any(group["source"] == "generic" for group in invitation.question_set["question_groups"])
    assert env.provider.propose.await_count == 1
    assert not await rows(env.repo, ProcessingEvent, env.owner)
    assert all(
        job.workflow != "question_preparation"
        for job in await env.processing.list_for_owner(env.owner)
    )
    before = invitation.question_set
    assert await ScheduleInvitations(env.repo, env.selector).execute(env.due) == 0
    assert (await rows(env.repo, Invitation, env.owner))[0].question_set == before


@pytest.mark.parametrize("mutation", ["deleted", "changed", "closed", "paused", "do_not_prompt"])
async def test_finalizer_rechecks_deleted_sources_and_later_boundaries(environment, mutation):
    env = environment
    await ready(env)
    if mutation in {"deleted", "changed"}:
        await env.documents.delete(env.document.id)
        if mutation == "changed":
            await env.documents.save(env.document.model_copy(update={"content": "Texto cambiado"}))
    else:
        # Materialize its stable topic, then simulate feedback after preparation.
        async with env.repo.transaction() as transaction:
            facts = await transaction.personal_question_facts(env.owner, env.result.proposals)
            topic = facts[0].topic.model_copy(
                update={
                    "status": mutation,
                    "restricted_at": env.now,
                    "paused_until": env.due + timedelta(days=7) if mutation == "paused" else None,
                }
            )
            await transaction.save_topic(topic)
    invitation = await publish(env)
    assert invitation.source == "generic"
    assert all(group["source"] == "generic" for group in invitation.question_set["question_groups"])


async def test_fallback_and_slow_provider_never_replace_published_package(environment):
    env = environment
    preparation = await accepted(env)
    started, release = asyncio.Event(), asyncio.Event()

    async def slow(_):
        started.set()
        await release.wait()
        return env.result, {}

    env.provider.propose.side_effect = slow
    work = asyncio.create_task(env.executor(preparation.processing_id, 1))
    await asyncio.wait_for(started.wait(), 5)
    invitation = await publish(env)
    assert invitation.source == "generic"
    release.set()
    await work
    saved = (await rows(env.repo, Invitation, env.owner))[0]
    assert saved.question_set == invitation.question_set
    assert len(await rows(env.repo, Invitation, env.owner)) == 1
    assert (await rows(env.repo, QuestionPreparation, env.owner))[0].status == "obsolete"


@pytest.mark.parametrize("mutation", ["disabled", "rescheduled", "workspace"])
async def test_obsolete_preferences_or_workspace_cancel_preparation(environment, mutation):
    env = environment
    preparation = await accepted(env)
    if mutation == "disabled":
        await env.service.configure(env.owner, False, "20:30", "UTC")
    elif mutation == "rescheduled":
        await env.service.configure(env.owner, True, "21:30", "UTC")
    else:
        from src.adapters.storage.postgres.workspace_models import UserWorkspace

        async with env.repo.sessions.begin() as session:
            workspace = await session.get(UserWorkspace, env.owner)
            workspace.status = "failed"
    await env.executor(preparation.processing_id, 1)
    env.provider.propose.assert_not_awaited()


async def test_lost_fencing_token_cannot_accept_even_with_saved_artifacts(environment):
    env = environment
    preparation = await accepted(env)
    execution = PostgresExecutionStore(env.processing)
    job = await execution.acquire(preparation.processing_id, 1, "first-worker")
    context = ExecutionContext(execution, job, env.workflow.definition)
    from src.use_cases.exteriorization.prepare_questions import build_snapshot

    snapshot, _ = await build_snapshot(
        env.preparations, env.documents, env.owner, env.now, env.configuration
    )
    async with env.repo.sessions.begin() as session:
        await session.execute(
            update(ProcessingRecord)
            .where(ProcessingRecord.id == job.id)
            .values(fencing_token=job.fencing_token + 1)
        )
    with pytest.raises(LeaseLost):
        await env.preparations.accept(
            context,
            snapshot,
            env.result,
            select_proposals(preparation.id, env.owner, snapshot, env.result),
        )


async def test_new_boundaries_filter_opening_but_historical_answer_remains_acceptable(environment):
    env = environment
    await ready(env)
    invitation = await publish(env)
    loaded = await env.service.get_invitation(env.owner, invitation.id)
    personal = loaded.questions.question_groups[0]
    await env.service.activity.feedback(
        env.owner,
        invitation.id,
        InvitationFeedbackChoice(invitation_question_id=personal.questions[2].id, value="closed"),
        uuid4(),
    )
    loaded = await env.service.get_invitation(env.owner, invitation.id)
    assert all(q.id not in loaded.available_question_ids for q in personal.questions)
    assert loaded.question == invitation.question
    assert loaded.question_set == invitation.question_set
    opened = await env.service.open_invitation(env.owner, invitation.id)
    assert opened.available_question_ids == loaded.available_question_ids
    _, history, _ = await env.preparations.inventory(env.owner, datetime.now(UTC))
    observed = next(
        question
        for question in history[0]["questions"]
        if question["id"] == str(personal.questions[2].id)
    )
    assert observed["text"] == personal.questions[2].text and observed["feedback"] == "closed"
    async with env.repo.sessions() as session:
        from src.adapters.storage.postgres.invitation_questions import resolve_question

        assert (
            await resolve_question(session, env.owner, invitation.id, personal.questions[1].id)
            == personal.questions[1].id
        )


@pytest.mark.parametrize(
    "intent,basis,restriction,expected",
    [
        ("reopen", "explicit", "closed", "personalized"),
        ("reopen", "explicit", "do_not_prompt", "personalized"),
        ("mention", "explicit", "closed", "generic"),
        ("reopen", "inferred", "closed", "generic"),
        ("explore", "explicit", "closed", "generic"),
    ],
)
async def test_only_explicit_current_intent_reopens_known_restricted_topic(
    environment, intent, basis, restriction, expected
):
    env = environment
    async with env.repo.transaction() as transaction:
        fact = (await transaction.personal_question_facts(env.owner, env.result.proposals))[0]
        await transaction.save_topic(
            fact.topic.model_copy(
                update={"status": restriction, "restricted_at": env.now - timedelta(minutes=10)}
            )
        )
    proposal = env.result.proposals[0].model_copy(
        update={"existing_topic_id": fact.topic.id, "intent": intent, "basis": basis}
    )
    env.provider.propose.return_value = (TopicProposals(proposals=[proposal]), {})
    await ready(env)
    invitation = await publish(env)
    assert invitation.source == expected
    from src.adapters.storage.postgres.invitation_question_models import InvitationTopic

    async with env.repo.sessions() as session:
        topic = await session.get(InvitationTopic, fact.topic.id)
        assert topic.status == ("open" if expected == "personalized" else restriction)
        if expected == "personalized":
            assert topic.reopened_by_document_id == env.document.id


async def test_concurrent_finalizers_publish_one_prepared_occurrence(environment):
    env = environment
    await ready(env)
    results = await asyncio.gather(
        *[ScheduleInvitations(env.repo, env.selector).execute(env.due) for _ in range(4)]
    )
    assert sum(results) == 1
    assert len(await rows(env.repo, Invitation, env.owner)) == 1
    assert env.provider.propose.await_count == 1


async def test_group_provenance_survives_temporary_preparation_cleanup(environment):
    from src.adapters.storage.postgres.question_preparation_models import QuestionGroupProvenance

    env = environment
    preparation = await ready(env)
    invitation = await publish(env)
    await env.preparations.remove(env.owner, preparation.id)
    provenance = await rows(env.repo, QuestionGroupProvenance, env.owner)
    assert len(provenance) == len(invitation.question_set["question_groups"])
    personal = next(
        row.specification for row in provenance if row.specification["source"] == "personalized"
    )
    assert personal["configuration"]["model"] == "synthetic-model"
    assert personal["configuration"]["prompt_version"] == "daily-proposals-v1"
    assert personal["evidence"][0]["document_id"] == str(env.document.id)
    assert env.document.content not in str(personal)


async def test_fourth_initial_is_general_even_when_personal_proposals_are_ready(environment):
    env = environment
    await ready(env)
    # The scheduler's preexisting curated behavior provides valid historical rows.
    async with env.repo.transaction() as transaction:
        from src.use_cases.exteriorization.generate_invitation import GenerateInvitation

        preference = await transaction.preference(env.owner)
        for days in range(3, 0, -1):
            previous = await GenerateInvitation().execute(
                transaction,
                preference,
                env.due - timedelta(days=days),
                env.now - timedelta(days=days),
                [],
            )
            previous.source = "personalized"
            # It was newly added, not tracked via SnapshotTracker; update the SQL row.
            await transaction.session.execute(
                update(Invitation).where(Invitation.id == previous.id).values(source="personalized")
            )
    invitation = await publish(env)
    assert invitation.source == "generic"
    assert any(
        group["source"] == "personalized" for group in invitation.question_set["question_groups"]
    )


async def test_recent_linked_reply_is_prioritized_when_new_notes_fill_the_inventory(environment):
    from src.adapters.storage.postgres.invitation_questions import bind_response
    from src.use_cases.exteriorization.generate_invitation import GenerateInvitation

    env = environment
    async with env.repo.transaction() as transaction:
        preference = await transaction.preference(env.owner)
        invitation = await GenerateInvitation().execute(
            transaction, preference, env.due - timedelta(days=1), env.now - timedelta(days=1), []
        )
        await bind_response(transaction.session, env.owner, env.document.id, invitation.id)
        for index in range(21):
            transaction.session.add(
                ProcessingRecord(
                    id=uuid4(),
                    user_id=env.owner,
                    workflow="document",
                    workflow_version=5,
                    resource_kind="document",
                    resource_id=uuid4(),
                    status="completed",
                    stage="done",
                    config={},
                    created_at=env.now - timedelta(seconds=index + 1),
                )
            )
    inventory, history, _ = await env.preparations.inventory(env.owner, env.now)
    assert len(inventory) == 20 and inventory[0][0] == env.document.id
    assert str(env.document.id) in history[0]["responses"]
