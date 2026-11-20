"""Historical invitation context and durable membership for journal originals.

Revision ID: 20261103_24
Revises: 20261103_23
"""

import sqlalchemy as sa
from alembic import op

revision = "20261103_24"
down_revision = "20261103_23"
branch_labels = None
depends_on = None


def stage_foreign_key(name):
    return sa.ForeignKeyConstraint(
        ["run_id", "owner_id", "revision", "stage_id"],
        [
            "journal_stage_revisions.run_id",
            "journal_stage_revisions.owner_id",
            "journal_stage_revisions.revision",
            "journal_stage_revisions.stage_id",
        ],
        name=name,
        ondelete="CASCADE",
    )


def upgrade():
    op.create_table(
        "journal_invitation_contexts",
        sa.Column("invitation_id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("stage_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["invitation_id", "owner_id"],
            ["invitations.id", "invitations.user_id"],
            name="fk_journal_invitation_owner",
            ondelete="CASCADE",
        ),
        stage_foreign_key("fk_journal_invitation_stage"),
    )
    op.create_table(
        "journal_entries",
        sa.Column("owner_id", sa.Uuid(), primary_key=True),
        sa.Column("resource_kind", sa.String(12), primary_key=True),
        sa.Column("resource_id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("stage_id", sa.Uuid(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        stage_foreign_key("fk_journal_entry_stage"),
        sa.CheckConstraint("resource_kind IN ('document','audio')", name="ck_journal_entry_kind"),
    )
    op.create_index(
        "ix_journal_entry_context",
        "journal_entries",
        ["owner_id", "run_id", "resource_kind", "accepted_at", "resource_id"],
    )


def downgrade():
    # Loses journal membership/publication indices; originals and jobs remain intact.
    op.drop_table("journal_entries")
    op.drop_table("journal_invitation_contexts")
