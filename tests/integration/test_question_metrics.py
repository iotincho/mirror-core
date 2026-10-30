"""Content-free SQL metrics, replay and rollback to curated mode."""

# ruff: noqa: F811
import asyncio
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import update
from test_exteriorization_postgres import anyio_backend, rows, setup, store  # noqa: F401
from test_question_preparations import accepted, environment, publish, ready  # noqa: F401

from src.adapters.storage.postgres.invitation_models import Invitation, InvitationPreference
from src.adapters.storage.postgres.invitation_question_models import (
    InvitationFeedback,
    InvitationTopic,
)
from src.adapters.storage.postgres.models import ProcessingRecord
from src.adapters.storage.postgres.question_metrics import PostgresQuestionMetrics
from src.adapters.storage.postgres.state import PostgresExecutionStore
from src.core.exteriorization.question_contracts import InvitationFeedbackChoice
from src.core.exteriorization.question_policy import QuestionPolicy
from src.core.processing.errors import LeaseLost, StorageUnavailable, WorkflowFailure
from src.use_cases.exteriorization.schedule_invitations import ScheduleInvitations
from src.use_cases.processing.context import ExecutionContext

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("INVITATIONS_TEST_DATABASE_URL"), reason="requires isolated PostgreSQL"
    ),
]


async def test_metrics_survive_preparation_cleanup_and_never_expose_content_or_owner(environment):
    env = environment
    metrics = PostgresQuestionMetrics(env.repo.sessions)
    env.workflow.metrics = metrics
    env.provider.propose.return_value = env.result, dict(input_tokens=123, output_tokens=45)
    preparation = await ready(env)
    await publish(env)
    await env.preparations.remove(env.owner, preparation.id)
    result = await metrics.aggregate(7)
    model = next(row for row in result["provider_calls"] if row["model"] == "synthetic-model")
    assert model["started"] == 1 and model["unknown_usage"] == 0
    assert model["known_input_tokens"] == 123 and model["known_output_tokens"] == 45
    assert result["decisions"]["prepared"] == 1
    assert str(env.owner) not in str(result) and env.document.content not in str(result)
    assert "question" not in str(result).lower()


async def test_metadata_commit_failure_replays_saved_usage_without_another_call(environment):
    env = environment
    metrics = PostgresQuestionMetrics(env.repo.sessions)
    env.workflow.metrics = metrics
    env.provider.propose.return_value = env.result, dict(input_tokens=123, output_tokens=45)
    preparation = await accepted(env)
    original = metrics.complete_call
    metrics.complete_call = AsyncMock(
        side_effect=StorageUnavailable("synthetic metrics unavailable")
    )
    with pytest.raises(StorageUnavailable):
        await env.executor(preparation.processing_id, 1)
    metrics.complete_call = original
    async with env.repo.sessions.begin() as session:
        await session.execute(
            update(ProcessingRecord)
            .where(ProcessingRecord.id == preparation.processing_id)
            .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    await env.processing.recover()
    replay = await env.processing.get(preparation.processing_id, env.owner)
    await env.executor(replay.id, replay.generation)
    assert env.provider.propose.await_count == 1
    result = await metrics.aggregate(7)
    assert result["provider_calls"][0]["known_input_tokens"] == 123
    assert result["provider_calls"][0]["started"] == 1


async def test_failed_provider_has_unknown_usage_not_zero_and_safe_error_code(environment, caplog):
    env = environment
    metrics = PostgresQuestionMetrics(env.repo.sessions)
    env.workflow.metrics = metrics
    env.provider.propose.side_effect = ValueError("synthetic private payload")
    preparation = await accepted(env)
    await env.executor(preparation.processing_id, 1)
    result = await metrics.aggregate(7)
    row = result["provider_calls"][0]
    assert row["unknown_usage"] == row["unknown_outcome"] == 1
    assert row["known_input_tokens"] is None and result["cost_usd"] is None
    assert result["failures"]["question_preparation_failed"] == 1
    assert "synthetic private payload" not in caplog.text


async def test_fenced_call_receipts_reject_duplicates_and_stale_completion(environment):
    env = environment
    preparation = await accepted(env)
    execution = PostgresExecutionStore(env.processing)
    job = await execution.acquire(preparation.processing_id, 1, "test-worker")
    context = ExecutionContext(execution, job, env.workflow.definition)
    metrics = PostgresQuestionMetrics(env.repo.sessions)
    token = await metrics.start_call(context)
    with pytest.raises(WorkflowFailure, match="already_started"):
        await metrics.start_call(context)
    async with env.repo.sessions.begin() as session:
        await session.execute(
            update(ProcessingRecord)
            .where(ProcessingRecord.id == job.id)
            .values(fencing_token=job.fencing_token + 1)
        )
    with pytest.raises(LeaseLost):
        await metrics.complete_call(context, token, {}, 0)


async def test_operational_rollback_preserves_published_questions_and_feedback(
    environment, monkeypatch
):
    from src.bootstrap import daily_questions

    env = environment
    await ready(env)
    personal = await publish(env)
    await env.service.activity.feedback(
        env.owner,
        personal.id,
        InvitationFeedbackChoice(
            invitation_question_id=personal.question_set["default_question_id"], value="helpful"
        ),
        uuid4(),
    )
    monkeypatch.setattr(
        daily_questions, "get_settings", lambda: SimpleNamespace(daily_question_mode="curated")
    )
    assert daily_questions.prepared_question_selector() is None
    tomorrow = env.due + timedelta(days=1)
    async with env.repo.sessions.begin() as session:
        await session.execute(
            update(InvitationPreference)
            .where(InvitationPreference.user_id == env.owner)
            .values(next_due_at=tomorrow)
        )
    assert (
        await ScheduleInvitations(env.repo, daily_questions.prepared_question_selector()).execute(
            tomorrow
        )
        == 1
    )
    invitations = await rows(env.repo, Invitation, env.owner)
    assert (
        next(item for item in invitations if item.id == personal.id).question_set
        == personal.question_set
    )
    assert next(item for item in invitations if item.scheduled_at == tomorrow).source == "generic"
    assert len(await rows(env.repo, InvitationFeedback, env.owner)) == 1
    assert env.provider.propose.await_count == 1


async def test_invitation_policy_snapshot_controls_later_feedback(environment):
    env = environment
    policy = QuestionPolicy(rest_days=21, general_every=3)
    assert await ScheduleInvitations(env.repo, policy=policy).execute(env.due) == 1
    invitation = (await rows(env.repo, Invitation, env.owner))[0]
    await env.service.activity.feedback(
        env.owner,
        invitation.id,
        InvitationFeedbackChoice(
            invitation_question_id=invitation.question_set["default_question_id"], value="not_now"
        ),
        uuid4(),
    )
    topics = await rows(env.repo, InvitationTopic, env.owner)
    topic = next(item for item in topics if item.status == "paused")
    assert topic.paused_until - topic.restricted_at == timedelta(days=21)


async def test_daily_call_quota_is_atomic_across_two_owners(environment):
    env = environment
    preparation = await accepted(env)
    execution = PostgresExecutionStore(env.processing)
    first = await execution.acquire(preparation.processing_id, 1, "first-worker")
    other_id, other_owner = uuid4(), env.store[1][1]
    async with env.repo.sessions.begin() as session:
        session.add(
            ProcessingRecord(
                id=other_id,
                user_id=other_owner,
                resource_id=uuid4(),
                resource_kind="question_preparation",
                workflow="question_preparation",
                workflow_version=1,
                stage="question_proposals",
                config=env.configuration.model_dump(mode="json"),
                expires_at=env.due,
            )
        )
    second = await execution.acquire(other_id, 1, "second-worker")
    metrics = PostgresQuestionMetrics(env.repo.sessions, max_calls_per_day=1)
    contexts = [
        ExecutionContext(execution, job, env.workflow.definition) for job in (first, second)
    ]
    results = await asyncio.gather(
        *(metrics.start_call(context) for context in contexts), return_exceptions=True
    )
    assert sum(isinstance(value, int) for value in results) == 1
    assert (
        sum(
            isinstance(value, WorkflowFailure) and value.code == "question_daily_call_limit"
            for value in results
        )
        == 1
    )


async def test_zero_quota_uses_catalog_without_calling_provider(environment):
    env = environment
    metrics = PostgresQuestionMetrics(env.repo.sessions, max_calls_per_day=0)
    env.workflow.metrics = metrics
    preparation = await accepted(env)
    await env.executor(preparation.processing_id, 1)
    env.provider.propose.assert_not_awaited()
    invitation = await publish(env)
    assert invitation.source == "generic"
    result = await metrics.aggregate(7)
    assert not result["provider_calls"]
    assert result["failures"]["question_daily_call_limit"] == 1
