"""PostgreSQL records for AI usage and collection intervals."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.storage.postgres.base import Base


class AiUsageCoverage(Base):
    __tablename__ = "ai_usage_coverage"
    __table_args__ = (
        Index(
            "uq_ai_usage_open_coverage",
            text("(1)"),
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
        CheckConstraint("ended_at >= started_at", name="ck_ai_usage_coverage_times"),
    )

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AiUsageReceipt(Base):
    __tablename__ = "ai_usage_receipts"
    __table_args__ = (
        Index("ix_ai_usage_receipts_started_at", "started_at"),
        Index("ix_ai_usage_receipts_user_started_at", "user_id", "started_at"),
        CheckConstraint(
            "(finished_at IS NULL AND outcome IS NULL) OR "
            "(finished_at IS NOT NULL AND finished_at >= started_at AND outcome IS NOT NULL "
            "AND outcome IN ('succeeded', 'failed', 'unknown'))",
            name="ck_ai_usage_receipt_outcome",
        ),
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND total_tokens >= 0 "
            "AND cached_input_tokens >= 0 AND audio_input_tokens >= 0 AND duration_seconds >= 0",
            name="ck_ai_usage_receipt_amounts",
        ),
    )

    attempt_id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    execution_id: Mapped[UUID | None]
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    feature: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(64))
    requested_model: Mapped[str] = mapped_column(String(200))
    effective_model: Mapped[str | None] = mapped_column(String(200))
    provider_request_id: Mapped[str | None] = mapped_column(String(200))
    outcome: Mapped[str | None] = mapped_column(String(16))
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    total_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cached_input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    audio_input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
