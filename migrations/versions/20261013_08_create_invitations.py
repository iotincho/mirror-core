"""Voluntary writing invitations and per-device push deliveries

Revision ID: 20261013_08
Revises: 20261007_07
Create Date: 2026-10-13 16:51:41.836436
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261013_08"
down_revision: str | Sequence[str] | None = "20261007_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invitation_preferences",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("local_time", sa.String(length=5), nullable=False),
        sa.Column("timezone", sa.String(length=100), nullable=False),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index(
        "ix_invitation_due", "invitation_preferences", ["enabled", "next_due_at"], unique=False
    )
    op.create_table(
        "invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=100), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurrence_key", sa.String(length=150), nullable=False),
        sa.Column("request_key", sa.Uuid(), nullable=True),
        sa.Column("test_subscription_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("candidate_id", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("engine_version", sa.String(length=50), nullable=False),
        sa.Column("catalog_version", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('scheduled','test')", name="ck_invitation_kind"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "user_id", name="uq_invitation_owner"),
        sa.UniqueConstraint("occurrence_key"),
        sa.UniqueConstraint("user_id", "request_key", name="uq_invitation_test_key"),
    )
    op.create_index(
        "ix_invitation_history", "invitations", ["user_id", "kind", "created_at"], unique=False
    )
    op.create_index(
        "uq_invitation_occurrence",
        "invitations",
        ["user_id", "local_date"],
        unique=True,
        postgresql_where=sa.text("kind = 'scheduled'"),
    )
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.Text(), nullable=False),
        sa.Column("auth", sa.Text(), nullable=False),
        sa.Column("session_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("endpoint"),
        sa.UniqueConstraint("id", "user_id", name="uq_push_subscription_owner"),
    )
    op.create_index(
        "ix_push_subscription_owner", "push_subscriptions", ["user_id", "active"], unique=False
    )
    op.create_table(
        "invitation_responses",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["invitation_id", "user_id"],
            ["invitations.id", "invitations.user_id"],
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "document_id"),
    )
    op.create_table(
        "invitation_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), nullable=False),
        sa.Column("processing_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','accepted','retrying','expired','cancelled','failed')",
            name="ck_invitation_delivery_status",
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id", "user_id"],
            ["invitations.id", "invitations.user_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["processing_id"],
            ["processing_records.id"],
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id", "user_id"],
            ["push_subscriptions.id", "push_subscriptions.user_id"],
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invitation_id", "subscription_id", name="uq_invitation_device"),
        sa.UniqueConstraint("processing_id"),
    )


def downgrade() -> None:
    op.drop_table("invitation_deliveries")
    op.drop_table("invitation_responses")
    op.drop_index("ix_push_subscription_owner", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
    op.drop_index(
        "uq_invitation_occurrence",
        table_name="invitations",
        postgresql_where=sa.text("kind = 'scheduled'"),
    )
    op.drop_index("ix_invitation_history", table_name="invitations")
    op.drop_table("invitations")
    op.drop_index("ix_invitation_due", table_name="invitation_preferences")
    op.drop_table("invitation_preferences")
