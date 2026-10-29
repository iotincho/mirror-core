"""Versioned question-set contracts; not yet wired into the invitation runtime."""

from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Depth = Literal["gentle", "middle", "deep"]
FeedbackValue = Literal["helpful", "unrelated", "not_now", "closed", "do_not_prompt"]


class FrozenQuestionModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class InvitationQuestion(FrozenQuestionModel):
    id: UUID
    depth: Depth | None
    text: str = Field(min_length=1, max_length=240, repr=False)

    @field_validator("text")
    @classmethod
    def visible_text(cls, value: str) -> str:
        if not value.strip() or value != value.strip() or "\n" in value or "\r" in value:
            raise ValueError("invalid_question_text")
        return value


class QuestionGroup(FrozenQuestionModel):
    id: UUID
    source: Literal["generic", "personalized"]
    layout: Literal["depths", "legacy"] = "depths"
    questions: tuple[InvitationQuestion, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def valid_depths(self):
        if len({question.id for question in self.questions}) != len(self.questions):
            raise ValueError("duplicate_question_id")
        depths = tuple(question.depth for question in self.questions)
        expected = (None,) if self.layout == "legacy" else ("gentle", "middle", "deep")
        if depths != expected:
            raise ValueError("invalid_question_depths")
        return self


class InvitationQuestionSet(FrozenQuestionModel):
    """Additive public fragment; id and question keep their existing meaning."""

    id: UUID
    question_schema_version: Literal["1"] = "1"
    question: str = Field(repr=False)
    default_question_id: UUID
    question_groups: tuple[QuestionGroup, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def consistent_package(self):
        if len({group.id for group in self.question_groups}) != len(self.question_groups):
            raise ValueError("duplicate_group_id")
        questions = tuple(q for group in self.question_groups for q in group.questions)
        if len({question.id for question in questions}) != len(questions):
            raise ValueError("duplicate_question_id")
        if any(group.layout == "legacy" for group in self.question_groups):
            if len(self.question_groups) != 1 or len(questions) != 1:
                raise ValueError("legacy_package_must_be_single_question")
            default = questions[0]
        else:
            default = self.question_groups[0].questions[1]
        if self.default_question_id != default.id or self.question != default.text:
            raise ValueError("default_question_mismatch")
        return self


def legacy_question_set(invitation_id: UUID, question: str) -> InvitationQuestionSet:
    """Stable read projection; no historical row or question text is rewritten."""
    item = InvitationQuestion(
        id=uuid5(invitation_id, "legacy-question-v1"), depth=None, text=question
    )
    return InvitationQuestionSet(
        id=invitation_id,
        question=question,
        default_question_id=item.id,
        question_groups=(
            QuestionGroup(
                id=uuid5(invitation_id, "legacy-group-v1"),
                source="generic",
                layout="legacy",
                questions=(item,),
            ),
        ),
    )


class InvitationResponseReference(FrozenQuestionModel):
    invitation_id: UUID | None = None
    invitation_question_id: UUID | None = None

    @model_validator(mode="after")
    def question_requires_invitation(self):
        if self.invitation_question_id is not None and self.invitation_id is None:
            raise ValueError("question_requires_invitation")
        return self


def resolve_response_question(
    package: InvitationQuestionSet, reference: InvitationResponseReference
) -> InvitationQuestion:
    """Membership check after the use case has resolved the owner's invitation."""
    if reference.invitation_id != package.id:
        raise ValueError("invitation_not_found")
    identifier = reference.invitation_question_id or package.default_question_id
    for group in package.question_groups:
        for question in group.questions:
            if question.id == identifier:
                return question
    raise ValueError("invitation_question_not_found")


class InvitationFeedbackChoice(FrozenQuestionModel):
    invitation_question_id: UUID
    value: FeedbackValue


class InvitationInteraction(FrozenQuestionModel):
    event_id: UUID
    invitation_question_id: UUID
    kind: Literal["shown", "another_requested", "passed"]


class InvitationInteractions(FrozenQuestionModel):
    events: tuple[InvitationInteraction, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_events(self):
        if len({event.event_id for event in self.events}) != len(self.events):
            raise ValueError("duplicate_interaction_event")
        return self
