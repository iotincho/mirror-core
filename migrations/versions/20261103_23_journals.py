"""Journal templates, journeys, immutable revisions and mutation receipts.

Revision ID: 20261103_23
Revises: 20261029_22
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261103_23"
down_revision = "20261029_22"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "journal_templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("definition", JSONB(), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_journal_template_version"),
    )
    op.create_table(
        "journal_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("id", "owner_id", name="uq_journal_run_owner"),
        sa.ForeignKeyConstraint(
            ["template_id", "template_version"],
            ["journal_templates.id", "journal_templates.version"],
            name="fk_journal_run_template",
        ),
        sa.CheckConstraint("revision > 0", name="ck_journal_run_revision"),
        sa.CheckConstraint(
            "status IN ('active','paused','completed','closed')", name="ck_journal_run_status"
        ),
    )
    op.create_index(
        "uq_journal_active_owner",
        "journal_runs",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_journal_run_due",
        "journal_runs",
        ["ends_at", "owner_id"],
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index("ix_journal_run_owner", "journal_runs", ["owner_id", "updated_at", "id"])
    op.create_table(
        "journal_run_revisions",
        sa.Column("run_id", sa.Uuid(), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot", JSONB(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "owner_id", "revision", name="uq_journal_revision_owner"),
        sa.ForeignKeyConstraint(
            ["run_id", "owner_id"],
            ["journal_runs.id", "journal_runs.owner_id"],
            name="fk_journal_revision_run",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("revision > 0", name="ck_journal_revision_positive"),
    )
    op.create_foreign_key(
        "fk_journal_current_revision",
        "journal_runs",
        "journal_run_revisions",
        ["id", "owner_id", "revision"],
        ["run_id", "owner_id", "revision"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_table(
        "journal_stage_revisions",
        sa.Column("run_id", sa.Uuid(), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("stage_id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id", "owner_id", "revision"],
            [
                "journal_run_revisions.run_id",
                "journal_run_revisions.owner_id",
                "journal_run_revisions.revision",
            ],
            name="fk_journal_stage_revision",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "run_id", "owner_id", "revision", "stage_id", name="uq_journal_stage_owner"
        ),
        sa.UniqueConstraint("run_id", "revision", "position", name="uq_journal_stage_position"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_journal_stage_interval"),
        sa.CheckConstraint("position >= 0", name="ck_journal_stage_position"),
    )
    op.create_table(
        "journal_mutation_receipts",
        sa.Column("owner_id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.Uuid(), primary_key=True),
        sa.Column("operation", sa.String(12), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
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


def downgrade():
    # Irreversible loss of journal configuration, intention history and receipts.
    # Existing notes, invitations, accounts and sessions are not removed.
    op.drop_table("journal_mutation_receipts")
    op.drop_table("journal_stage_revisions")
    op.drop_constraint("fk_journal_current_revision", "journal_runs", type_="foreignkey")
    op.drop_table("journal_run_revisions")
    op.drop_table("journal_runs")
    op.drop_table("journal_templates")
