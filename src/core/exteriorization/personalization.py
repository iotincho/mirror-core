"""Bounded proposal contracts and reproducible selection, independent of providers."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid5

from pydantic import AwareDatetime, Field, field_validator, model_validator

from src.core.exteriorization.contracts import Trigger
from src.core.exteriorization.question_contracts import (
    FrozenQuestionModel,
    InvitationQuestion,
    InvitationQuestionSet,
    QuestionGroup,
)
from src.core.exteriorization.question_policy import QuestionPolicy, TopicState


@dataclass(frozen=True)
class PersonalQuestionFact:
    topic: TopicState
    last_shown_at: datetime | None = None
    answered: bool = False
    followups: int = 0


@dataclass(frozen=True)
class PreparedQuestions:
    trigger: Trigger
    package: InvitationQuestionSet
    bindings: tuple
    provenance: dict

    def __iter__(self):
        return iter((self.trigger, self.package, self.bindings))


class PreparationConfiguration(FrozenQuestionModel):
    version: Literal["daily-preparation-v1"] = "daily-preparation-v1"
    prompt_version: Literal["daily-proposals-v1"] = "daily-proposals-v1"
    selector_version: Literal["daily-selection-v1"] = "daily-selection-v1"
    provider: Literal["openai"] = "openai"
    model: str = Field(min_length=1, max_length=100)
    max_input_tokens: int = Field(default=24000, ge=8000, le=64000)
    max_output_tokens: int = Field(default=3000, ge=1000, le=8000)
    timeout_seconds: int = Field(default=45, ge=1, le=120)
    concurrency: int = Field(default=2, ge=1, le=8)
    lead_minutes: int = Field(default=30, ge=1, le=120)
    policy: QuestionPolicy = Field(default_factory=QuestionPolicy)


class SourceReference(FrozenQuestionModel):
    document_id: UUID
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    authored_at: AwareDatetime
    accepted_at: AwareDatetime
    excerpt_chars: int = Field(ge=1)
    truncated: bool


class TopicDescription(FrozenQuestionModel):
    topic: TopicState
    label: str = Field(max_length=120, repr=False)


class PreparationSnapshot(FrozenQuestionModel):
    captured_at: AwareDatetime
    sources: tuple[SourceReference, ...] = Field(max_length=20)
    history: tuple[dict, ...] = Field(max_length=14)
    topics: tuple[TopicDescription, ...] = Field(max_length=64)


class EvidenceReference(FrozenQuestionModel):
    document_id: UUID
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class ProposedDepths(FrozenQuestionModel):
    gentle: str = Field(min_length=5, max_length=240, repr=False)
    middle: str = Field(min_length=5, max_length=240, repr=False)
    deep: str = Field(min_length=5, max_length=240, repr=False)

    @field_validator("gentle", "middle", "deep")
    @classmethod
    def single_question(cls, value):
        if value != value.strip() or "\n" in value or "\r" in value or value.count("?") != 1:
            raise ValueError("single_question_required")
        return value


class TopicProposal(FrozenQuestionModel):
    # Existing identity wins over labels; uncertain equivalence must be omitted.
    existing_topic_id: UUID | None
    label: str = Field(min_length=1, max_length=120, repr=False)
    evidence: tuple[EvidenceReference, ...] = Field(min_length=1, max_length=3)
    basis: Literal["explicit", "inferred"]
    intent: Literal["explore", "reopen", "mention", "closed", "uncertain"]
    effort: Literal["low", "medium"]
    questions: ProposedDepths

    @model_validator(mode="after")
    def distinct_questions(self):
        if len(set(self.questions.model_dump().values())) != 3:
            raise ValueError("distinct_depths_required")
        return self


class TopicProposals(FrozenQuestionModel):
    proposals: tuple[TopicProposal, ...] = Field(max_length=3)


def content_hash(document):
    # Titles may change asynchronously and are not evidence.
    return hashlib.sha256(document.content.encode("utf-8")).hexdigest()


def encoded_input(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def proposal_topic_id(owner, proposal):
    if proposal.existing_topic_id:
        return proposal.existing_topic_id
    # New topic identity is anchored to evidence, not just a generated title.
    evidence = proposal.evidence[0]
    return uuid5(owner, f"personal-topic-v1:{evidence.document_id}:{evidence.start}:{evidence.end}")


def proposal_group(preparation_id, owner, proposal):
    topic_id = proposal_topic_id(owner, proposal)
    group_id = uuid5(preparation_id, f"personal-group-v1:{topic_id}")
    return QuestionGroup(
        id=group_id,
        source="personalized",
        questions=tuple(
            InvitationQuestion(id=uuid5(group_id, depth), depth=depth, text=text)
            for depth, text in proposal.questions.model_dump().items()
        ),
    )


def validate_proposals(value, snapshot):
    result = TopicProposals.model_validate(value)
    sources = {source.document_id: source for source in snapshot.sources}
    topics = {item.topic.id for item in snapshot.topics if item.topic.scope == "personal"}
    seen = set()
    for proposal in result.proposals:
        identifier = proposal_topic_id(UUID(int=0), proposal)
        if identifier in seen:
            raise ValueError("duplicate_proposal_topic")
        seen.add(identifier)
        if proposal.existing_topic_id and proposal.existing_topic_id not in topics:
            raise ValueError("unknown_topic_reference")
        for evidence in proposal.evidence:
            source = sources.get(evidence.document_id)
            if source is None or not 0 <= evidence.start < evidence.end <= source.excerpt_chars:
                raise ValueError("invalid_evidence_reference")
    return result


def proposal_order(proposals, sources):
    """Lexicographic criteria, no fabricated psychological score or response-rate goal."""
    by_id = {item.document_id: item for item in sources}
    return sorted(
        proposals,
        key=lambda item: (
            item.basis != "explicit",
            -max(by_id[e.document_id].authored_at.timestamp() for e in item.evidence),
            item.effort != "low",
            str(proposal_topic_id(UUID(int=0), item)),
        ),
    )
