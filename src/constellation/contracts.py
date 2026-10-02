"""Versioned comparison result, separate from immutable document extractions."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.embeddings.contracts import EvidenceReference
from src.extraction.contracts import Claim, Concept, Entity, ExtractionResult, Relationship
from src.services.extraction_store import ExtractionRun


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


class DiscoveryLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # An existing source graph ID, or a local ID from additions.claims.
    source_claim_id: str
    target_claim_id: str
    relation_type: LinkType


class SupplementalItems(ExtractionResult):
    concepts: list[Concept] = Field(max_length=20)
    entities: list[Entity] = Field(max_length=20)
    claims: list[Claim] = Field(max_length=20)
    relationships: list[Relationship] = Field(max_length=50)


class DocumentLinkAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    additions: SupplementalItems
    links: list[DiscoveryLink] = Field(max_length=100)


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
    supplemental_extraction: ExtractionRun | None = None
    embeddings_status: str = "not_required"
    warnings: list[str] = Field(default_factory=list)


class SavedLink(BaseModel):
    """One conceptual link; its two navigation edges are not exposed as duplicates."""

    link_id: str
    source_claim_id: str
    target_claim_id: str
    source_document_id: str
    target_document_id: str
    relation_type: LinkType
    source_evidence: list[EvidenceReference]
    target_evidence: list[EvidenceReference]
    profile: str


class LinkNeighborhood(BaseModel):
    document_id: str
    neighbor_ids: list[str]
    total_neighbors: int
    next_offset: int | None
    links: list[SavedLink]
    links_truncated: bool = False


class ExtractionSummary(BaseModel):
    id: UUID
    profile_name: str
    status: str
    created_at: datetime
    claim_count: int
    ready: bool
    origin: str = "extraction"
    graph_persisted: bool = False
