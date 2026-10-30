"""Index provider-call receipts for the shared UTC daily quota.

Revision ID: 20261029_22
Revises: 20261029_21
"""

from alembic import op

revision = "20261029_22"
down_revision = "20261029_21"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_question_provider_started", "question_provider_calls", ["started_at"])


def downgrade():
    op.drop_index("ix_question_provider_started", table_name="question_provider_calls")
