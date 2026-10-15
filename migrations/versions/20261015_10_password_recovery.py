"""Local credential provenance, recovery budgets, protected codes and session fencing."""

import sqlalchemy as sa
from alembic import op

revision = "20261015_10"
down_revision = "20261013_09"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user",
        sa.Column(
            "password_login_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "user", sa.Column("session_version", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "accesstoken",
        sa.Column("session_version", sa.Integer(), nullable=False, server_default="0"),
    )
    # The owner confirmed that all pre-migration Google accounts signed up with
    # Google. Future local signups retain True when they explicitly link Google.
    op.execute(
        'UPDATE "user" SET password_login_enabled = CASE WHEN EXISTS '
        '(SELECT 1 FROM oauth_account WHERE oauth_account.user_id = "user".id) '
        "THEN FALSE ELSE TRUE END"
    )
    # Auth mail must work for an account whose workspace allocation failed.
    # All document workflows still require an active workspace in the executor.
    op.drop_constraint("processing_records_user_id_fkey", "processing_records", type_="foreignkey")
    op.create_foreign_key(
        "processing_records_user_id_fkey", "processing_records", "user", ["user_id"], ["id"]
    )
    op.create_table(
        "password_recovery_addresses",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("sent_times", sa.JSON(), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("user.id", ondelete="CASCADE")),
        sa.Column("challenge_id", sa.Uuid()),
        sa.Column("code_mac", sa.String(64)),
        sa.Column("code_ciphertext", sa.Text()),
        sa.Column("password_mac", sa.String(64)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_recovery_address_cleanup", "password_recovery_addresses", ["updated_at"])
    op.create_table(
        "password_recovery_ips",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("request_times", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "password_recovery_deliveries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "address_key",
            sa.String(64),
            sa.ForeignKey("password_recovery_addresses.key", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("challenge_id", sa.Uuid(), nullable=False),
        sa.Column(
            "processing_id", sa.Uuid(), sa.ForeignKey("processing_records.id"), nullable=False
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.String(100)),
        sa.Column("error_code", sa.String(100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    # A rollback must never delete auth work or user data to restore the old FK.
    # Reject downgrade until any records without a workspace are reconciled.
    op.drop_table("password_recovery_deliveries")
    op.drop_table("password_recovery_ips")
    op.drop_table("password_recovery_addresses")
    op.drop_constraint("processing_records_user_id_fkey", "processing_records", type_="foreignkey")
    op.create_foreign_key(
        "processing_records_user_id_fkey",
        "processing_records",
        "user_graphs",
        ["user_id"],
        ["user_id"],
    )
    op.drop_column("accesstoken", "session_version")
    op.drop_column("user", "session_version")
    op.drop_column("user", "password_login_enabled")
