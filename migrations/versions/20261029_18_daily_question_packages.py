"""Daily question packages and idempotent optional activity.

Downgrade drops v2 packages, variant links, feedback and observations.
Existing invitation text and original documents/audio remain untouched.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261029_18"
down_revision = "20261021_17"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("invitations", sa.Column("question_policy", postgresql.JSONB(), nullable=True))
    op.add_column(
        "invitations",
        sa.Column("question_set", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_table(
        "invitation_topics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("catalog_key", sa.String(length=100), nullable=True),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("restricted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_feedback_sequence", sa.Integer(), nullable=False),
        sa.Column("reopened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reopened_by_document_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("scope IN ('catalog','personal')", name="ck_invitation_topic_scope"),
        sa.CheckConstraint(
            "status IN ('open','paused','closed','do_not_prompt')",
            name="ck_invitation_topic_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_invitation_topic_owner"),
        sa.UniqueConstraint("user_id", "catalog_key", name="uq_invitation_topic_catalog"),
    )
    op.create_table(
        "invitation_questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("topic_id", sa.Uuid(), nullable=True),
        sa.Column("depth", sa.String(length=12), nullable=True),
        sa.CheckConstraint(
            "depth IN ('gentle','middle','deep')", name="ck_invitation_question_depth"
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id", "user_id"],
            ["invitations.id", "invitations.user_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id", "user_id"],
            ["invitation_topics.id", "invitation_topics.user_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "invitation_id", "user_id", name="uq_invitation_question_owner"),
    )
    op.create_table(
        "invitation_activity_receipts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=20), nullable=False),
        sa.Column("request_key", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "operation", "request_key", name="uq_invitation_activity_key"
        ),
    )
    op.create_table(
        "invitation_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("value", sa.String(length=24), nullable=False),
        sa.Column("topic_sequence", sa.Integer(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "value IN ('helpful','unrelated','not_now','closed','do_not_prompt')",
            name="ck_invitation_feedback_value",
        ),
        sa.ForeignKeyConstraint(["id"], ["invitation_activity_receipts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["question_id", "invitation_id", "user_id"],
            [
                "invitation_questions.id",
                "invitation_questions.invitation_id",
                "invitation_questions.user_id",
            ],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "invitation_interactions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('shown','another_requested','passed')", name="ck_invitation_event"
        ),
        sa.ForeignKeyConstraint(
            ["question_id", "invitation_id", "user_id"],
            [
                "invitation_questions.id",
                "invitation_questions.invitation_id",
                "invitation_questions.user_id",
            ],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "id"),
    )
    op.create_table(
        "invitation_occurrences",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('published','no_eligible_questions')", name="ck_invitation_outcome"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "local_date"),
    )
    op.add_column(
        "invitation_responses", sa.Column("invitation_question_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "fk_invitation_response_question",
        "invitation_responses",
        "invitation_questions",
        ["invitation_question_id", "invitation_id", "user_id"],
        ["id", "invitation_id", "user_id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_invitation_question_topic",
        "invitation_questions",
        ["user_id", "topic_id"],
        unique=False,
    )
    op.create_index(
        "ix_invitation_shown",
        "invitation_interactions",
        ["user_id", "kind", "recorded_at"],
        unique=False,
    )


def downgrade():
    op.drop_column("invitations", "question_policy")
    op.drop_constraint(
        "fk_invitation_response_question", "invitation_responses", type_="foreignkey"
    )
    op.drop_column("invitation_responses", "invitation_question_id")
    op.drop_table("invitation_occurrences")
    op.drop_table("invitation_interactions")
    op.drop_table("invitation_feedback")
    op.drop_table("invitation_activity_receipts")
    op.drop_table("invitation_questions")
    op.drop_table("invitation_topics")
    op.drop_column("invitations", "question_set")
