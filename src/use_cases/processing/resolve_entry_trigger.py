"""Resolve new capture origins while preserving legacy invitation identity."""

from src.core.domain.entry_triggers import (
    AcceptedEmotionTrigger,
    EmotionTrigger,
    InvitationTrigger,
    manifest_emotion_trigger,
)
from src.core.extractors.emotions import label_key
from src.core.graph.ports import GraphPersistenceError
from src.core.processing.submissions import SubmissionConflict


async def invitation_fields(submissions, owner, trigger, invitation_id, question_id):
    if isinstance(trigger, EmotionTrigger):
        if invitation_id is not None or question_id is not None:
            raise SubmissionConflict("entry_trigger_conflict")
        return None, None
    if not isinstance(trigger, InvitationTrigger):
        return invitation_id, question_id
    if invitation_id is None:
        if question_id is not None:
            raise ValueError("question_requires_invitation")
        return trigger.invitation_id, trigger.question_id
    if invitation_id != trigger.invitation_id:
        raise SubmissionConflict("entry_trigger_conflict")
    if question_id != trigger.question_id:
        # Resolve omitted variants just as legacy requests do.
        legacy = await submissions.validate_invitation(owner, invitation_id, question_id)
        typed = await submissions.validate_invitation(owner, invitation_id, trigger.question_id)
        if legacy != typed:
            raise SubmissionConflict("entry_trigger_conflict")
    return invitation_id, trigger.question_id


async def resolve_emotion_trigger(
    submissions, lookup, owner, operation, key, trigger, *, resource_id=None
):
    if not isinstance(trigger, EmotionTrigger):
        return None
    canonical = label_key(trigger.emotion_key)
    if not canonical or len(canonical) > 240:
        raise ValueError("invalid_emotion_key")
    previous = await submissions.get(owner, operation, key, resource_id=resource_id)
    if previous is not None:
        accepted = manifest_emotion_trigger(previous.manifest)
        if accepted is None or accepted.emotion_key != canonical:
            raise SubmissionConflict("idempotency_conflict")
        return accepted
    if lookup is None:
        raise GraphPersistenceError("Emotion lookup is unavailable")
    label = await lookup.resolve_emotion_label(canonical)
    return AcceptedEmotionTrigger(kind="emotion", emotion_key=canonical, label=label)
