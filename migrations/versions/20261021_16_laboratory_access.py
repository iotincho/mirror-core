"""Opt-in Laboratory access, independently controlled for each account."""

import sqlalchemy as sa
from alembic import op

revision = "20261021_16"
down_revision = "20261021_15"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user",
        sa.Column("laboratory_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("user", "laboratory_enabled")
