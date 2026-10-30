"""Conservative, pure rules for candidate eligibility and explicit topic boundaries."""

from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from src.core.exteriorization.question_contracts import (
    FeedbackValue,
    FrozenQuestionModel,
    QuestionGroup,
)


class QuestionPolicy(FrozenQuestionModel):
    version: Literal["daily-question-policy-v1"] = "daily-question-policy-v1"
    max_groups: int = Field(default=3, ge=2, le=3)
    max_followups: int = Field(default=1, ge=1)
    rest_days: int = Field(default=7, ge=1)
    silence_hours: int = Field(default=48, ge=1)
    general_every: int = Field(default=4, ge=2)


class TopicState(FrozenQuestionModel):
    id: UUID
    user_id: UUID
    scope: Literal["personal", "catalog"]
    status: Literal["open", "paused", "closed", "do_not_prompt"] = "open"
    restricted_at: AwareDatetime | None = None
    paused_until: AwareDatetime | None = None
    last_feedback_sequence: int = Field(default=0, ge=0)
    reopened_at: AwareDatetime | None = None
    reopened_by_document_id: UUID | None = None

    @model_validator(mode="after")
    def coherent_state(self):
        if self.status != "open" and self.restricted_at is None:
            raise ValueError("topic_restriction_requires_time")
        if self.status == "paused":
            if self.paused_until is None or self.paused_until <= self.restricted_at:
                raise ValueError("topic_pause_requires_deadline")
        elif self.paused_until is not None:
            raise ValueError("unexpected_pause_deadline")
        if (self.reopened_at is None) != (self.reopened_by_document_id is None):
            raise ValueError("topic_reopening_requires_evidence")
        return self


class TopicFeedback(FrozenQuestionModel):
    user_id: UUID
    topic_id: UUID
    value: FeedbackValue
    sequence: int = Field(ge=1)
    received_at: AwareDatetime


def apply_topic_feedback(
    topic: TopicState, event: TopicFeedback, policy: QuestionPolicy
) -> TopicState:
    """Sequence is assigned by persistence, never supplied by a public client."""
    if event.user_id != topic.user_id or event.topic_id != topic.id:
        raise ValueError("feedback_topic_owner_mismatch")
    if event.sequence <= topic.last_feedback_sequence:
        return topic
    changes = {"last_feedback_sequence": event.sequence}
    strength = {"open": 0, "paused": 1, "closed": 2, "do_not_prompt": 3}
    status = {"not_now": "paused", "closed": "closed", "do_not_prompt": "do_not_prompt"}
    desired = status.get(event.value)
    if desired is not None and strength[desired] >= strength[topic.status]:
        changes.update(
            status=desired,
            restricted_at=event.received_at,
            paused_until=(
                event.received_at + timedelta(days=policy.rest_days)
                if desired == "paused"
                else None
            ),
            reopened_at=None,
            reopened_by_document_id=None,
        )
    return topic.model_copy(update=changes)


class TopicReopeningEvidence(FrozenQuestionModel):
    user_id: UUID
    topic_id: UUID
    document_id: UUID
    authored_at: AwareDatetime
    accepted_at: AwareDatetime
    association: Literal["confirmed", "uncertain"]
    intent: Literal["explicit", "mention", "rejected", "uncertain"]
    original_available: bool


def reopen_topic(
    topic: TopicState, evidence: TopicReopeningEvidence, *, now: datetime
) -> TopicState:
    """Evidence assessment is supplied by the context/proposal use case."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("aware_time_required")
    if evidence.user_id != topic.user_id or evidence.topic_id != topic.id:
        raise ValueError("reopening_topic_owner_mismatch")
    if topic.status == "open" or topic.restricted_at is None:
        return topic
    if (
        evidence.association != "confirmed"
        or evidence.intent != "explicit"
        or not evidence.original_available
        or evidence.authored_at <= topic.restricted_at
        or evidence.accepted_at <= topic.restricted_at
        or evidence.authored_at > now
        or evidence.accepted_at > now
    ):
        return topic
    return topic.model_copy(
        update={
            "status": "open",
            "paused_until": None,
            "reopened_at": now,
            "reopened_by_document_id": evidence.document_id,
        }
    )


class RankedQuestionGroup(FrozenQuestionModel):
    group: QuestionGroup
    topic: TopicState
    evidence_valid: bool
    last_shown_at: AwareDatetime | None = None
    last_shown_answered: bool = False
    followups_since_rest: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def coherent_candidate(self):
        if self.group.layout != "depths":
            raise ValueError("legacy_group_is_not_a_candidate")
        if (self.group.source == "generic") != (self.topic.scope == "catalog"):
            raise ValueError("candidate_topic_scope_mismatch")
        if self.last_shown_at is None and (self.followups_since_rest or self.last_shown_answered):
            raise ValueError("candidate_history_requires_shown_question")
        return self


class QuestionSelectionContext(FrozenQuestionModel):
    user_id: UUID
    now: AwareDatetime
    consecutive_personalized_initials: int = Field(default=0, ge=0)


class ExcludedQuestionGroup(FrozenQuestionModel):
    group_id: UUID
    code: Literal[
        "evidence_unavailable",
        "paused",
        "closed",
        "do_not_prompt",
        "followup_rest",
        "unanswered_rest",
        "duplicate_topic",
    ]


class QuestionSelection(FrozenQuestionModel):
    policy_version: str
    group_ids: tuple[UUID, ...]
    excluded: tuple[ExcludedQuestionGroup, ...]
    requires_catalog: bool


def _exclusion(candidate: RankedQuestionGroup, now: datetime, policy: QuestionPolicy):
    topic = candidate.topic
    if not candidate.evidence_valid:
        return "evidence_unavailable"
    if topic.status in {"closed", "do_not_prompt"}:
        return topic.status
    if topic.status == "paused" and now < topic.paused_until:
        return "paused"
    shown = candidate.last_shown_at
    if shown is None or (topic.reopened_at is not None and topic.reopened_at > shown):
        return None
    if candidate.followups_since_rest >= policy.max_followups:
        if now < shown + timedelta(days=policy.rest_days):
            return "followup_rest"
    silence_at = shown + timedelta(hours=policy.silence_hours)
    if not candidate.last_shown_answered:
        if silence_at <= now < silence_at + timedelta(days=policy.rest_days):
            return "unanswered_rest"
    return None


def select_question_groups(
    context: QuestionSelectionContext,
    ranked: tuple[RankedQuestionGroup, ...],
    policy: QuestionPolicy,
) -> QuestionSelection:
    """Preserve proposed order after hard rules; never infer psychological relevance."""
    eligible = []
    excluded = []
    seen_topics = set()
    seen_groups = set()
    for candidate in ranked:
        if candidate.topic.user_id != context.user_id:
            raise ValueError("candidate_owner_mismatch")
        if candidate.group.id in seen_groups:
            raise ValueError("duplicate_candidate_group")
        seen_groups.add(candidate.group.id)
        reason = _exclusion(candidate, context.now, policy)
        if reason is None and candidate.topic.id in seen_topics:
            reason = "duplicate_topic"
        if reason:
            excluded.append(ExcludedQuestionGroup(group_id=candidate.group.id, code=reason))
        else:
            eligible.append(candidate)
            seen_topics.add(candidate.topic.id)
    generic = next((item for item in eligible if item.group.source == "generic"), None)
    if generic is None:
        return QuestionSelection(
            policy_version=policy.version,
            group_ids=(),
            excluded=tuple(excluded),
            requires_catalog=True,
        )
    if context.consecutive_personalized_initials >= policy.general_every - 1:
        eligible = [generic, *(item for item in eligible if item is not generic)]
    selected = eligible[: policy.max_groups]
    if generic not in selected:
        selected[-1] = generic
    return QuestionSelection(
        policy_version=policy.version,
        group_ids=tuple(item.group.id for item in selected),
        excluded=tuple(excluded),
        requires_catalog=False,
    )
