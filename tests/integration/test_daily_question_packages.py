"""Real PostgreSQL packages, activity transactions and public API ownership."""

# ruff: noqa: F811 (imported pytest fixtures)

import asyncio
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, update
from test_exteriorization_postgres import (  # noqa: F401
    anyio_backend,
    due_now,
    rows,
    setup,
    store,
)

from src.adapters.storage.postgres.invitation_models import Invitation
from src.adapters.storage.postgres.invitation_question_models import (
    InvitationActivityReceipt,
    InvitationFeedback,
    InvitationInteractionRecord,
    InvitationOccurrence,
    InvitationTopic,
)
from src.bootstrap.auth import require_authenticated
from src.bootstrap.invitations import get_invitations
from src.bootstrap.public_api import app
from src.core.exteriorization.curated_questions import catalog_topics
from src.core.exteriorization.models import InvitationError
from src.core.exteriorization.question_contracts import (
    InvitationFeedbackChoice,
    InvitationInteractions,
)
from src.use_cases.exteriorization.schedule_invitations import ScheduleInvitations

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        not os.getenv("INVITATIONS_TEST_DATABASE_URL"),
        reason="requires isolated PostgreSQL",
    ),
]


async def published(store):
    repo, owner, service, _ = await setup(store, devices=0)
    now = await due_now(repo, owner)
    assert await ScheduleInvitations(repo).execute(now) == 1
    row = (await rows(repo, Invitation, owner))[0]
    return repo, owner, service, await service.get_invitation(owner, row.id), now


def feedback(question, value="closed"):
    return InvitationFeedbackChoice(invitation_question_id=question.id, value=value)


def shown(question, *, identifier=None, kind="shown"):
    return InvitationInteractions(
        events=[
            dict(
                event_id=identifier or uuid4(),
                invitation_question_id=question.id,
                kind=kind,
            )
        ]
    )


async def test_packages_are_persisted_and_public_read_keeps_push_question(store):
    repo, owner, service, invitation, _ = await published(store)
    package = invitation.questions
    assert len(package.question_groups) == 3
    assert all(len(group.questions) == 3 for group in package.question_groups)
    assert package.question == package.question_groups[0].questions[1].text
    app.dependency_overrides[require_authenticated] = lambda: SimpleNamespace(id=owner)
    app.dependency_overrides[get_invitations] = lambda: service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://test"
    ) as client:
        result = await client.get(f"/exteriorization/invitations/{invitation.id}")
        assert result.status_code == 200
        body = result.json()
        assert body["question"] == invitation.question
        assert body["default_question_id"] == str(package.default_question_id)
        assert "topic_id" not in str(body) and "user_id" not in body
    repeated = await service.get_invitation(owner, invitation.id)
    assert repeated.question_set == invitation.question_set


async def test_concurrent_feedback_replays_once_and_closes_all_depths_of_topic(store):
    repo, owner, service, invitation, now = await published(store)
    question = invitation.questions.question_groups[0].questions[2]
    key = uuid4()
    first, second = await asyncio.gather(
        *[
            service.activity.feedback(owner, invitation.id, feedback(question), key)
            for _ in range(2)
        ]
    )
    assert first == second
    assert len(await rows(repo, InvitationFeedback, owner)) == 1
    async with repo.sessions() as session:
        closed = await session.scalar(
            select(InvitationTopic).where(
                InvitationTopic.user_id == owner,
                InvitationTopic.status == "closed",
            )
        )
        assert closed.last_feedback_sequence == 1
        closed_id = closed.id
    with pytest.raises(InvitationError, match="idempotency_conflict"):
        await service.activity.feedback(owner, invitation.id, feedback(question, "helpful"), key)
    await service.activity.feedback(owner, invitation.id, feedback(question, "helpful"), uuid4())
    async with repo.sessions() as session:
        topic = await session.get(InvitationTopic, closed_id)
        assert topic.status == "closed" and topic.last_feedback_sequence == 2
    tomorrow = now + timedelta(days=1)
    await due_now(repo, owner, tomorrow)
    assert await ScheduleInvitations(repo).execute(tomorrow) == 1
    async with repo.sessions() as session:
        latest = await session.scalar(
            select(Invitation).where(
                Invitation.user_id == owner,
                Invitation.local_date == tomorrow.date(),
            )
        )
        assert latest.candidate_id != invitation.candidate_id


async def test_interactions_deduplicate_observation_and_reject_changed_event_content(store):
    repo, owner, service, invitation, _ = await published(store)
    group = invitation.questions.question_groups[0]
    question = group.questions[1]
    event = shown(question)
    key = uuid4()
    first = await service.activity.interactions(owner, invitation.id, event, key)
    assert await service.activity.interactions(owner, invitation.id, event, key) == first
    await service.activity.interactions(owner, invitation.id, event, uuid4())
    assert len(await rows(repo, InvitationInteractionRecord, owner)) == 1
    async with repo.transaction() as tx:
        original = await tx.catalog_state(owner, catalog_topics(owner))
    await service.activity.interactions(owner, invitation.id, shown(question), uuid4())
    await service.activity.interactions(owner, invitation.id, shown(group.questions[2]), uuid4())
    async with repo.transaction() as tx:
        repeated = await tx.catalog_state(owner, catalog_topics(owner))
    assert original == repeated
    altered = shown(question, identifier=event.events[0].event_id, kind="passed")
    with pytest.raises(InvitationError, match="idempotency_conflict"):
        await service.activity.interactions(owner, invitation.id, altered, uuid4())
    assert len(await rows(repo, InvitationInteractionRecord, owner)) == 3


async def test_activity_http_validates_owner_origin_shape_and_replay(store, monkeypatch):
    repo, owner, service, invitation, _ = await published(store)
    question = invitation.questions.question_groups[0].questions[0]
    app.dependency_overrides[require_authenticated] = lambda: SimpleNamespace(id=owner)
    app.dependency_overrides[get_invitations] = lambda: service
    path = f"/exteriorization/invitations/{invitation.id}/feedback"
    payload = feedback(question).model_dump(mode="json")
    headers = {"Idempotency-Key": str(uuid4()), "Origin": "https://test"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://test"
    ) as client:
        first = await client.post(path, json=payload, headers=headers)
        assert first.status_code == 200
        assert (await client.post(path, json=payload, headers=headers)).json() == first.json()
        changed = await client.post(path, json={**payload, "value": "helpful"}, headers=headers)
        assert changed.status_code == 409
        assert (
            await client.post(path, json={**payload, "user_id": str(owner)}, headers=headers)
        ).status_code == 422
        assert (
            await client.post(path, json=payload, headers={**headers, "Origin": "https://evil"})
        ).status_code == 403
        assert (
            await client.post(
                path, json={**payload, "invitation_question_id": str(uuid4())}, headers=headers
            )
        ).status_code == 404
        app.dependency_overrides[require_authenticated] = lambda: SimpleNamespace(id=store[1][1])
        assert (await client.post(path, json=payload, headers=headers)).status_code == 404
        monkeypatch.setattr(
            "src.bootstrap.auth.get_settings",
            lambda: SimpleNamespace(
                auth_session_secret="synthetic-auth-test-secret",
                auth_session_ttl_seconds=3600,
            ),
        )
        monkeypatch.setattr("src.bootstrap.database.get_session_maker", lambda: repo.sessions)
        app.dependency_overrides.pop(require_authenticated)
        assert (await client.post(path, json=payload, headers=headers)).status_code == 401


async def test_all_topics_closed_omits_and_reserves_occurrence_without_relaxing_limits(store):
    repo, owner, _, invitation, now = await published(store)
    async with repo.sessions.begin() as session:
        await session.execute(
            update(InvitationTopic)
            .where(InvitationTopic.user_id == owner)
            .values(
                status="closed",
                restricted_at=now,
            )
        )
    tomorrow = now + timedelta(days=1)
    await due_now(repo, owner, tomorrow)
    assert await ScheduleInvitations(repo).execute(tomorrow) == 0
    occurrences = await rows(repo, InvitationOccurrence, owner)
    assert {item.outcome for item in occurrences} == {"published", "no_eligible_questions"}
    await due_now(repo, owner, tomorrow)
    assert await ScheduleInvitations(repo).execute(tomorrow) == 0
    assert len(await rows(repo, Invitation, owner)) == 1
    assert (await rows(repo, Invitation, owner))[0].id == invitation.id


async def test_test_invitation_activity_does_not_consume_real_topic_history(store):
    repo, owner, service, subscriptions = await setup(store, devices=1)
    invitation = await service.test(owner, "session-0", subscriptions[0].id, uuid4())
    question = invitation.questions.question_groups[0].questions[1]
    await service.activity.feedback(owner, invitation.id, feedback(question), uuid4())
    await service.activity.interactions(owner, invitation.id, shown(question), uuid4())
    async with repo.transaction() as tx:
        facts = await tx.catalog_state(owner, catalog_topics(owner))
    assert all(item.topic.status == "open" and item.last_shown_at is None for item in facts)
    assert await ScheduleInvitations(repo).execute(await due_now(repo, owner)) == 1
    invitation = next(row for row in await rows(repo, Invitation, owner) if row.kind == "scheduled")
    assert invitation.candidate_id == "daily_01"


async def test_legacy_activity_does_not_invent_topic_or_rewrite_historical_question(store):
    repo, owner, service, _ = await setup(store, devices=0)
    now = datetime.now(UTC)
    identifier = uuid4()
    async with repo.sessions.begin() as session:
        session.add(
            Invitation(
                id=identifier,
                user_id=owner,
                kind="test",
                local_date=now.date(),
                timezone="UTC",
                scheduled_at=now,
                expires_at=now + timedelta(hours=1),
                occurrence_key=str(uuid4()),
                source="generic",
                candidate_id="daily_01",
                category="registro",
                question="¿Cómo estuvo tu día?",
                engine_version="generic-v1",
                catalog_version="1",
                created_at=now,
            )
        )
    invitation = await service.get_invitation(owner, identifier)
    package = invitation.questions
    assert package.question_groups[0].layout == "legacy"
    question = package.question_groups[0].questions[0]
    await service.activity.feedback(owner, identifier, feedback(question), uuid4())
    async with repo.sessions() as session:
        row = await session.get(Invitation, identifier)
        assert row.question_set is None and row.question == "¿Cómo estuvo tu día?"
        assert (
            await session.scalar(
                select(func.count())
                .select_from(InvitationTopic)
                .where(
                    InvitationTopic.user_id == owner,
                )
            )
            == 0
        )


async def test_interaction_http_batch_rolls_back_when_a_later_event_conflicts(store):
    repo, owner, service, invitation, _ = await published(store)
    question = invitation.questions.question_groups[0].questions[1]
    event = shown(question)
    await service.activity.interactions(owner, invitation.id, event, uuid4())
    fresh = shown(question).events[0]
    changed = shown(question, identifier=event.events[0].event_id, kind="passed").events[0]
    batch = InvitationInteractions(events=(fresh, changed))
    app.dependency_overrides[require_authenticated] = lambda: SimpleNamespace(id=owner)
    app.dependency_overrides[get_invitations] = lambda: service
    path = f"/exteriorization/invitations/{invitation.id}/interactions"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="https://test"
    ) as client:
        result = await client.post(
            path, json=batch.model_dump(mode="json"), headers={"Idempotency-Key": str(uuid4())}
        )
        assert result.status_code == 409
        assert len(await rows(repo, InvitationInteractionRecord, owner)) == 1
        assert len(await rows(repo, InvitationActivityReceipt, owner)) == 1
        payload = {"events": [fresh.model_dump(mode="json")]}
        headers = {"Idempotency-Key": str(uuid4())}
        result = await client.post(path, json=payload, headers=headers)
        assert result.status_code == 200
        assert result.json()["recorded_event_ids"] == [str(fresh.event_id)]
        assert (await client.post(path, json=payload, headers=headers)).json() == result.json()
        invalid = {"events": [fresh.model_dump(mode="json"), fresh.model_dump(mode="json")]}
        assert (await client.post(path, json=invalid, headers=headers)).status_code == 422


async def test_feedback_uses_the_policy_frozen_when_invitation_was_created(store, monkeypatch):
    from src.core.exteriorization.question_policy import QuestionPolicy

    monkeypatch.setattr(
        "src.use_cases.exteriorization.generate_invitation.QuestionPolicy",
        lambda: QuestionPolicy(rest_days=2),
    )
    repo, owner, service, invitation, _ = await published(store)
    assert invitation.question_policy["rest_days"] == 2
    question = invitation.questions.question_groups[0].questions[1]
    receipt = await service.activity.feedback(
        owner, invitation.id, feedback(question, "not_now"), uuid4()
    )
    async with repo.sessions() as session:
        paused = await session.scalar(
            select(InvitationTopic).where(
                InvitationTopic.user_id == owner,
                InvitationTopic.status == "paused",
            )
        )
        assert paused.paused_until - datetime.fromisoformat(receipt["recorded_at"]) == timedelta(
            days=2
        )
