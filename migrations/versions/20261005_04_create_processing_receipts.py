"""Add workflow links and idempotent submission receipts

Revision ID: 20261005_04
Revises: 20261005_03
Create Date: 2026-10-05 18:48:42.046501
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261005_04"
down_revision: str | Sequence[str] | None = "20261005_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "processing_receipts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("key", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("is_original", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("resource_kind", sa.String(length=50), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("processing_id", sa.Uuid(), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["processing_id"],
            ["processing_records.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_graphs.user_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "operation", "key", name="uq_processing_receipt_key"),
    )
    op.create_index(
        "ix_processing_receipts_pending",
        "processing_receipts",
        ["accepted_at", "lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "uq_processing_upload_resource",
        "processing_receipts",
        ["user_id", "resource_kind", "resource_id"],
        unique=True,
        postgresql_where=sa.text("operation IN ('upload_document','upload_audio') AND is_original"),
    )
    op.add_column(
        "processing_records",
        sa.Column("retryable", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("processing_records", sa.Column("document_id", sa.Uuid(), nullable=True))
    op.add_column("processing_records", sa.Column("extraction_run_id", sa.Uuid(), nullable=True))
    op.add_column("processing_records", sa.Column("parent_processing_id", sa.Uuid(), nullable=True))
    op.add_column("processing_records", sa.Column("child_processing_id", sa.Uuid(), nullable=True))
    op.add_column(
        "processing_records", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "processing_records",
        sa.Column("resource_deleted", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_foreign_key(
        "fk_processing_child",
        "processing_records",
        "processing_records",
        ["child_processing_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_processing_parent",
        "processing_records",
        "processing_records",
        ["parent_processing_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_processing_parent", "processing_records", type_="foreignkey")
    op.drop_constraint("fk_processing_child", "processing_records", type_="foreignkey")
    op.drop_column("processing_records", "resource_deleted")
    op.drop_column("processing_records", "completed_at")
    op.drop_column("processing_records", "child_processing_id")
    op.drop_column("processing_records", "parent_processing_id")
    op.drop_column("processing_records", "extraction_run_id")
    op.drop_column("processing_records", "document_id")
    op.drop_column("processing_records", "retryable")
    op.drop_index(
        "uq_processing_upload_resource",
        table_name="processing_receipts",
        postgresql_where=sa.text("operation IN ('upload_document','upload_audio') AND is_original"),
    )
    op.drop_index("ix_processing_receipts_pending", table_name="processing_receipts")
    op.drop_table("processing_receipts")
