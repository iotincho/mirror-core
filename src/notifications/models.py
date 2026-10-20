from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.user_management.models import Base


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "deduplication_key", name="uq_notification_source"),
        Index("ix_notification_inbox", "user_id", "published_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(String(1000))
    body: Mapped[str] = mapped_column(Text)
    action: Mapped[dict | None] = mapped_column(JSON)
    deduplication_key: Mapped[str] = mapped_column(String(200))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationEnrollment(Base):
    """A durable marker prevents onboarding from reappearing after expiry/dismissal."""

    __tablename__ = "notification_enrollments"
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    initialized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Announcement(Base):
    """Publication snapshot and locked cursor for restartable recipient fan-out."""

    __tablename__ = "notification_announcements"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    content: Mapped[dict] = mapped_column(JSON)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_user_id: Mapped[UUID | None] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
