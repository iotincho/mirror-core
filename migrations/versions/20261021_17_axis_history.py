"""Recoverable, version-pinned analysis of historical notes."""

import sqlalchemy as sa
from alembic import op

revision = "20261021_17"
down_revision = "20261021_16"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "axis_history_batches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "axis_id",
            sa.Uuid(),
            sa.ForeignKey("personal_axes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "version_id", sa.Uuid(), sa.ForeignKey("personal_axis_versions.id"), nullable=False
        ),
        sa.Column("request_key", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("stopped_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "request_key", name="uq_axis_history_request"),
    )
    op.create_index(
        "ix_axis_history_owner_axis", "axis_history_batches", ["user_id", "axis_id", "created_at"]
    )
    op.create_table(
        "axis_history_items",
        sa.Column(
            "batch_id",
            sa.Uuid(),
            sa.ForeignKey("axis_history_batches.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("document_id", sa.Uuid(), primary_key=True),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("processing_id", sa.Uuid(), sa.ForeignKey("processing_records.id"), unique=True),
        sa.Column("outcome", sa.String(24)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
    )


def downgrade():
    op.drop_table("axis_history_items")
    op.drop_table("axis_history_batches")
