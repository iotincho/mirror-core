"""Approved axis versions and expiry of temporary preview operations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261020_13"
down_revision = "20261020_12"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("processing_records", sa.Column("expires_at", sa.DateTime(timezone=True)))
    op.add_column("processing_receipts", sa.Column("expires_at", sa.DateTime(timezone=True)))
    op.create_table(
        "personal_axes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("current_version_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_personal_axes_user_id", "personal_axes", ["user_id"])
    op.create_table(
        "personal_axis_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "axis_id",
            sa.Uuid(),
            sa.ForeignKey("personal_axes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("specification", postgresql.JSONB(), nullable=False),
        sa.Column("specification_hash", sa.String(64), nullable=False),
        sa.Column("accepted_preview_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("revision_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("axis_id", "number", name="uq_axis_version_number"),
        sa.UniqueConstraint("axis_id", "id", name="uq_axis_version_identity"),
        sa.CheckConstraint("number > 0", name="ck_axis_version_positive"),
    )
    op.create_foreign_key(
        "fk_axis_current_version",
        "personal_axes",
        "personal_axis_versions",
        ["id", "current_version_id"],
        ["axis_id", "id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.execute("""CREATE FUNCTION reject_axis_version_update() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        RAISE EXCEPTION 'axis_version_immutable'; END $$""")
    op.execute("""CREATE TRIGGER axis_version_immutable BEFORE UPDATE ON personal_axis_versions
        FOR EACH ROW EXECUTE FUNCTION reject_axis_version_update()""")


def downgrade():
    op.execute("DROP TRIGGER axis_version_immutable ON personal_axis_versions")
    op.execute("DROP FUNCTION reject_axis_version_update()")
    op.drop_constraint("fk_axis_current_version", "personal_axes", type_="foreignkey")
    op.drop_table("personal_axis_versions")
    op.drop_table("personal_axes")
    op.drop_column("processing_receipts", "expires_at")
    op.drop_column("processing_records", "expires_at")
