"""Persistent inbox, one-time onboarding and resumable announcement publications."""

import sqlalchemy as sa
from alembic import op

revision = "20261020_12"
down_revision = "20261016_11"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.String(1000), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("action", sa.JSON(), nullable=True),
        sa.Column("deduplication_key", sa.String(200), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.clock_timestamp(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "deduplication_key", name="uq_notification_source"),
    )
    op.create_index("ix_notification_inbox", "notifications", ["user_id", "published_at", "id"])
    op.create_table(
        "notification_enrollments",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("initialized_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "notification_announcements",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_user_id", sa.Uuid(), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Preserve only still-visible scheduled invitations; manual push tests stay out of the inbox.
    # Existing UUIDs can be reused here: table identities are independent.
    op.execute(
        sa.text("""
        INSERT INTO notifications
          (id, user_id, kind, title, summary, body, action, deduplication_key,
           published_at, expires_at, read_at)
        SELECT id, user_id, 'invitation', 'Tu pregunta del ' || local_date::text,
          question, question,
          json_build_object('type', 'open_invitation', 'invitation_id', id::text),
          'invitation:' || id::text, created_at, created_at + interval '15 days', first_opened_at
        FROM invitations
        WHERE kind = 'scheduled' AND created_at + interval '15 days' > clock_timestamp()
        ON CONFLICT (user_id, deduplication_key) DO NOTHING
    """)
    )


def downgrade():
    op.drop_table("notification_announcements")
    op.drop_table("notification_enrollments")
    op.drop_table("notifications")
