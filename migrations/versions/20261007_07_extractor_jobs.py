"""Independent extractor jobs under a document coordinator."""

import sqlalchemy as sa
from alembic import op

revision = "20261007_07"
down_revision = "20261006_06"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("processing_records", sa.Column("extractor_name", sa.String(80)))
    op.create_index("ix_processing_parent", "processing_records", ["parent_processing_id"])
    op.create_index(
        "uq_processing_extractor_child",
        "processing_records",
        ["parent_processing_id", "extractor_name"],
        unique=True,
        postgresql_where=sa.text("workflow = 'extractor'"),
    )
    op.create_check_constraint(
        "ck_processing_extractor_identity",
        "processing_records",
        "workflow <> 'extractor' OR (parent_processing_id IS NOT NULL AND "
        "extractor_name IS NOT NULL AND extraction_run_id IS NOT NULL "
        "AND resource_kind = 'document')",
    )


def downgrade():
    op.drop_constraint("ck_processing_extractor_identity", "processing_records", type_="check")
    op.drop_index("uq_processing_extractor_child", table_name="processing_records")
    op.drop_index("ix_processing_parent", table_name="processing_records")
    op.drop_column("processing_records", "extractor_name")
