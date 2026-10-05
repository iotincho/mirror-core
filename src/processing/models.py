"""PostgreSQL records, event history and transactional dispatch outbox."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.user_management.models import Base


class ProcessingRecord(Base):
    __tablename__ = "processing_records"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','waiting','retrying','failed','completed')",
            name="ck_processing_status",
        ),
        Index("ix_processing_recovery", "status", "available_at", "lease_expires_at"),
        Index("ix_processing_owner", "user_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user_graphs.user_id"), nullable=False)
    workflow: Mapped[str] = mapped_column(String(100))
    workflow_version: Mapped[int] = mapped_column(Integer, default=1)
    resource_kind: Mapped[str] = mapped_column(String(50))
    resource_id: Mapped[UUID] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), default="queued")
    stage: Mapped[str] = mapped_column(String(100))
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    checkpoints: Mapped[dict] = mapped_column(JSONB, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    generation: Mapped[int] = mapped_column(Integer, default=1)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    stage_attempts: Mapped[int] = mapped_column(Integer, default=0)
    fencing_token: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    document_id: Mapped[UUID | None] = mapped_column()
    extraction_run_id: Mapped[UUID | None] = mapped_column()
    parent_processing_id: Mapped[UUID | None] = mapped_column(ForeignKey("processing_records.id"))
    child_processing_id: Mapped[UUID | None] = mapped_column(ForeignKey("processing_records.id"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resource_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())


class ProcessingEvent(Base):
    __tablename__ = "processing_events"
    __table_args__ = (Index("ix_processing_events_owner", "user_id", "id"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    processing_id: Mapped[UUID] = mapped_column(ForeignKey("processing_records.id"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user_graphs.user_id"))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    stage: Mapped[str] = mapped_column(String(100))
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())


class ProcessingOutbox(Base):
    __tablename__ = "processing_outbox"
    __table_args__ = (Index("ix_processing_outbox_pending", "published_at", "available_at"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    processing_id: Mapped[UUID] = mapped_column(ForeignKey("processing_records.id"))
    generation: Mapped[int] = mapped_column(Integer)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_token: Mapped[UUID | None] = mapped_column()
    claimed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class ProcessingReceipt(Base):
    """Reserved request identity; only accepted receipts reference executable work."""

    __tablename__ = "processing_receipts"
    __table_args__ = (
        UniqueConstraint("user_id", "operation", "key", name="uq_processing_receipt_key"),
        Index("ix_processing_receipts_pending", "accepted_at", "lease_expires_at"),
        Index(
            "uq_processing_upload_resource",
            "user_id",
            "resource_kind",
            "resource_id",
            unique=True,
            postgresql_where=text(
                "operation IN ('upload_document','upload_audio') AND is_original"
            ),
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user_graphs.user_id"))
    operation: Mapped[str] = mapped_column(String(100))
    key: Mapped[UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    is_original: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    resource_kind: Mapped[str] = mapped_column(String(50))
    resource_id: Mapped[UUID] = mapped_column()
    config: Mapped[dict] = mapped_column(JSONB)
    manifest: Mapped[dict] = mapped_column(JSONB, default=dict)
    processing_id: Mapped[UUID | None] = mapped_column(ForeignKey("processing_records.id"))
    lease_token: Mapped[UUID] = mapped_column(default=uuid4)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
