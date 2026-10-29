"""Detached invitation/preference/device state; private routing data is hidden from repr."""

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import UUID

from src.core.exteriorization.question_contracts import (
    InvitationQuestionSet,
    legacy_question_set,
)


class InvitationError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def session_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class InvitationPreference:
    user_id: UUID
    enabled: bool = False
    local_time: str = "20:30"
    timezone: str = "UTC"
    next_due_at: datetime | None = None
    last_test_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class PushSubscription:
    id: UUID
    user_id: UUID
    endpoint: str = field(repr=False)
    p256dh: str = field(repr=False)
    auth: str = field(repr=False)
    binding_id: UUID
    session_fingerprint: str = field(repr=False)
    active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class Invitation:
    id: UUID
    user_id: UUID
    kind: str
    local_date: date
    timezone: str
    scheduled_at: datetime
    expires_at: datetime
    occurrence_key: str
    request_key: UUID | None
    test_subscription_id: UUID | None
    source: str
    candidate_id: str
    category: str
    question: str = field(repr=False)
    engine_version: str
    catalog_version: str
    created_at: datetime
    first_opened_at: datetime | None = None
    question_set: dict | None = field(default=None, repr=False)
    question_policy: dict | None = field(default=None, repr=False)

    @property
    def questions(self) -> InvitationQuestionSet:
        if self.question_set is not None:
            return InvitationQuestionSet.model_validate(self.question_set)
        return legacy_question_set(self.id, self.question)

    @property
    def question_schema_version(self):
        return self.questions.question_schema_version

    @property
    def default_question_id(self):
        return self.questions.default_question_id

    @property
    def question_groups(self):
        return self.questions.question_groups

    @property
    def available_question_ids(self):
        return getattr(
            self,
            "_available_question_ids",
            tuple(q.id for group in self.question_groups for q in group.questions),
        )


@dataclass
class InvitationDelivery:
    id: UUID
    user_id: UUID
    invitation_id: UUID
    subscription_id: UUID
    processing_id: UUID
    status: str = "pending"
    attempts: int = 0
    next_attempt_at: datetime | None = None
    error_code: str | None = None
    accepted_at: datetime | None = None


@dataclass(frozen=True)
class PushResult:
    accepted: bool = False
    expired: bool = False
    retryable: bool = False
    code: str | None = None
