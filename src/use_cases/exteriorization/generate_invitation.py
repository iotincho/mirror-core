"""Select once and atomically persist the invitation, inbox item, device jobs and outbox."""

from datetime import timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from src.core.exteriorization.contracts import EngineContext
from src.core.exteriorization.curated_questions import build_curated_questions, catalog_topics
from src.core.exteriorization.journal_questions import (
    build_journal_questions,
    context_hash,
    journal_topics,
)
from src.core.exteriorization.models import Invitation
from src.core.exteriorization.question_policy import QuestionPolicy
from src.core.exteriorization.scheduling import expires_at
from src.core.journals.contracts import JournalQuestionContext
from src.core.journals.errors import JournalError


class GenerateInvitation:
    def __init__(self, personalization=None, policy=None, journal_contexts=None):
        self.personalization = personalization
        self.policy = policy or QuestionPolicy()
        self.journal_contexts = journal_contexts

    async def execute(
        self,
        transaction,
        preference,
        due,
        now,
        subscriptions,
        *,
        request_key=None,
        preference_version=None,
    ):
        kind = "test" if request_key else "scheduled"
        identifier = uuid4()
        policy = self.policy
        scope = None
        if self.journal_contexts is not None:
            try:
                candidate = await self.journal_contexts.resolve(preference.user_id, due)
            except JournalError as error:
                if error.code in {
                    "journals_disabled",
                    "journal_workspace_unavailable",
                    "journal_owner_not_found",
                }:
                    return None
                raise
            if isinstance(candidate, JournalQuestionContext):
                scope = candidate
        history = await transaction.history(
            preference.user_id,
            **({"journal_reference": scope.reference} if scope is not None else {}),
        )
        if scope is not None:
            prepared = build_journal_questions(
                identifier,
                preference.user_id,
                scope,
                now,
                await transaction.catalog_state(
                    preference.user_id, journal_topics(preference.user_id, scope)
                ),
                policy,
                history,
            )
        else:
            prepared = build_curated_questions(
                identifier,
                preference.user_id,
                EngineContext(now=now, timezone=preference.timezone, history=history),
                await transaction.catalog_state(
                    preference.user_id, catalog_topics(preference.user_id)
                ),
                policy=policy,
            )
        if prepared is None:
            return None
        if self.personalization is not None and request_key is None:
            prepared = await self.personalization.execute(
                transaction,
                preference,
                due,
                now,
                prepared,
                policy,
                preference_version=preference_version or preference.updated_at,
                **({"journal_context": scope} if scope is not None else {}),
            )
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
        if scope is not None:
            await transaction.bind_journal_context(invitation, scope.reference)
        provenance = getattr(prepared, "provenance", None)
        if scope is not None:
            provenance = {
                str(group.id): {
                    **(provenance or {}).get(str(group.id), {"source": group.source}),
                    "journal_reference": scope.reference.model_dump(mode="json"),
                    "journal_context_hash": context_hash(scope),
                }
                for group in package.question_groups
            }
        if provenance:
            await transaction.save_question_provenance(invitation, provenance)
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
