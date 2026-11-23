"""Journal metadata, immutable snapshots and composite owner-scoped references."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.adapters.storage.postgres.base import Base


class JournalTemplateRecord(Base):
    __tablename__ = "journal_templates"
    __table_args__ = (CheckConstraint("version > 0", name="ck_journal_template_version"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    definition: Mapped[dict] = mapped_column(JSONB)


class JournalRunRecord(Base):
    __tablename__ = "journal_runs"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_journal_run_owner"),
        ForeignKeyConstraint(
            ["template_id", "template_version"],
            ["journal_templates.id", "journal_templates.version"],
            name="fk_journal_run_template",
        ),
        ForeignKeyConstraint(
            ["id", "owner_id", "revision"],
            [
                "journal_run_revisions.run_id",
                "journal_run_revisions.owner_id",
                "journal_run_revisions.revision",
            ],
            name="fk_journal_current_revision",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        CheckConstraint("revision > 0", name="ck_journal_run_revision"),
        CheckConstraint(
            "status IN ('active','paused','completed','closed')", name="ck_journal_run_status"
        ),
        Index(
            "uq_journal_active_owner",
            "owner_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "ix_journal_run_due", "ends_at", "owner_id", postgresql_where=text("status = 'active'")
        ),
        Index("ix_journal_run_owner", "owner_id", "updated_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    template_id: Mapped[UUID] = mapped_column()
    template_version: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JournalRevisionRecord(Base):
    __tablename__ = "journal_run_revisions"
    __table_args__ = (
        UniqueConstraint("run_id", "owner_id", "revision", name="uq_journal_revision_owner"),
        ForeignKeyConstraint(
            ["run_id", "owner_id"],
            ["journal_runs.id", "journal_runs.owner_id"],
            name="fk_journal_revision_run",
            ondelete="CASCADE",
        ),
        CheckConstraint("revision > 0", name="ck_journal_revision_positive"),
    )
    run_id: Mapped[UUID] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column()
    snapshot: Mapped[dict] = mapped_column(JSONB)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JournalStageRecord(Base):
    """Relational membership index; content is owned by the immutable snapshot."""

    __tablename__ = "journal_stage_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "owner_id", "revision"],
            [
                "journal_run_revisions.run_id",
                "journal_run_revisions.owner_id",
                "journal_run_revisions.revision",
            ],
            name="fk_journal_stage_revision",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "run_id", "owner_id", "revision", "stage_id", name="uq_journal_stage_owner"
        ),
        UniqueConstraint("run_id", "revision", "position", name="uq_journal_stage_position"),
        CheckConstraint("ends_at > starts_at", name="ck_journal_stage_interval"),
        CheckConstraint("position >= 0", name="ck_journal_stage_position"),
    )
    run_id: Mapped[UUID] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    stage_id: Mapped[UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[UUID] = mapped_column()
    position: Mapped[int] = mapped_column(Integer)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JournalReceiptRecord(Base):
    __tablename__ = "journal_mutation_receipts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "owner_id", "revision"],
            [
                "journal_run_revisions.run_id",
                "journal_run_revisions.owner_id",
                "journal_run_revisions.revision",
            ],
            name="fk_journal_receipt_revision",
            ondelete="CASCADE",
        ),
    )
    owner_id: Mapped[UUID] = mapped_column(primary_key=True)
    key: Mapped[UUID] = mapped_column(primary_key=True)
    operation: Mapped[str] = mapped_column(String(12))
    request_hash: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[UUID] = mapped_column()
    revision: Mapped[int] = mapped_column(Integer)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JournalInvitationRecord(Base):
    """Immutable publication context, populated by the journal question publisher."""

    __tablename__ = "journal_invitation_contexts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["invitation_id", "owner_id"],
            ["invitations.id", "invitations.user_id"],
            name="fk_journal_invitation_owner",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id", "owner_id", "revision", "stage_id"],
            [
                "journal_stage_revisions.run_id",
                "journal_stage_revisions.owner_id",
                "journal_stage_revisions.revision",
                "journal_stage_revisions.stage_id",
            ],
            name="fk_journal_invitation_stage",
            ondelete="CASCADE",
        ),
    )
    invitation_id: Mapped[UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[UUID] = mapped_column()
    run_id: Mapped[UUID] = mapped_column()
    revision: Mapped[int] = mapped_column(Integer)
    stage_id: Mapped[UUID] = mapped_column()


class JournalEntryRecord(Base):
    __tablename__ = "journal_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "owner_id", "revision", "stage_id"],
            [
                "journal_stage_revisions.run_id",
                "journal_stage_revisions.owner_id",
                "journal_stage_revisions.revision",
                "journal_stage_revisions.stage_id",
            ],
            name="fk_journal_entry_stage",
            ondelete="CASCADE",
        ),
        CheckConstraint("resource_kind IN ('document','audio')", name="ck_journal_entry_kind"),
        Index(
            "ix_journal_entry_context",
            "owner_id",
            "run_id",
            "resource_kind",
            "accepted_at",
            "resource_id",
        ),
    )
    owner_id: Mapped[UUID] = mapped_column(primary_key=True)
    resource_kind: Mapped[str] = mapped_column(String(12), primary_key=True)
    resource_id: Mapped[UUID] = mapped_column(primary_key=True)
    run_id: Mapped[UUID] = mapped_column()
    revision: Mapped[int] = mapped_column(Integer)
    stage_id: Mapped[UUID] = mapped_column()
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
