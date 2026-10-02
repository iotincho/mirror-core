"""Create the user-to-ArcadeDB workspace registry.

Revision ID: 20260930_02
Revises: 20260930_01
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260930_02"
down_revision: str | Sequence[str] | None = "20260930_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_graphs",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("arcadedb_instance_key", sa.String(length=100), nullable=False),
        sa.Column("database_name", sa.String(length=100), nullable=False),
        sa.Column("graph_username", sa.String(length=100), nullable=False),
        sa.Column("graph_secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("schema_version", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("provisioned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("database_name"),
        sa.UniqueConstraint("graph_username"),
    )
    op.create_check_constraint(
        "ck_user_graphs_status",
        "user_graphs",
        "status IN ('pending', 'provisioning', 'active', 'failed', 'suspended')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_user_graphs_status", "user_graphs", type_="check")
    op.drop_table("user_graphs")
