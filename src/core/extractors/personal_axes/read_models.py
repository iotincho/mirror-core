"""Facts read from an axis projection; evidence remains attached to its relationship."""

from src.core.extractors.contracts import FrozenModel


class FindingFacts(FrozenModel):
    id: str
    document_id: str
    axis_id: str
    version_id: str
    run_id: str
    title: str
    content: str
    tags: tuple[str, ...]
    content_hash: str


class EvidenceFacts(FrozenModel):
    finding_id: str
    extraction_id: str
    extraction_axis: str
    extraction_version: str
    extraction_document: str
    id: str
    quote: str
    start_char: object
    end_char: object
    axis_id: str
    version_id: str
    run_id: str
    document_id: str


class TagFacts(FrozenModel):
    id: str
    document_id: str
    tags: tuple[str, ...]


class CoverageFacts(FrozenModel):
    document_id: str
    version_id: str
    content_hash: str
    profile_hash: str | None = None
    findings_count: int = 0
