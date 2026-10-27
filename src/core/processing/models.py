"""Detached application state; SQL mappings live exclusively in the PostgreSQL adapter."""

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4


@dataclass(kw_only=True)
class ProcessingJob:
    id: UUID = field(default_factory=uuid4)
    user_id: UUID
    workflow: str
    workflow_version: int = 1
    resource_kind: str
    resource_id: UUID
    status: str = "queued"
    stage: str
    config: dict = field(default_factory=dict)
    checkpoints: dict = field(default_factory=dict)
    version: int = 1
    generation: int = 1
    attempts: int = 0
    stage_attempts: int = 0
    fencing_token: int = 0
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    error_code: str | None = None
    retryable: bool = False
    document_id: UUID | None = None
    extraction_run_id: UUID | None = None
    parent_processing_id: UUID | None = None
    child_processing_id: UUID | None = None
    extractor_name: str | None = None
    extractor_key: str | None = None
    completed_at: datetime | None = None
    resource_deleted: bool = False
    expires_at: datetime | None = None
    available_at: datetime = None
    created_at: datetime = None
    updated_at: datetime = None


@dataclass(kw_only=True)
class SubmissionReceipt:
    id: UUID = field(default_factory=uuid4)
    user_id: UUID
    operation: str
    key: UUID
    request_hash: str
    is_original: bool = True
    resource_kind: str
    resource_id: UUID
    config: dict = field(default_factory=dict)
    manifest: dict = field(default_factory=dict)
    processing_id: UUID | None = None
    lease_token: UUID = field(default_factory=uuid4)
    lease_expires_at: datetime = None
    created_at: datetime = None
    accepted_at: datetime | None = None
    expires_at: datetime | None = None


@dataclass(kw_only=True)
class OutboxDelivery:
    id: UUID = field(default_factory=uuid4)
    processing_id: UUID
    generation: int
    available_at: datetime = None
    published_at: datetime | None = None
    claim_token: UUID | None = None
    claimed_until: datetime | None = None
    attempts: int = 0
