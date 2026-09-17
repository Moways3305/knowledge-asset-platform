"""Add durable per-version parse reconciliation leases.

Revision ID: 0073_parse_reconcile_lease
Revises: 0072_cooperative_upload_cancellation
"""

import sqlalchemy as sa

from alembic import op

revision = "0073_parse_reconcile_lease"
down_revision = "0072_cooperative_upload_cancellation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_asset_versions", sa.Column("parse_reconcile_token", sa.String(36), nullable=True)
    )
    op.add_column(
        "knowledge_asset_versions",
        sa.Column("parse_reconcile_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_asset_versions", "parse_reconcile_until")
    op.drop_column("knowledge_asset_versions", "parse_reconcile_token")
