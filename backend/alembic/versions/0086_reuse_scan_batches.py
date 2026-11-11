"""Bound reuse scans and index citation/history lookups.

Stop old reuse producers/consumers before upgrade. Drain reuse tasks before
downgrade; only operational progress is removed, never business/audit history.
"""

import sqlalchemy as sa

from alembic import op

revision = "0086_reuse_scan_batches"
down_revision = "0085_governance_scan_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_assets", sa.Column("reuse_scan_checked_at", sa.DateTime(timezone=True))
    )
    op.create_index(
        "ix_assets_reuse_scan",
        "knowledge_assets",
        ["reuse_scan_checked_at", "id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_agent_citations_asset_created_call",
        "agent_call_citations",
        ["cited_asset_id", "created_at", "call_id"],
    )
    op.create_index("ix_audit_events_action_target", "audit_events", ["action", "target_id"])


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM governance_scan_runs WHERE name = 'reuse'"))
    op.drop_index("ix_audit_events_action_target", table_name="audit_events")
    op.drop_index("ix_agent_citations_asset_created_call", table_name="agent_call_citations")
    op.drop_index("ix_assets_reuse_scan", table_name="knowledge_assets")
    op.drop_column("knowledge_assets", "reuse_scan_checked_at")
