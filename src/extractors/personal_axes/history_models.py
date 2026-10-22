"""Durable, owner-scoped historical analysis; definitions remain immutable."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.user_management.models import Base


class AxisHistoryBatch(Base):
    __tablename__ = "axis_history_batches"
    __table_args__ = (
        UniqueConstraint("user_id", "request_key", name="uq_axis_history_request"),
        Index("ix_axis_history_owner_axis", "user_id", "axis_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    axis_id: Mapped[UUID] = mapped_column(ForeignKey("personal_axes.id", ondelete="CASCADE"))
    version_id: Mapped[UUID] = mapped_column(ForeignKey("personal_axis_versions.id"))
    request_key: Mapped[UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AxisHistoryItem(Base):
    __tablename__ = "axis_history_items"
    batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("axis_history_batches.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[UUID] = mapped_column(primary_key=True)
    source_hash: Mapped[str] = mapped_column(String(64))
    processing_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("processing_records.id"), unique=True
    )
    outcome: Mapped[str | None] = mapped_column(String(24))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
