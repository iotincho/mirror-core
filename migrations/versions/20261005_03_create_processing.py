"""Create durable processing state events and outbox

Revision ID: 20261005_03
Revises: 20260930_02
Create Date: 2026-10-05 17:22:25.088378
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261005_03"
down_revision: str | Sequence[str] | None = "20260930_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "processing_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workflow", sa.String(length=100), nullable=False),
        sa.Column("workflow_version", sa.Integer(), nullable=False),
        sa.Column("resource_kind", sa.String(length=50), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("stage", sa.String(length=100), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("checkpoints", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("stage_attempts", sa.Integer(), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(length=100), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued','running','waiting','retrying','failed','completed')",
            name="ck_processing_status",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_graphs.user_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_processing_owner", "processing_records", ["user_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_processing_recovery",
        "processing_records",
        ["status", "available_at", "lease_expires_at"],
        unique=False,
    )
    op.create_table(
        "processing_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("processing_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("stage", sa.String(length=100), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["processing_id"],
            ["processing_records.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_graphs.user_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_processing_events_owner", "processing_events", ["user_id", "id"], unique=False
    )
    op.create_table(
        "processing_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("processing_id", sa.Uuid(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("claimed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["processing_id"],
            ["processing_records.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_processing_outbox_pending",
        "processing_outbox",
        ["published_at", "available_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_processing_outbox_pending", table_name="processing_outbox")
    op.drop_table("processing_outbox")
    op.drop_index("ix_processing_events_owner", table_name="processing_events")
    op.drop_table("processing_events")
    op.drop_index("ix_processing_recovery", table_name="processing_records")
    op.drop_index("ix_processing_owner", table_name="processing_records")
    op.drop_table("processing_records")
