"""add indexing operations health and targeted retry guard

Revision ID: 0043_indexing_ops_health
Revises: 0042_business_notifications
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0043_indexing_ops_health"
down_revision: str | None = "0042_business_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("indexing_operation_jobs") as batch_op:
        batch_op.add_column(sa.Column("target_asset_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_indexing_jobs_target_asset", "knowledge_assets", ["target_asset_id"], ["id"]
        )
    op.create_index(
        "uq_indexing_active_target_retry",
        "indexing_operation_jobs",
        ["target_asset_id"],
        unique=True,
        sqlite_where=sa.text(
            "target_asset_id IS NOT NULL AND operation_type = 'retry_index' "
            "AND status IN ('queued', 'running')"
        ),
        postgresql_where=sa.text(
            "target_asset_id IS NOT NULL AND operation_type = 'retry_index' "
            "AND status IN ('queued', 'running')"
        ),
    )
    op.create_table(
        "indexing_ops_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bucket_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("index_failed", sa.Integer(), nullable=False),
        sa.Column("indexing", sa.Integer(), nullable=False),
        sa.Column("not_indexed", sa.Integer(), nullable=False),
        sa.Column("skipped", sa.Integer(), nullable=False),
        sa.Column("parse_pending", sa.Integer(), nullable=False),
        sa.Column("parse_processing", sa.Integer(), nullable=False),
        sa.Column("kb_init_failed", sa.Integer(), nullable=False),
        sa.Column("completed_jobs", sa.Integer(), nullable=False),
        sa.Column("failed_jobs", sa.Integer(), nullable=False),
        sa.Column("queued_jobs", sa.Integer(), nullable=False),
        sa.Column("oldest_queued_seconds", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bucket_started_at"),
    )
    op.create_table(
        "ops_runtime_heartbeats",
        sa.Column("component", sa.String(length=20), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("component"),
    )


def downgrade() -> None:
    op.drop_table("ops_runtime_heartbeats")
    op.drop_table("indexing_ops_snapshots")
    op.drop_index("uq_indexing_active_target_retry", table_name="indexing_operation_jobs")
    with op.batch_alter_table("indexing_operation_jobs") as batch_op:
        batch_op.drop_constraint("fk_indexing_jobs_target_asset", type_="foreignkey")
        batch_op.drop_column("target_asset_id")
