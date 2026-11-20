"""Allow a new preparation after the journal context of an occurrence changes.

Revision ID: 20261103_25
Revises: 20261103_24
"""

import sqlalchemy as sa
from alembic import op

revision = "20261103_25"
down_revision = "20261103_24"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "question_preparations",
        sa.Column("context_key", sa.String(200), nullable=False, server_default="free"),
    )
    op.drop_constraint(
        "uq_question_preparation_occurrence", "question_preparations", type_="unique"
    )
    op.create_unique_constraint(
        "uq_question_preparation_context",
        "question_preparations",
        ["user_id", "due_at", "preference_version", "context_key"],
    )


def downgrade():
    # Old code cannot distinguish multiple contexts of one occurrence. Keep free
    # preparations only; their internal jobs expire through the existing runtime.
    op.execute("DELETE FROM question_preparations WHERE context_key <> 'free'")
    op.drop_constraint("uq_question_preparation_context", "question_preparations", type_="unique")
    op.drop_column("question_preparations", "context_key")
    op.create_unique_constraint(
        "uq_question_preparation_occurrence",
        "question_preparations",
        ["user_id", "due_at", "preference_version"],
    )
