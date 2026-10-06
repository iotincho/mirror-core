"""Track resumable deployment migrations spanning graphs and files."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261006_06"
down_revision = "20261005_05"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "data_migrations",
        sa.Column("migration_id", sa.String(100), primary_key=True),
        sa.Column("instance_key", sa.String(100), primary_key=True),
        sa.Column("target", sa.String(100), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )


def downgrade():
    # Removing bookkeeping cannot restore deleted derived data.
    op.drop_table("data_migrations")
