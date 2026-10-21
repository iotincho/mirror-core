"""Only approved definitions are permanent domain records."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.user_management.models import Base


class PersonalAxis(Base):
    __tablename__ = "personal_axes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["id", "current_version_id"],
            ["personal_axis_versions.axis_id", "personal_axis_versions.id"],
            name="fk_axis_current_version",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    current_version_id: Mapped[UUID] = mapped_column(nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PersonalAxisVersion(Base):
    __tablename__ = "personal_axis_versions"
    __table_args__ = (
        UniqueConstraint("axis_id", "number", name="uq_axis_version_number"),
        UniqueConstraint("axis_id", "id", name="uq_axis_version_identity"),
        CheckConstraint("number > 0", name="ck_axis_version_positive"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    axis_id: Mapped[UUID] = mapped_column(ForeignKey("personal_axes.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    purpose: Mapped[str] = mapped_column(Text)
    specification: Mapped[dict] = mapped_column(JSONB)
    specification_hash: Mapped[str] = mapped_column(String(64))
    accepted_preview_id: Mapped[UUID] = mapped_column(unique=True)
    revision_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
