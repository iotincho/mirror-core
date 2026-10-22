"""Remember Laboratory welcome per user without retaining creation history."""

import sqlalchemy as sa
from alembic import op

revision = "20261021_15"
down_revision = "20261021_14"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user",
        sa.Column("laboratory_welcome_dismissed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("user", "laboratory_welcome_dismissed_at")
