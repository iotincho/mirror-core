"""Metadata only: no titles, text, audio, tokens or arbitrary JSON payloads."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.user_management.models import Base


class DocumentMetric(Base):
    __tablename__ = "admin_document_metrics"
    __table_args__ = (Index("ix_admin_documents_arrival", "arrived_at", "kind"),)

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str | None] = mapped_column(String(16))
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InventoryState(Base):
    __tablename__ = "admin_inventory_state"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    complete: Mapped[bool] = mapped_column(Boolean, default=False)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserActivity(Base):
    __tablename__ = "platform_user_activity"
    __table_args__ = (Index("ix_platform_activity_day", "day"),)

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MetricCoverage(Base):
    __tablename__ = "platform_metric_coverage"

    name: Mapped[str] = mapped_column(String(50), primary_key=True)
    since: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
