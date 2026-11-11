"""Persist bounded governance scan progress without changing business timestamps.

Stop old lifecycle scan producers/consumers before upgrading. Drain new scan
tasks before downgrade; historic events, notifications and assets are retained.
"""

import sqlalchemy as sa

from alembic import op

revision = "0085_governance_scan_batches"
down_revision = "0084_notification_delivery_lease"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for kind in ("archive", "review"):
        op.add_column(
            "knowledge_assets",
            sa.Column(f"{kind}_scan_checked_at", sa.DateTime(timezone=True), nullable=True),
        )
        predicate = (
            "asset_status = 'active' AND deleted_at IS NULL"
            if kind == "archive"
            else "asset_status IN ('active', 'needs_update') AND deleted_at IS NULL AND review_due_at IS NOT NULL"
        )
        op.create_index(
            f"ix_assets_{kind}_scan",
            "knowledge_assets",
            [f"{kind}_scan_checked_at", "id"],
            postgresql_where=sa.text(predicate),
            sqlite_where=sa.text(predicate),
        )
    op.create_table(
        "governance_scan_runs",
        sa.Column("name", sa.String(20), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("parameters", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("governance_scan_runs")
    for kind in ("review", "archive"):
        op.drop_index(f"ix_assets_{kind}_scan", table_name="knowledge_assets")
        op.drop_column("knowledge_assets", f"{kind}_scan_checked_at")
