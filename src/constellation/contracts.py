"""Versioned comparison result, separate from immutable document extractions."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from src.embeddings.contracts import EvidenceReference


class LinkType(str, Enum):
    SAME_REFERENT = "SAME_REFERENT"
    REVISITS = "REVISITS"
    SHIFTS = "SHIFTS"
    IN_TENSION = "IN_TENSION"


class LinkChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_claim_id: str
    relation_type: LinkType


class LinkChoices(BaseModel):
    model_config = ConfigDict(extra="forbid")

    links: list[LinkChoice]


class CrossDocumentLink(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_claim_id: str
    target_claim_id: str
    source_document_id: str
    target_document_id: str
    relation_type: LinkType
    source_evidence: list[EvidenceReference] = Field(min_length=1)
    target_evidence: list[EvidenceReference] = Field(min_length=1)
    similarity: float
    profile: str = "link-v1"


class LinkReport(BaseModel):
    document_id: str
    run_id: str
    profile: str = "link-v1"
    compared_pairs: int
    persisted: bool
    links: list[CrossDocumentLink]
