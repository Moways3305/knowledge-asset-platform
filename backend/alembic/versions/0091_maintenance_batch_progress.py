"""Persist resumable inspection cursors; existing reports remain readable."""

import sqlalchemy as sa
from alembic import op

revision = "0091_maintenance_batch_progress"
down_revision = "0090_maintenance_run_details"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("maintenance_agent_run_items", sa.Column("work_state", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("maintenance_agent_run_items", "work_state")
