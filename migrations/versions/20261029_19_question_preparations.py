"""Durable daily question preparation and private personal topic descriptors.

Revision ID: 20261029_19
Revises: 20261029_18
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261029_19"
down_revision = "20261029_18"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "question_preparations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "processing_id", sa.Uuid(), sa.ForeignKey("processing_records.id"), nullable=False
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("preference_version", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("configuration", postgresql.JSONB(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB()),
        sa.Column("proposals", postgresql.JSONB()),
        sa.Column("selection", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "due_at", "preference_version", name="uq_question_preparation_occurrence"
        ),
        sa.CheckConstraint(
            "status IN ('pending','ready','obsolete','consumed')",
            name="ck_question_preparation_status",
        ),
    )
    op.create_index("ix_question_preparation_expiry", "question_preparations", ["expires_at"])
    op.create_table(
        "invitation_personal_topics",
        sa.Column(
            "topic_id",
            sa.Uuid(),
            sa.ForeignKey("invitation_topics.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
    )


def downgrade():
    # Private descriptors/preparation artifacts are lost; published questions and replies survive.
    op.drop_table("invitation_personal_topics")
    op.drop_index("ix_question_preparation_expiry", table_name="question_preparations")
    op.drop_table("question_preparations")
