"""Content-free preparation outcomes and provider-call receipts."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.storage.postgres.accounts import Base


class QuestionPreparationMetric(Base):
    __tablename__ = "question_preparation_metrics"
    __table_args__ = (Index("ix_question_metric_created", "created_at"),)
    processing_id: Mapped[UUID] = mapped_column(
        ForeignKey("processing_records.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    model: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision: Mapped[str | None] = mapped_column(String(50))


class QuestionProviderCall(Base):
    __tablename__ = "question_provider_calls"
    __table_args__ = (Index("ix_question_provider_started", "started_at"),)
    processing_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_preparation_metrics.processing_id", ondelete="CASCADE"),
        primary_key=True,
    )
    fencing_token: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    elapsed_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    reserved_input_tokens: Mapped[int] = mapped_column(Integer)
    reserved_output_tokens: Mapped[int] = mapped_column(Integer)
