"""Opaque push destination binding independent of authentication credentials.

Revision ID: 20261013_09
Revises: 20261013_08
"""

import sqlalchemy as sa
from alembic import op

revision = "20261013_09"
down_revision = "20261013_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "push_subscriptions",
        sa.Column(
            "binding_id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
    )
    op.alter_column("push_subscriptions", "binding_id", server_default=None)


def downgrade() -> None:
    op.drop_column("push_subscriptions", "binding_id")
