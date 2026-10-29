"""Select once and atomically persist the invitation, inbox item, device jobs and outbox."""

from datetime import timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from src.core.exteriorization.contracts import EngineContext
from src.core.exteriorization.curated_questions import build_curated_questions, catalog_topics
from src.core.exteriorization.models import Invitation
from src.core.exteriorization.question_policy import QuestionPolicy
from src.core.exteriorization.scheduling import expires_at


class GenerateInvitation:
    async def execute(self, transaction, preference, due, now, subscriptions, *, request_key=None):
        kind = "test" if request_key else "scheduled"
        identifier = uuid4()
        policy = QuestionPolicy()
        prepared = build_curated_questions(
            identifier,
            preference.user_id,
            EngineContext(
                now=now,
                timezone=preference.timezone,
                history=await transaction.history(preference.user_id),
            ),
            await transaction.catalog_state(preference.user_id, catalog_topics(preference.user_id)),
            policy=policy,
        )
        if prepared is None:
            return None
        trigger, package, bindings = prepared
        day = due.astimezone(ZoneInfo(preference.timezone)).date()
        invitation = Invitation(
            id=identifier,
            user_id=preference.user_id,
            kind=kind,
            local_date=day,
            timezone=preference.timezone,
            scheduled_at=due,
            expires_at=expires_at(due, preference.timezone)
            if kind == "scheduled"
            else now + timedelta(minutes=5),
            occurrence_key=f"{preference.user_id}:{day}"
            if kind == "scheduled"
            else f"test:{preference.user_id}:{request_key}",
            request_key=request_key,
            test_subscription_id=subscriptions[0].id if request_key else None,
            created_at=now,
            question_set=package.model_dump(mode="json"),
            question_policy=policy.model_dump(mode="json"),
            **trigger.model_dump(),
        )
        await transaction.add_invitation(invitation, topic_bindings=bindings)
        await transaction.notify(invitation)
        for subscription in subscriptions:
            await transaction.enqueue_push(
                uuid4(),
                uuid4(),
                preference.user_id,
                invitation.id,
                subscription.id,
                now,
            )
        return invitation
