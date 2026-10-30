"""Record optional opinions and observations without waiting for document ingestion."""

from uuid import uuid4

from src.core.exteriorization.models import InvitationError
from src.core.exteriorization.question_contracts import (
    InvitationResponseReference,
    resolve_response_question,
)
from src.core.exteriorization.question_policy import (
    QuestionPolicy,
    TopicFeedback,
    apply_topic_feedback,
)
from src.core.processing.submissions import fingerprint


class RecordInvitationActivity:
    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def check_question(invitation, question_id):
        try:
            resolve_response_question(
                invitation.questions,
                InvitationResponseReference(
                    invitation_id=invitation.id,
                    invitation_question_id=question_id,
                ),
            )
        except ValueError:
            raise InvitationError("invitation_question_not_found") from None

    async def feedback(self, owner, invitation_id, choice, key):
        request_hash = fingerprint(
            {
                "invitation_id": str(invitation_id),
                **choice.model_dump(mode="json"),
            }
        )
        async with self.repository.transaction() as transaction:
            # Same lock order as generation: owner preference, invitation, topic.
            await transaction.preference(owner)
            invitation = await transaction.invitation(owner, invitation_id)
            self.check_question(invitation, choice.invitation_question_id)
            previous = await transaction.activity_receipt(owner, "feedback", key, request_hash)
            if previous is not None:
                return previous
            now = await transaction.now()
            topic = await transaction.feedback_topic(
                owner, invitation_id, choice.invitation_question_id
            )
            sequence = None
            if topic is not None and invitation.kind == "scheduled":
                sequence = topic.last_feedback_sequence + 1
                updated = apply_topic_feedback(
                    topic,
                    TopicFeedback(
                        user_id=owner,
                        topic_id=topic.id,
                        value=choice.value,
                        sequence=sequence,
                        received_at=now,
                    ),
                    QuestionPolicy.model_validate(invitation.question_policy)
                    if invitation.question_policy
                    else QuestionPolicy(),
                )
                await transaction.save_topic(updated)
            identifier = uuid4()
            body = dict(
                id=str(identifier),
                invitation_id=str(invitation_id),
                invitation_question_id=str(choice.invitation_question_id),
                value=choice.value,
                recorded_at=now.isoformat(),
            )
            await transaction.save_activity_receipt(
                owner,
                "feedback",
                key,
                request_hash,
                body,
                identifier,
            )
            await transaction.append_feedback(
                owner,
                invitation_id,
                choice.invitation_question_id,
                choice.value,
                now,
                identifier,
                sequence,
            )
            return body

    async def interactions(self, owner, invitation_id, batch, key):
        request_hash = fingerprint(
            {
                "invitation_id": str(invitation_id),
                **batch.model_dump(mode="json"),
            }
        )
        async with self.repository.transaction() as transaction:
            await transaction.preference(owner)
            invitation = await transaction.invitation(owner, invitation_id)
            for event in batch.events:
                self.check_question(invitation, event.invitation_question_id)
            previous = await transaction.activity_receipt(owner, "interactions", key, request_hash)
            if previous is not None:
                return previous
            await transaction.record_interactions(
                owner, invitation_id, batch.events, await transaction.now()
            )
            body = {"recorded_event_ids": [str(event.event_id) for event in batch.events]}
            await transaction.save_activity_receipt(
                owner,
                "interactions",
                key,
                request_hash,
                body,
                uuid4(),
            )
            return body
