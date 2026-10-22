"""API contracts independent of the future Laboratory UI."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from src.extractors.personal_axes.contracts import AxisSpecification


class PreviewError(BaseModel):
    code: str
    retryable: bool


class NoteProgress(BaseModel):
    document_id: UUID
    status: str
    error: PreviewError | None


class PreviewSnapshot(BaseModel):
    id: UUID
    draft_id: UUID
    revision: int
    revision_hash: str
    specification_hash: str | None
    expires_at: datetime
    status: str
    stage: str
    notes: list[NoteProgress]
    error: PreviewError | None


class EvidenceView(BaseModel):
    quote: str
    start_char: int
    end_char: int


class FindingView(BaseModel):
    id: str
    title: str
    content: str
    tags: list[str]
    evidence: list[EvidenceView]


class PreviewDocument(BaseModel):
    document_id: UUID
    run_id: UUID
    source_hash: str
    title: str
    status: str
    findings: list[FindingView]
    warnings: list[str]


class PreviewNode(BaseModel):
    id: str
    type: str
    label: str
    document_id: UUID | None = None
    finding_id: UUID | None = None
    tags_complete: bool = False
    source_hash: str | None = None


class PreviewEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str
    quote: str | None = None
    start_char: int | None = None
    end_char: int | None = None


class PreviewGraph(BaseModel):
    root_id: str
    nodes: list[PreviewNode]
    edges: list[PreviewEdge]


class PreviewResults(BaseModel):
    preview: PreviewSnapshot
    documents: list[PreviewDocument]
    graph: PreviewGraph


class AxisVersionResponse(BaseModel):
    id: UUID
    number: int
    title: str
    purpose: str
    specification: AxisSpecification
    specification_hash: str
    created_at: datetime


class AxisResponse(BaseModel):
    id: UUID
    enabled: bool
    current_version_id: UUID
    version: AxisVersionResponse


class AxesPage(BaseModel):
    items: list[AxisResponse]
    next_offset: int | None


class AxisEnabled(BaseModel):
    enabled: bool


class ActiveEvidence(EvidenceView):
    id: UUID


class ActiveFinding(BaseModel):
    node_id: str
    source_hash: str
    id: UUID
    document_id: UUID
    axis_id: UUID
    version_id: UUID
    run_id: UUID
    title: str
    content: str
    tags: list[str]
    evidence: list[ActiveEvidence]
    document_title: str


class ActiveFindingsPage(BaseModel):
    axis_id: UUID
    version_id: UUID | None
    items: list[ActiveFinding]
    next_cursor: str | None
    limit: int


class ActiveNode(PreviewNode):
    axis_id: UUID | None = None
    version_id: UUID | None = None
    run_id: UUID | None = None


class ActiveEdge(PreviewEdge):
    document_id: UUID | None = None
    axis_id: UUID | None = None
    version_id: UUID | None = None
    run_id: UUID | None = None


class NeighborsPage(BaseModel):
    root_id: str
    nodes: list[ActiveNode]
    edges: list[ActiveEdge]
    next_cursor: str | None
    limit: int


class ActiveNeighbors(NeighborsPage):
    axis_id: UUID
    version_id: UUID | None


class PreviewNeighbors(NeighborsPage):
    preview_id: UUID
    revision_hash: str


class AxisTag(BaseModel):
    id: str
    key: str
    label: str
    document_count: int


class AxisTagsPage(BaseModel):
    axis_id: UUID
    version_id: UUID | None
    items: list[AxisTag]
    next_cursor: str | None


class LaboratoryPreferences(BaseModel):
    welcome_dismissed: bool


class LaboratoryPreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    welcome_dismissed: Literal[True]


class LaboratoryContext(BaseModel):
    enabled: bool
    welcome_dismissed: bool
    sample_size: int = 5
    title_limit: int = 200
    purpose_limit: int = 8000
    adjustment_limit: int = 4000
    max_adjustments: int = 20
