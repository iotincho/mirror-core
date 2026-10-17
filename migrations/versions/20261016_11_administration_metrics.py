"""Administrative metadata projection and explicit activity measurement."""

import sqlalchemy as sa
from alembic import op

revision = "20261016_11"
down_revision = "20261015_10"
branch_labels = None
depends_on = None


def upgrade():
    # Keep historical account dates unknown, then default only future inserts.
    op.add_column("user", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("user", "created_at", server_default=sa.func.now())
    op.create_table(
        "admin_document_metrics",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("document_id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kind", sa.String(16), nullable=True),
        sa.Column("deleted", sa.Boolean(), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_admin_documents_arrival", "admin_document_metrics", ["arrived_at", "kind"])
    op.create_table(
        "admin_inventory_state",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "platform_user_activity",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_platform_activity_day", "platform_user_activity", ["day"])
    op.create_table(
        "platform_metric_coverage",
        sa.Column("name", sa.String(50), primary_key=True),
        sa.Column(
            "since", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade():
    op.drop_table("platform_metric_coverage")
    op.drop_table("platform_user_activity")
    op.drop_table("admin_inventory_state")
    op.drop_table("admin_document_metrics")
    op.drop_column("user", "created_at")
