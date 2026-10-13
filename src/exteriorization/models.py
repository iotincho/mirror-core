"""Operational records; no original note text or extraction data is stored here."""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.user_management.models import Base


class InvitationPreference(Base):
    __tablename__ = "invitation_preferences"
    __table_args__ = (Index("ix_invitation_due", "enabled", "next_due_at"),)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    local_time: Mapped[str] = mapped_column(String(5), default="20:30")
    timezone: Mapped[str] = mapped_column(String(100), default="UTC")
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_push_subscription_owner"),
        Index("ix_push_subscription_owner", "user_id", "active"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(Text)
    session_fingerprint: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())


class Invitation(Base):
    __tablename__ = "invitations"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_invitation_owner"),
        UniqueConstraint("user_id", "request_key", name="uq_invitation_test_key"),
        CheckConstraint("kind IN ('scheduled','test')", name="ck_invitation_kind"),
        Index(
            "uq_invitation_occurrence",
            "user_id",
            "local_date",
            unique=True,
            postgresql_where=text("kind = 'scheduled'"),
        ),
        Index("ix_invitation_history", "user_id", "kind", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    local_date: Mapped[date] = mapped_column(Date)
    timezone: Mapped[str] = mapped_column(String(100))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    occurrence_key: Mapped[str] = mapped_column(String(150), unique=True)
    request_key: Mapped[UUID | None] = mapped_column()
    test_subscription_id: Mapped[UUID | None] = mapped_column()
    source: Mapped[str] = mapped_column(String(30), default="generic")
    candidate_id: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(100))
    question: Mapped[str] = mapped_column(Text)
    engine_version: Mapped[str] = mapped_column(String(50))
    catalog_version: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    first_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InvitationDelivery(Base):
    __tablename__ = "invitation_deliveries"
    __table_args__ = (
        UniqueConstraint("invitation_id", "subscription_id", name="uq_invitation_device"),
        ForeignKeyConstraint(
            ["invitation_id", "user_id"],
            ["invitations.id", "invitations.user_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["subscription_id", "user_id"], ["push_subscriptions.id", "push_subscriptions.user_id"]
        ),
        CheckConstraint(
            "status IN ('pending','accepted','retrying','expired','cancelled','failed')",
            name="ck_invitation_delivery_status",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    invitation_id: Mapped[UUID] = mapped_column()
    subscription_id: Mapped[UUID] = mapped_column()
    processing_id: Mapped[UUID] = mapped_column(ForeignKey("processing_records.id"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InvitationResponse(Base):
    __tablename__ = "invitation_responses"
    __table_args__ = (
        ForeignKeyConstraint(
            ["invitation_id", "user_id"], ["invitations.id", "invitations.user_id"]
        ),
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[UUID] = mapped_column(primary_key=True)
    invitation_id: Mapped[UUID] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
