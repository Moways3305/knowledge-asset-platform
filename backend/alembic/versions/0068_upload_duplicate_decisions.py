"""Upload duplicate decisions and indexed hash lookup.

Revision ID: 0068_upload_duplicate_decisions
Revises: 0067_domain_event_outbox
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0068_upload_duplicate_decisions"
down_revision = "0067_domain_event_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingest_tasks", sa.Column("duplicate_decision", sa.String(length=20), nullable=True)
    )
    op.add_column(
        "ingest_tasks",
        sa.Column("duplicate_decision_reason", sa.String(length=300), nullable=True),
    )
    op.add_column(
        "ingest_tasks",
        sa.Column("duplicate_decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_ingest_tasks_source_hash_status_scope",
        "ingest_tasks",
        ["source_file_hash", "status", "target_scope", "target_project_id"],
    )
    op.create_index(
        "ix_asset_versions_file_hash_status",
        "knowledge_asset_versions",
        ["file_hash", "version_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_asset_versions_file_hash_status", table_name="knowledge_asset_versions")
    op.drop_index("ix_ingest_tasks_source_hash_status_scope", table_name="ingest_tasks")
    op.drop_column("ingest_tasks", "duplicate_decided_at")
    op.drop_column("ingest_tasks", "duplicate_decision_reason")
    op.drop_column("ingest_tasks", "duplicate_decision")
