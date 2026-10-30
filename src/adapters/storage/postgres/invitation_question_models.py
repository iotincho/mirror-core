"""Immutable question indexes, activity receipts and owner-scoped topic boundaries."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.storage.postgres.accounts import Base


class InvitationTopic(Base):
    __tablename__ = "invitation_topics"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_invitation_topic_owner"),
        UniqueConstraint("user_id", "catalog_key", name="uq_invitation_topic_catalog"),
        CheckConstraint("scope IN ('catalog','personal')", name="ck_invitation_topic_scope"),
        CheckConstraint(
            "status IN ('open','paused','closed','do_not_prompt')",
            name="ck_invitation_topic_status",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    catalog_key: Mapped[str | None] = mapped_column(String(100))
    scope: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="open")
    restricted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_feedback_sequence: Mapped[int] = mapped_column(Integer, default=0)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reopened_by_document_id: Mapped[UUID | None] = mapped_column()


class InvitationQuestionRecord(Base):
    __tablename__ = "invitation_questions"
    __table_args__ = (
        UniqueConstraint("id", "invitation_id", "user_id", name="uq_invitation_question_owner"),
        ForeignKeyConstraint(
            ["invitation_id", "user_id"],
            ["invitations.id", "invitations.user_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["topic_id", "user_id"],
            ["invitation_topics.id", "invitation_topics.user_id"],
        ),
        CheckConstraint("depth IN ('gentle','middle','deep')", name="ck_invitation_question_depth"),
        Index("ix_invitation_question_topic", "user_id", "topic_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    invitation_id: Mapped[UUID] = mapped_column()
    user_id: Mapped[UUID] = mapped_column()
    group_id: Mapped[UUID] = mapped_column()
    topic_id: Mapped[UUID | None] = mapped_column()
    depth: Mapped[str | None] = mapped_column(String(12))


class InvitationActivityReceipt(Base):
    __tablename__ = "invitation_activity_receipts"
    __table_args__ = (
        UniqueConstraint("user_id", "operation", "request_key", name="uq_invitation_activity_key"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    operation: Mapped[str] = mapped_column(String(20))
    request_key: Mapped[UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSONB)


class InvitationFeedback(Base):
    __tablename__ = "invitation_feedback"
    __table_args__ = (
        ForeignKeyConstraint(
            ["question_id", "invitation_id", "user_id"],
            [
                "invitation_questions.id",
                "invitation_questions.invitation_id",
                "invitation_questions.user_id",
            ],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "value IN ('helpful','unrelated','not_now','closed','do_not_prompt')",
            name="ck_invitation_feedback_value",
        ),
    )
    id: Mapped[UUID] = mapped_column(
        ForeignKey("invitation_activity_receipts.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column()
    invitation_id: Mapped[UUID] = mapped_column()
    question_id: Mapped[UUID] = mapped_column()
    value: Mapped[str] = mapped_column(String(24))
    topic_sequence: Mapped[int | None] = mapped_column(Integer)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InvitationInteractionRecord(Base):
    __tablename__ = "invitation_interactions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["question_id", "invitation_id", "user_id"],
            [
                "invitation_questions.id",
                "invitation_questions.invitation_id",
                "invitation_questions.user_id",
            ],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "kind IN ('shown','another_requested','passed')", name="ck_invitation_event"
        ),
        Index("ix_invitation_shown", "user_id", "kind", "recorded_at"),
    )
    user_id: Mapped[UUID] = mapped_column(primary_key=True)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    invitation_id: Mapped[UUID] = mapped_column()
    question_id: Mapped[UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(24))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InvitationOccurrence(Base):
    __tablename__ = "invitation_occurrences"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('published','no_eligible_questions')", name="ck_invitation_outcome"
        ),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    local_date: Mapped[date] = mapped_column(Date, primary_key=True)
    outcome: Mapped[str] = mapped_column(String(32))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
