"""Content-free daily-question preparation and provider metrics.

Revision ID: 20261029_21
Revises: 20261029_20
"""

import sqlalchemy as sa
from alembic import op

revision = "20261029_21"
down_revision = "20261029_20"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "question_preparation_metrics",
        sa.Column(
            "processing_id",
            sa.Uuid(),
            sa.ForeignKey("processing_records.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ready_at", sa.DateTime(timezone=True)),
        sa.Column("decision", sa.String(50)),
    )
    op.create_index("ix_question_metric_created", "question_preparation_metrics", ["created_at"])
    op.create_table(
        "question_provider_calls",
        sa.Column(
            "processing_id",
            sa.Uuid(),
            sa.ForeignKey("question_preparation_metrics.processing_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("fencing_token", sa.Integer(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("elapsed_ms", sa.Integer()),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("reserved_input_tokens", sa.Integer(), nullable=False),
        sa.Column("reserved_output_tokens", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("question_provider_calls")
    op.drop_index("ix_question_metric_created", table_name="question_preparation_metrics")
    op.drop_table("question_preparation_metrics")
