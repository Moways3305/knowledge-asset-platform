"""Add ops reconcile heartbeat table.

Revision ID: 0055_ops_reconcile_heartbeat
Revises: 0054_llm_usage_events
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0055_ops_reconcile_heartbeat"
down_revision: str | None = "0054_llm_usage_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ops_reconcile_heartbeats",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed", sa.Integer(), nullable=False),
        sa.Column("updated", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ops_reconcile_heartbeats_observed_at",
        "ops_reconcile_heartbeats",
        ["observed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ops_reconcile_heartbeats_observed_at", table_name="ops_reconcile_heartbeats")
    op.drop_table("ops_reconcile_heartbeats")
