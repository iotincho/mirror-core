"""Preparation consumption, source locks and topic facts in the publication transaction."""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from src.adapters.storage.postgres.invitation_models import Invitation, InvitationResponse
from src.adapters.storage.postgres.invitation_question_models import (
    InvitationInteractionRecord,
    InvitationQuestionRecord,
    InvitationTopic,
)
from src.adapters.storage.postgres.invitation_questions import topic_snapshot
from src.adapters.storage.postgres.question_preparation_models import (
    PersonalTopicDescription,
    QuestionGroupProvenance,
    QuestionPreparation,
)
from src.core.exteriorization.personalization import PersonalQuestionFact, proposal_topic_id


class PreparedQuestionTransaction:
    async def prepared_questions(self, owner, due, preference_version):
        row = await self.session.scalar(
            select(QuestionPreparation)
            .where(
                QuestionPreparation.user_id == owner,
                QuestionPreparation.due_at == due,
                QuestionPreparation.preference_version == preference_version,
            )
            .with_for_update()
        )
        if row is None:
            return None
        if row.status != "ready":
            row.status = "obsolete"
            row.decision = "not_ready"
            return None
        row.status = "consumed"
        row.decision = "catalog"
        return row.id, row.snapshot, row.proposals, row.selection, row.configuration

    async def record_question_decision(self, identifier, code):
        row = await self.session.get(QuestionPreparation, identifier)
        row.decision = code

    async def save_question_provenance(self, invitation, provenance):
        for group in invitation.question_groups:
            self.session.add(
                QuestionGroupProvenance(
                    group_id=group.id,
                    invitation_id=invitation.id,
                    user_id=invitation.user_id,
                    specification=provenance.get(
                        str(group.id), {"source": "generic", "catalog_version": "2"}
                    ),
                )
            )

    async def guard_question_sources(self, owner, identifiers):
        for identifier in sorted(identifiers):
            if not await self.session.scalar(
                select(
                    func.pg_try_advisory_xact_lock_shared(
                        func.hashtextextended(f"{owner}:{identifier}", 0)
                    )
                )
            ):
                return False
        return True

    async def personal_question_facts(self, owner, proposals):
        facts = []
        for proposal in sorted(proposals, key=lambda item: str(proposal_topic_id(owner, item))):
            identifier = proposal_topic_id(owner, proposal)
            await self.session.execute(
                insert(InvitationTopic)
                .values(
                    id=identifier,
                    user_id=owner,
                    scope="personal",
                    status="open",
                    last_feedback_sequence=0,
                )
                .on_conflict_do_nothing()
            )
            topic = await self.session.scalar(
                select(InvitationTopic)
                .where(
                    InvitationTopic.id == identifier,
                    InvitationTopic.user_id == owner,
                    InvitationTopic.scope == "personal",
                )
                .with_for_update()
            )
            if topic is None:
                raise ValueError("question_topic_owner_mismatch")
            await self.session.execute(
                insert(PersonalTopicDescription)
                .values(
                    topic_id=identifier,
                    label=proposal.label,
                    evidence=[e.model_dump(mode="json") for e in proposal.evidence],
                )
                .on_conflict_do_nothing()
            )
            shown = list(
                (
                    await self.session.execute(
                        select(
                            InvitationInteractionRecord.invitation_id,
                            func.min(InvitationInteractionRecord.recorded_at).label("shown_at"),
                        )
                        .join(
                            InvitationQuestionRecord,
                            InvitationQuestionRecord.id == InvitationInteractionRecord.question_id,
                        )
                        .join(
                            Invitation, Invitation.id == InvitationInteractionRecord.invitation_id
                        )
                        .where(
                            InvitationInteractionRecord.user_id == owner,
                            InvitationQuestionRecord.topic_id == identifier,
                            InvitationInteractionRecord.kind == "shown",
                            Invitation.kind == "scheduled",
                        )
                        .group_by(InvitationInteractionRecord.invitation_id)
                        .order_by(func.min(InvitationInteractionRecord.recorded_at).desc())
                        .limit(16)
                    )
                ).all()
            )
            answered = False
            count = 0
            if shown:
                answered = (
                    await self.session.scalar(
                        select(InvitationResponse.document_id)
                        .join(
                            InvitationQuestionRecord,
                            InvitationQuestionRecord.id
                            == InvitationResponse.invitation_question_id,
                        )
                        .where(
                            InvitationResponse.user_id == owner,
                            InvitationResponse.invitation_id == shown[0].invitation_id,
                            InvitationQuestionRecord.topic_id == identifier,
                        )
                        .limit(1)
                    )
                    is not None
                )
                for current, previous in zip(shown, shown[1:]):
                    if current.shown_at - previous.shown_at >= timedelta(days=7):
                        break
                    count += 1
            facts.append(
                PersonalQuestionFact(
                    topic_snapshot(topic), shown[0].shown_at if shown else None, answered, count
                )
            )
        return facts

    async def personalized_initials(self, owner):
        sources = await self.session.scalars(
            select(Invitation.source)
            .where(Invitation.user_id == owner, Invitation.kind == "scheduled")
            .order_by(Invitation.created_at.desc(), Invitation.id.desc())
            .limit(14)
        )
        count = 0
        for source in sources:
            if source != "personalized":
                break
            count += 1
        return count

    async def question_topic_states(self, owner, invitation_id):
        rows = await self.session.execute(
            select(InvitationQuestionRecord.id, InvitationTopic)
            .join(InvitationTopic, InvitationTopic.id == InvitationQuestionRecord.topic_id)
            .where(
                InvitationQuestionRecord.user_id == owner,
                InvitationTopic.user_id == owner,
                InvitationQuestionRecord.invitation_id == invitation_id,
            )
        )
        return [(identifier, topic_snapshot(topic)) for identifier, topic in rows]
