"""Accept the intermediate level of invitation feedback.

Revision ID: 20261120_27
Revises: 20261114_26
"""

from alembic import op

revision = "20261120_27"
down_revision = "20261114_26"
branch_labels = None
depends_on = None

TABLE = "invitation_feedback"
CONSTRAINT = "ck_invitation_feedback_value"


def upgrade():
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(
        CONSTRAINT,
        TABLE,
        "value IN ('helpful','somewhat_helpful','unrelated','not_now','closed','do_not_prompt')",
    )


def downgrade():
    # PostgreSQL rejects and rolls back the downgrade if the new value is in use.
    op.drop_constraint(CONSTRAINT, TABLE, type_="check")
    op.create_check_constraint(
        CONSTRAINT, TABLE, "value IN ('helpful','unrelated','not_now','closed','do_not_prompt')"
    )
