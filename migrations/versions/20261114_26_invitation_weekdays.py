"""Schedule invitations on selected local weekdays.

Revision ID: 20261114_26
Revises: 20261103_25
"""

import sqlalchemy as sa
from alembic import op

revision = "20261114_26"
down_revision = "20261103_25"
branch_labels = None
depends_on = None


def upgrade():
    # All seven bits preserve the existing daily schedule for old preferences and clients.
    op.add_column(
        "invitation_preferences",
        sa.Column("weekdays_mask", sa.SmallInteger(), nullable=False, server_default="127"),
    )
    op.create_check_constraint(
        "ck_invitation_weekdays_mask", "invitation_preferences", "weekdays_mask BETWEEN 1 AND 127"
    )


def downgrade():
    # Downgrading loses the selected days; old code schedules every day.
    op.drop_constraint("ck_invitation_weekdays_mask", "invitation_preferences", type_="check")
    op.drop_column("invitation_preferences", "weekdays_mask")
