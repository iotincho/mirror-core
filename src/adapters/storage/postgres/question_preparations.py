"""Bounded inventory and occurrence reservations through the existing job/outbox runtime."""

from datetime import timedelta
from uuid import uuid4, uuid5

from sqlalchemy import func, select, update

from src.adapters.storage.postgres.invitation_models import (
    Invitation,
    InvitationPreference,
    InvitationResponse,
)
from src.adapters.storage.postgres.invitation_question_models import (
    InvitationFeedback,
    InvitationInteractionRecord,
    InvitationTopic,
)
from src.adapters.storage.postgres.invitation_questions import topic_snapshot
from src.adapters.storage.postgres.models import ProcessingRecord
from src.adapters.storage.postgres.question_metric_models import QuestionPreparationMetric
from src.adapters.storage.postgres.question_metrics import ensure_metric
from src.adapters.storage.postgres.question_preparation_models import (
    PersonalTopicDescription,
    QuestionPreparation,
)
from src.adapters.storage.postgres.repository import ProcessingRepository
from src.adapters.storage.postgres.state import database_errors
from src.adapters.storage.postgres.workspace_models import UserWorkspace
from src.core.exteriorization.personalization import TopicDescription
from src.core.exteriorization.question_contracts import InvitationQuestionSet, legacy_question_set
from src.core.processing.errors import LeaseLost


class PostgresQuestionPreparations:
    def __init__(self, sessions):
        self.sessions = sessions

    async def schedule(self, configuration, now=None):
        async with database_errors(), self.sessions.begin() as session:
            now = now or await session.scalar(select(func.clock_timestamp()))
            # Global accepted-job bound complements per-worker provider concurrency.
            await session.execute(
                select(
                    func.pg_advisory_xact_lock(
                        func.hashtextextended("daily-question-admission-v1", 0)
                    )
                )
            )
            pending = await session.scalar(
                select(func.count())
                .select_from(ProcessingRecord)
                .where(
                    ProcessingRecord.workflow == "question_preparation",
                    ProcessingRecord.status.in_(["queued", "running", "retrying"]),
                    ProcessingRecord.expires_at > now,
                )
            )
            capacity = min(100, max(0, 1000 - pending))
            if not capacity:
                return 0
            preferences = list(
                await session.scalars(
                    select(InvitationPreference)
                    .join(
                        UserWorkspace,
                        UserWorkspace.user_id == InvitationPreference.user_id,
                    )
                    .where(
                        InvitationPreference.enabled.is_(True),
                        UserWorkspace.status == "active",
                        InvitationPreference.next_due_at > now,
                        InvitationPreference.next_due_at
                        <= now + timedelta(minutes=configuration.lead_minutes),
                    )
                    .order_by(InvitationPreference.next_due_at)
                    .limit(capacity)
                    .with_for_update(skip_locked=True, of=InvitationPreference)
                )
            )
            accepted = 0
            for preference in preferences:
                identifier = uuid5(
                    preference.user_id,
                    f"daily-prepare-v1:{preference.next_due_at.isoformat()}:{preference.updated_at.isoformat()}",
                )
                if await session.get(QuestionPreparation, identifier):
                    continue
                await session.execute(
                    update(QuestionPreparation)
                    .where(
                        QuestionPreparation.user_id == preference.user_id,
                        QuestionPreparation.status.in_(["pending", "ready"]),
                    )
                    .values(status="obsolete")
                )
                config = configuration.model_dump(mode="json")
                job = ProcessingRecord(
                    id=uuid4(),
                    user_id=preference.user_id,
                    workflow="question_preparation",
                    workflow_version=1,
                    resource_kind="question_preparation",
                    resource_id=identifier,
                    stage="question_context",
                    config=config,
                    expires_at=preference.next_due_at,
                )
                session.add(job)
                await session.flush()
                await ensure_metric(session, job)
                session.add(
                    QuestionPreparation(
                        id=identifier,
                        user_id=preference.user_id,
                        processing_id=job.id,
                        due_at=preference.next_due_at,
                        preference_version=preference.updated_at,
                        configuration=config,
                        created_at=now,
                        expires_at=preference.next_due_at + timedelta(hours=36),
                        status="pending",
                    )
                )
                ProcessingRepository.schedule(session, job)
                accepted += 1
            return accepted

    async def live(self, owner, preparation_id, *, now=None):
        async with database_errors(), self.sessions() as session:
            now = now or await session.scalar(select(func.clock_timestamp()))
            preparation = await session.scalar(
                select(QuestionPreparation).where(
                    QuestionPreparation.id == preparation_id,
                    QuestionPreparation.user_id == owner,
                )
            )
            preference = await session.get(InvitationPreference, owner)
            workspace = await session.get(UserWorkspace, owner)
            if not preparation or not preference or not workspace or workspace.status != "active":
                return None
            if (
                not preference.enabled
                or preparation.status not in {"pending", "ready"}
                or now >= preparation.due_at
            ):
                return None
            if (
                preference.next_due_at != preparation.due_at
                or preference.updated_at != preparation.preference_version
            ):
                return None
            return {"now": now, "due_at": preparation.due_at}

    async def inventory(self, owner, now):
        async with database_errors(), self.sessions() as session:
            sources = (
                select(
                    ProcessingRecord.resource_id,
                    func.min(ProcessingRecord.created_at).label("accepted_at"),
                )
                .where(
                    ProcessingRecord.user_id == owner,
                    ProcessingRecord.workflow == "document",
                    ProcessingRecord.resource_kind == "document",
                )
                .group_by(ProcessingRecord.resource_id)
                .having(
                    func.bool_or(ProcessingRecord.resource_deleted).is_(False),
                    func.min(ProcessingRecord.created_at) >= now - timedelta(days=30),
                    func.min(ProcessingRecord.created_at) <= now,
                )
                .order_by(
                    func.min(ProcessingRecord.created_at).desc(), ProcessingRecord.resource_id
                )
            )
            rows = list((await session.execute(sources.limit(20))).all())
            invitations = list(
                await session.scalars(
                    select(Invitation)
                    .where(
                        Invitation.user_id == owner,
                        Invitation.kind == "scheduled",
                    )
                    .order_by(Invitation.created_at.desc(), Invitation.id.desc())
                    .limit(14)
                )
            )
            responses = list(
                (
                    await session.execute(
                        select(
                            InvitationResponse.invitation_id,
                            InvitationResponse.document_id,
                            InvitationResponse.invitation_question_id,
                        )
                        .where(
                            InvitationResponse.user_id == owner,
                            InvitationResponse.invitation_id.in_([item.id for item in invitations]),
                        )
                        .order_by(InvitationResponse.document_id)
                        .limit(40)
                    )
                ).all()
            )
            response_ids = {row.document_id for row in responses}
            if response_ids:
                replies = list(
                    (
                        await session.execute(
                            sources.where(ProcessingRecord.resource_id.in_(response_ids)).limit(20)
                        )
                    ).all()
                )
                rows = list({row.resource_id: row for row in [*replies, *rows]}.values())
            # Relevant replies first, then recent notes; never load an unbounded directory.
            rows.sort(
                key=lambda row: (row.resource_id not in response_ids, -row.accepted_at.timestamp())
            )
            rows = rows[:20]
            invitation_ids = [item.id for item in invitations]
            shows = list(
                (
                    await session.execute(
                        select(
                            InvitationInteractionRecord.invitation_id,
                            InvitationInteractionRecord.question_id,
                        )
                        .where(
                            InvitationInteractionRecord.user_id == owner,
                            InvitationInteractionRecord.invitation_id.in_(invitation_ids),
                            InvitationInteractionRecord.kind == "shown",
                        )
                        .group_by(
                            InvitationInteractionRecord.invitation_id,
                            InvitationInteractionRecord.question_id,
                        )
                        .limit(126)
                    )
                ).all()
            )
            feedback = list(
                await session.scalars(
                    select(InvitationFeedback)
                    .where(
                        InvitationFeedback.user_id == owner,
                        InvitationFeedback.invitation_id.in_(invitation_ids),
                    )
                    .order_by(InvitationFeedback.recorded_at.desc(), InvitationFeedback.id.desc())
                    .limit(126)
                )
            )
            history = [invitation_history(item, responses, shows, feedback) for item in invitations]
            topics = list(
                (
                    await session.execute(
                        select(InvitationTopic, PersonalTopicDescription.label)
                        .join(
                            PersonalTopicDescription,
                            PersonalTopicDescription.topic_id == InvitationTopic.id,
                        )
                        .where(InvitationTopic.user_id == owner)
                        .order_by(InvitationTopic.id)
                        .limit(65)
                    )
                ).all()
            )
            return (
                [(row.resource_id, row.accepted_at) for row in rows],
                history,
                [
                    TopicDescription(topic=topic_snapshot(topic), label=label)
                    for topic, label in topics
                ],
            )

    async def accept(self, context, snapshot, proposals, selection):
        # Same lock order as finalizer: preference, preparation, then fenced job.
        async with database_errors(), self.sessions.begin() as session:
            preference = await session.scalar(
                select(InvitationPreference)
                .where(InvitationPreference.user_id == context.record.user_id)
                .with_for_update()
            )
            row = await session.scalar(
                select(QuestionPreparation)
                .where(
                    QuestionPreparation.id == context.record.resource_id,
                    QuestionPreparation.user_id == context.record.user_id,
                )
                .with_for_update()
            )
            job = await session.scalar(
                select(ProcessingRecord)
                .where(ProcessingRecord.id == context.record.id)
                .with_for_update()
            )
            now = await session.scalar(select(func.clock_timestamp()))
            if (
                not job
                or job.status != "running"
                or job.fencing_token != context.record.fencing_token
                or job.lease_owner != context.record.lease_owner
                or job.lease_expires_at <= now
            ):
                raise LeaseLost()
            workspace = await session.get(UserWorkspace, context.record.user_id)
            if (
                not row
                or not preference
                or not preference.enabled
                or not workspace
                or workspace.status != "active"
                or row.status not in {"pending", "ready"}
                or now >= row.due_at
                or preference.next_due_at != row.due_at
                or preference.updated_at != row.preference_version
            ):
                return False
            if row.status == "pending":
                await ensure_metric(session, job)
                metric = await session.get(QuestionPreparationMetric, job.id)
                metric.ready_at = now
                row.snapshot = snapshot.model_dump(mode="json")
                row.proposals = proposals.model_dump(mode="json")
                row.selection = selection
                row.status = "ready"
            return True

    async def expired(self, now, limit=50):
        async with database_errors(), self.sessions() as session:
            return [
                (row.user_id, row.id)
                for row in await session.scalars(
                    select(QuestionPreparation)
                    .where(QuestionPreparation.expires_at <= now)
                    .order_by(QuestionPreparation.expires_at)
                    .limit(limit)
                )
            ]

    async def remove(self, owner, identifier):
        from sqlalchemy import delete

        async with database_errors(), self.sessions.begin() as session:
            await session.execute(
                delete(QuestionPreparation).where(
                    QuestionPreparation.id == identifier, QuestionPreparation.user_id == owner
                )
            )


def invitation_history(invitation, responses, shows, feedback):
    package = (
        InvitationQuestionSet.model_validate(invitation.question_set)
        if invitation.question_set
        else legacy_question_set(invitation.id, invitation.question)
    )
    replies = [item for item in responses if item.invitation_id == invitation.id]
    seen = {item.question_id for item in shows if item.invitation_id == invitation.id}
    opinions = [item for item in feedback if item.invitation_id == invitation.id]
    actual = (
        seen
        | {item.invitation_question_id or package.default_question_id for item in replies}
        | {item.question_id for item in opinions}
    )
    questions = []
    for group in package.question_groups:
        for question in group.questions:
            if question.id not in actual:
                continue
            latest = next((item for item in opinions if item.question_id == question.id), None)
            questions.append(
                dict(
                    id=str(question.id),
                    text=question.text,
                    depth=question.depth,
                    shown=question.id in seen,
                    responses=[
                        str(item.document_id)
                        for item in replies
                        if (item.invitation_question_id or package.default_question_id)
                        == question.id
                    ],
                    feedback=latest.value if latest else None,
                )
            )
    return dict(
        id=str(invitation.id),
        question=invitation.question,
        source=invitation.source,
        created_at=invitation.created_at.isoformat(),
        questions=questions,
        responses=[str(item.document_id) for item in replies],
    )
