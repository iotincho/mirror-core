"""Question membership and SQL projections; selection and boundary rules remain in core."""

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from src.adapters.storage.postgres.invitation_models import Invitation, InvitationResponse
from src.adapters.storage.postgres.invitation_question_models import (
    InvitationActivityReceipt,
    InvitationFeedback,
    InvitationInteractionRecord,
    InvitationOccurrence,
    InvitationQuestionRecord,
    InvitationTopic,
)
from src.core.exteriorization.curated_questions import CatalogTopicFact
from src.core.exteriorization.models import InvitationError
from src.core.exteriorization.question_contracts import (
    InvitationQuestionSet,
    InvitationResponseReference,
    legacy_question_set,
    resolve_response_question,
)
from src.core.exteriorization.question_policy import TopicState
from src.core.processing.submissions import SubmissionConflict


async def question_set(session, owner, identifier):
    invitation = await session.scalar(
        select(Invitation).where(
            Invitation.id == identifier,
            Invitation.user_id == owner,
        )
    )
    if invitation is None:
        raise InvitationError("invitation_not_found")
    return (
        InvitationQuestionSet.model_validate(invitation.question_set)
        if invitation.question_set is not None
        else legacy_question_set(invitation.id, invitation.question)
    )


async def resolve_question(session, owner, invitation_id, question_id=None):
    package = await question_set(session, owner, invitation_id)
    try:
        return resolve_response_question(
            package,
            InvitationResponseReference(
                invitation_id=invitation_id,
                invitation_question_id=question_id,
            ),
        ).id
    except ValueError:
        raise InvitationError("invitation_question_not_found") from None


async def ensure_question(session, owner, invitation_id, question_id=None):
    identifier = await resolve_question(session, owner, invitation_id, question_id)
    row = await session.scalar(
        select(InvitationQuestionRecord).where(
            InvitationQuestionRecord.id == identifier,
            InvitationQuestionRecord.invitation_id == invitation_id,
            InvitationQuestionRecord.user_id == owner,
        )
    )
    if row is None:
        package = await question_set(session, owner, invitation_id)
        if package.question_groups[0].layout != "legacy":
            raise InvitationError("invitation_question_unavailable")
        await session.execute(
            insert(InvitationQuestionRecord)
            .values(
                id=identifier,
                invitation_id=invitation_id,
                user_id=owner,
                group_id=package.question_groups[0].id,
                topic_id=None,
                depth=None,
            )
            .on_conflict_do_nothing()
        )
        row = await session.get(InvitationQuestionRecord, identifier)
    return row


async def bind_response(session, owner, document_id, invitation_id, question_id=None):
    question = await ensure_question(session, owner, invitation_id, question_id)
    await session.execute(
        insert(InvitationResponse)
        .values(
            user_id=owner,
            document_id=document_id,
            invitation_id=invitation_id,
            invitation_question_id=question.id,
        )
        .on_conflict_do_nothing()
    )
    row = await session.get(InvitationResponse, (owner, document_id))
    if row.invitation_id != invitation_id:
        raise SubmissionConflict("invitation_response_conflict")
    if row.invitation_question_id is None:
        package = await question_set(session, owner, invitation_id)
        if question.id != package.default_question_id:
            raise SubmissionConflict("invitation_response_conflict")
    elif row.invitation_question_id != question.id:
        raise SubmissionConflict("invitation_response_conflict")


def topic_snapshot(row):
    return TopicState(**{name: getattr(row, name) for name in TopicState.model_fields})


class QuestionTransaction:
    async def catalog_state(self, owner, topics):
        if topics:
            await self.session.execute(
                insert(InvitationTopic)
                .values(
                    [
                        dict(
                            id=identifier,
                            user_id=owner,
                            catalog_key=key,
                            scope="catalog",
                            status="open",
                            last_feedback_sequence=0,
                        )
                        for identifier, key in topics
                    ]
                )
                .on_conflict_do_nothing()
            )
        rows = list(
            await self.session.scalars(
                select(InvitationTopic).where(
                    InvitationTopic.user_id == owner,
                    InvitationTopic.scope == "catalog",
                    (InvitationTopic.id.in_([i for i, _ in topics]) if topics else True),
                )
            )
        )
        shows = (
            select(
                InvitationQuestionRecord.topic_id,
                InvitationInteractionRecord.invitation_id,
                func.min(InvitationInteractionRecord.recorded_at).label("shown_at"),
            )
            .join(
                InvitationQuestionRecord,
                InvitationQuestionRecord.id == InvitationInteractionRecord.question_id,
            )
            .join(
                Invitation,
                Invitation.id == InvitationInteractionRecord.invitation_id,
            )
            .where(
                InvitationInteractionRecord.user_id == owner,
                InvitationInteractionRecord.kind == "shown",
                Invitation.kind == "scheduled",
                InvitationQuestionRecord.topic_id.in_([row.id for row in rows]),
            )
            .group_by(
                InvitationQuestionRecord.topic_id,
                InvitationInteractionRecord.invitation_id,
            )
            .subquery()
        )
        latest = list(
            (
                await self.session.execute(
                    select(shows)
                    .distinct(shows.c.topic_id)
                    .order_by(shows.c.topic_id, shows.c.shown_at.desc(), shows.c.invitation_id)
                )
            ).all()
        )
        responses = set(
            (
                await self.session.execute(
                    select(
                        InvitationResponse.invitation_id,
                        InvitationQuestionRecord.topic_id,
                    )
                    .join(
                        InvitationQuestionRecord,
                        InvitationQuestionRecord.id == InvitationResponse.invitation_question_id,
                    )
                    .where(
                        InvitationResponse.user_id == owner,
                        InvitationResponse.invitation_id.in_(
                            [item.invitation_id for item in latest]
                        ),
                    )
                )
            ).all()
        )
        history = {item.topic_id: item for item in latest}
        return tuple(
            CatalogTopicFact(
                topic=topic_snapshot(row),
                last_shown_at=history[row.id].shown_at if row.id in history else None,
                answered=(history[row.id].invitation_id, row.id) in responses
                if row.id in history
                else False,
            )
            for row in rows
        )

    async def add_question_indexes(self, invitation, bindings):
        topics = dict(bindings)
        for group in invitation.questions.question_groups:
            for question in group.questions:
                self.session.add(
                    InvitationQuestionRecord(
                        id=question.id,
                        user_id=invitation.user_id,
                        invitation_id=invitation.id,
                        group_id=group.id,
                        topic_id=topics.get(group.id),
                        depth=question.depth,
                    )
                )
        await self.session.flush()

    async def omit_occurrence(self, owner, day, now):
        self.session.add(
            InvitationOccurrence(
                user_id=owner,
                local_date=day,
                recorded_at=now,
                outcome="no_eligible_questions",
            )
        )

    async def activity_receipt(self, owner, operation, key, request_hash):
        row = await self.session.scalar(
            select(InvitationActivityReceipt).where(
                InvitationActivityReceipt.user_id == owner,
                InvitationActivityReceipt.operation == operation,
                InvitationActivityReceipt.request_key == key,
            )
        )
        if row is not None and row.request_hash != request_hash:
            raise InvitationError("idempotency_conflict")
        return row.response if row else None

    async def save_activity_receipt(self, owner, operation, key, request_hash, body, identifier):
        self.session.add(
            InvitationActivityReceipt(
                id=identifier,
                user_id=owner,
                operation=operation,
                request_key=key,
                request_hash=request_hash,
                response=body,
            )
        )
        await self.session.flush()

    async def feedback_topic(self, owner, invitation_id, question_id):
        question = await ensure_question(self.session, owner, invitation_id, question_id)
        if question.topic_id is None:
            return None
        row = await self.session.scalar(
            select(InvitationTopic)
            .where(
                InvitationTopic.id == question.topic_id,
                InvitationTopic.user_id == owner,
            )
            .with_for_update()
        )
        return topic_snapshot(row)

    async def save_topic(self, topic):
        row = await self.session.get(InvitationTopic, topic.id)
        for name in TopicState.model_fields:
            setattr(row, name, getattr(topic, name))

    async def append_feedback(
        self, owner, invitation_id, question_id, value, now, identifier, sequence
    ):
        self.session.add(
            InvitationFeedback(
                id=identifier,
                user_id=owner,
                invitation_id=invitation_id,
                question_id=question_id,
                value=value,
                recorded_at=now,
                topic_sequence=sequence,
            )
        )

    async def record_interactions(self, owner, invitation_id, events, now):
        for event in events:
            await ensure_question(self.session, owner, invitation_id, event.invitation_question_id)
            row = await self.session.get(InvitationInteractionRecord, (owner, event.event_id))
            if row:
                if (row.invitation_id, row.question_id, row.kind) != (
                    invitation_id,
                    event.invitation_question_id,
                    event.kind,
                ):
                    raise InvitationError("idempotency_conflict")
            else:
                self.session.add(
                    InvitationInteractionRecord(
                        id=event.event_id,
                        user_id=owner,
                        invitation_id=invitation_id,
                        question_id=event.invitation_question_id,
                        kind=event.kind,
                        recorded_at=now,
                    )
                )
