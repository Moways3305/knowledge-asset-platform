"""index recovery evidence

Revision ID: 0063_index_recovery_evidence
Revises: 0062_directory_migration_candidates
"""

from alembic import op
import sqlalchemy as sa


revision = "0063_index_recovery_evidence"
down_revision = "0062_directory_migration_candidates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_asset_versions",
        sa.Column(
            "index_reconcile_failure_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "knowledge_asset_versions",
        sa.Column("index_last_reconcile_failed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_asset_versions", "index_last_reconcile_failed_at")
    op.drop_column("knowledge_asset_versions", "index_reconcile_failure_count")
