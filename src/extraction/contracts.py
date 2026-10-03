"""Versioned, provider-neutral contracts for structured knowledge extraction."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ClaimType(str, Enum):
    BELIEF = "belief"
    DESIRE = "desire"
    CONCERN = "concern"
    OBSERVATION = "observation"
    DECISION = "decision"
    PREFERENCE = "preference"
    HYPOTHESIS = "hypothesis"


class RelationshipType(str, Enum):
    RELATES_TO = "RELATES_TO"
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    ABOUT = "ABOUT"
    EXPRESSES_EMOTION = "EXPRESSES_EMOTION"
    DESIRES = "DESIRES"
    FEARS = "FEARS"
    VALUES = "VALUES"
    QUESTIONS = "QUESTIONS"
    DECIDES = "DECIDES"
    ASSOCIATES_WITH = "ASSOCIATES_WITH"


class ExtractionModel(BaseModel):
    """Base model that keeps generated output closed to undeclared fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Evidence(ExtractionModel):
    """A literal fragment plus a server-derived location in its source document."""

    quote: str = Field(min_length=1)
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, gt=0)
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)


class Concept(ExtractionModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)


class Entity(ExtractionModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    type: str = Field(min_length=1)
    evidence: list[Evidence] = Field(min_length=1)


class Claim(ExtractionModel):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    type: ClaimType
    evidence: list[Evidence] = Field(min_length=1)


class ExtractionReference(ExtractionModel):
    kind: Literal["concept", "entity", "claim"]
    id: str = Field(min_length=1)


class Relationship(ExtractionModel):
    source: ExtractionReference
    type: RelationshipType
    target: ExtractionReference
    evidence: list[Evidence] = Field(min_length=1)


class ExtractionResult(ExtractionModel):
    """Structured extraction enriched with source locations by the application."""

    title: str | None = Field(default=None, min_length=1, max_length=80)
    concepts: list[Concept]
    entities: list[Entity]
    claims: list[Claim]
    relationships: list[Relationship]

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return " ".join(value.split())
