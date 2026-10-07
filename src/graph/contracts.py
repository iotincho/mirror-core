"""Presentation contract retained for the graph visualization and future link analysis."""

from enum import Enum

from pydantic import BaseModel


class EvidenceReference(BaseModel):
    quote: str
    start_line: int | None = None
    end_line: int | None = None


class LinkType(str, Enum):
    SAME_REFERENT = "SAME_REFERENT"
    REVISITS = "REVISITS"
    SHIFTS = "SHIFTS"
    IN_TENSION = "IN_TENSION"


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


class GraphNode(BaseModel):
    id: str
    type: str
    label: str
    layer: str | None = None
    document_id: str | None = None
    quote: str | None = None
    profile_id: str | None = None


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str
    layer: str


class ExtractionGraph(BaseModel):
    document_id: str
    root_id: str
    layers: list[str]
    nodes: list[GraphNode]
    edges: list[GraphEdge]
