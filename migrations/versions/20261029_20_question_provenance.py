"""Keep accepted group provenance after temporary preparations expire.

Revision ID: 20261029_20
Revises: 20261029_19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261029_20"
down_revision = "20261029_19"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("question_preparations", sa.Column("decision", sa.String(50)))
    op.create_table(
        "invitation_group_provenance",
        sa.Column("group_id", sa.Uuid(), primary_key=True),
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("specification", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["invitation_id", "user_id"],
            ["invitations.id", "invitations.user_id"],
            ondelete="CASCADE",
        ),
    )


def downgrade():
    op.drop_table("invitation_group_provenance")
    op.drop_column("question_preparations", "decision")
