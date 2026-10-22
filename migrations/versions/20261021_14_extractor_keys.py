"""Separate extractor implementations from per-axis branch identity."""

import sqlalchemy as sa
from alembic import op

revision = "20261021_14"
down_revision = "20261020_13"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("processing_records", sa.Column("extractor_key", sa.String(80)))
    op.execute(
        "UPDATE processing_records SET extractor_key=extractor_name WHERE workflow='extractor'"
    )
    op.drop_index("uq_processing_extractor_child", table_name="processing_records")
    op.create_index(
        "uq_processing_extractor_child",
        "processing_records",
        ["parent_processing_id", "extractor_key"],
        unique=True,
        postgresql_where=sa.text("workflow = 'extractor'"),
    )
    # Keep older writers/manual legacy jobs safe during an additive migration.
    op.execute("""CREATE FUNCTION default_extractor_key() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.workflow='extractor' AND NEW.extractor_key IS NULL THEN
            NEW.extractor_key := NEW.extractor_name;
          END IF;
          RETURN NEW;
        END $$""")
    op.execute("""CREATE TRIGGER processing_default_extractor_key
        BEFORE INSERT ON processing_records
        FOR EACH ROW EXECUTE FUNCTION default_extractor_key()""")
    op.create_check_constraint(
        "ck_processing_extractor_key",
        "processing_records",
        "workflow <> 'extractor' OR (extractor_key IS NOT NULL AND extractor_key <> '')",
    )


def downgrade():
    # Older workers cannot execute v5; the old index also cannot represent
    # multiple axes. Never silently discard their identities during downgrade.
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM processing_records
                 WHERE (workflow='document' AND workflow_version>=5)
                    OR (workflow='extractor' AND extractor_key<>extractor_name))
         OR EXISTS (SELECT 1 FROM processing_records WHERE workflow='extractor'
                 GROUP BY parent_processing_id, extractor_name HAVING count(*) > 1) THEN
        RAISE EXCEPTION 'extractor_key_downgrade_requires_v5_job_retirement';
      END IF;
    END $$""")
    op.execute("DROP TRIGGER processing_default_extractor_key ON processing_records")
    op.execute("DROP FUNCTION default_extractor_key()")
    op.drop_constraint("ck_processing_extractor_key", "processing_records", type_="check")
    op.drop_index("uq_processing_extractor_child", table_name="processing_records")
    op.create_index(
        "uq_processing_extractor_child",
        "processing_records",
        ["parent_processing_id", "extractor_name"],
        unique=True,
        postgresql_where=sa.text("workflow = 'extractor'"),
    )
    op.drop_column("processing_records", "extractor_key")
