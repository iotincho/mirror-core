"""Occurrence-scoped preparation state; no copies of original note content."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.storage.postgres.accounts import Base


class QuestionPreparation(Base):
    __tablename__ = "question_preparations"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "due_at", "preference_version", name="uq_question_preparation_occurrence"
        ),
        CheckConstraint(
            "status IN ('pending','ready','obsolete','consumed')",
            name="ck_question_preparation_status",
        ),
        Index("ix_question_preparation_expiry", "expires_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    processing_id: Mapped[UUID] = mapped_column(ForeignKey("processing_records.id"))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    preference_version: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(12), default="pending")
    configuration: Mapped[dict] = mapped_column(JSONB)
    snapshot: Mapped[dict | None] = mapped_column(JSONB)
    proposals: Mapped[dict | None] = mapped_column(JSONB)
    selection: Mapped[dict | None] = mapped_column(JSONB)
    decision: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PersonalTopicDescription(Base):
    __tablename__ = "invitation_personal_topics"
    topic_id: Mapped[UUID] = mapped_column(
        ForeignKey("invitation_topics.id", ondelete="CASCADE"), primary_key=True
    )
    label: Mapped[str] = mapped_column(String(120))
    evidence: Mapped[list] = mapped_column(JSONB)


class QuestionGroupProvenance(Base):
    __tablename__ = "invitation_group_provenance"
    __table_args__ = (
        ForeignKeyConstraint(
            ["invitation_id", "user_id"],
            ["invitations.id", "invitations.user_id"],
            ondelete="CASCADE",
        ),
    )
    group_id: Mapped[UUID] = mapped_column(primary_key=True)
    invitation_id: Mapped[UUID] = mapped_column()
    user_id: Mapped[UUID] = mapped_column()
    specification: Mapped[dict] = mapped_column(JSONB)
