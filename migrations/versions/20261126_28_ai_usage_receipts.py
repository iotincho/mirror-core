"""Add the AI usage ledger and its collection intervals.

Revision ID: 20261126_28
Revises: 20261120_27
"""

import sqlalchemy as sa
from alembic import op

revision = "20261126_28"
down_revision = "20261120_27"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ai_usage_coverage",
        sa.Column("started_at", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("ended_at >= started_at", name="ck_ai_usage_coverage_times"),
    )
    op.create_index(
        "uq_ai_usage_open_coverage",
        "ai_usage_coverage",
        [sa.text("(1)")],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.create_table(
        "ai_usage_receipts",
        sa.Column("attempt_id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("execution_id", sa.Uuid()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("feature", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("requested_model", sa.String(200), nullable=False),
        sa.Column("effective_model", sa.String(200)),
        sa.Column("provider_request_id", sa.String(200)),
        sa.Column("outcome", sa.String(16)),
        sa.Column("input_tokens", sa.BigInteger()),
        sa.Column("output_tokens", sa.BigInteger()),
        sa.Column("total_tokens", sa.BigInteger()),
        sa.Column("cached_input_tokens", sa.BigInteger()),
        sa.Column("audio_input_tokens", sa.BigInteger()),
        sa.Column("duration_seconds", sa.Numeric(20, 6)),
        sa.CheckConstraint(
            "(finished_at IS NULL AND outcome IS NULL) OR "
            "(finished_at IS NOT NULL AND finished_at >= started_at AND outcome IS NOT NULL "
            "AND outcome IN ('succeeded', 'failed', 'unknown'))",
            name="ck_ai_usage_receipt_outcome",
        ),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND total_tokens >= 0 "
            "AND cached_input_tokens >= 0 AND audio_input_tokens >= 0 AND duration_seconds >= 0",
            name="ck_ai_usage_receipt_amounts",
        ),
    )
    op.create_index("ix_ai_usage_receipts_started_at", "ai_usage_receipts", ["started_at"])
    op.create_index(
        "ix_ai_usage_receipts_user_started_at", "ai_usage_receipts", ["user_id", "started_at"]
    )


def downgrade():
    op.drop_table("ai_usage_receipts")
    op.drop_table("ai_usage_coverage")
