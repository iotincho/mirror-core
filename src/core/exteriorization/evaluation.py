"""Versioned synthetic evaluation contracts; semantic quality requires human review."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from src.core.exteriorization.personalization import (
    PreparationConfiguration,
    TopicDescription,
    TopicProposals,
)
from src.core.exteriorization.question_contracts import FrozenQuestionModel

REVIEW_DIMENSIONS = (
    "grounded",
    "boundaries",
    "gentle_effort",
    "depth_progression",
    "no_assumptions",
    "language",
)


class EvaluationNote(FrozenQuestionModel):
    id: UUID
    content: str = Field(min_length=1, max_length=4000, repr=False)
    authored_at: AwareDatetime
    accepted_at: AwareDatetime


class EvaluationHistory(FrozenQuestionModel):
    topic_id: UUID
    shown_at: AwareDatetime
    answered: bool = False
    followups: int = Field(default=0, ge=0, le=14)


class EvaluationExpectation(FrozenQuestionModel):
    initial: Literal["generic", "personalized", "either"]
    min_personal: int = Field(default=0, ge=0, le=2)
    max_personal: int = Field(default=2, ge=0, le=2)
    forbidden_topics: tuple[UUID, ...] = ()


class EvaluationCase(FrozenQuestionModel):
    id: str = Field(pattern=r"^[a-z0-9_]{1,60}$")
    purpose: str = Field(max_length=400)
    now: AwareDatetime
    notes: tuple[EvaluationNote, ...] = Field(max_length=3)
    topics: tuple[TopicDescription, ...] = Field(default=(), max_length=3)
    final_topics: tuple[TopicDescription, ...] = Field(default=(), max_length=3)
    history: tuple[EvaluationHistory, ...] = Field(default=(), max_length=3)
    consecutive_personalized: int = Field(default=0, ge=0, le=14)
    reference: TopicProposals
    expected: EvaluationExpectation


class EvaluationDataset(FrozenQuestionModel):
    version: Literal["daily-question-eval-v1", "daily-question-eval-v2"] = "daily-question-eval-v2"
    synthetic: Literal[True] = True
    cases: tuple[EvaluationCase, ...] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def distinct_cases(self):
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("duplicate_evaluation_case")
        return self


class EvaluationPlan(FrozenQuestionModel):
    version: Literal["daily-eval-run-v1"] = "daily-eval-run-v1"
    dataset_sha256: str
    implementation_sha256: str
    mode: Literal["reference", "live"]
    configuration: PreparationConfiguration
    max_calls: int = Field(ge=1, le=40)
    budget_usd: Decimal | None = Field(default=None, gt=0)
    input_usd_per_million: Decimal | None = Field(default=None, ge=0)
    output_usd_per_million: Decimal | None = Field(default=None, ge=0)
    price_source: str | None = Field(default=None, min_length=1, max_length=300)

    @model_validator(mode="after")
    def priced_live_run(self):
        if self.mode == "live" and any(
            value is None
            for value in (
                self.budget_usd,
                self.input_usd_per_million,
                self.output_usd_per_million,
                self.price_source,
            )
        ):
            raise ValueError("live_evaluation_requires_explicit_budget_and_prices")
        if self.mode == "live" and self.reserved_usd() > self.budget_usd:
            raise ValueError("evaluation_budget_exceeded")
        return self

    def reserved_usd(self):
        if self.input_usd_per_million is None or self.output_usd_per_million is None:
            return None
        config = self.configuration
        return (
            self.max_calls
            * (
                config.max_input_tokens * self.input_usd_per_million
                + config.max_output_tokens * self.output_usd_per_million
            )
            / Decimal(1_000_000)
        )
