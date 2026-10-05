"""PostgreSQL records, event history and transactional dispatch outbox."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
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
