"""Durable event payloads and commit-ordered SSE delivery cursors."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261005_05"
down_revision = "20261005_04"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("processing_events", sa.Column("payload", postgresql.JSONB(), nullable=True))
    op.create_table(
        "processing_deliveries",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("processing_events.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
    )


def downgrade():
    op.drop_table("processing_deliveries")
    op.drop_column("processing_events", "payload")
