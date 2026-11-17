"""Optional review cadence and explicit, asset-scoped maintenance delegation."""

import sqlalchemy as sa
from alembic import op

revision = "0093_optional_knowledge_review"
down_revision = "0092_notification_inbox"
branch_labels = None
depends_on = None


def upgrade():
    # Existing dates remain one-time schedules. Existing assignments grant no new rights.
    op.add_column("knowledge_assets", sa.Column("review_interval_days", sa.Integer()))
    op.add_column(
        "knowledge_assets",
        sa.Column("maintenance_delegated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("knowledge_assets", "maintenance_delegated")
    op.drop_column("knowledge_assets", "review_interval_days")
