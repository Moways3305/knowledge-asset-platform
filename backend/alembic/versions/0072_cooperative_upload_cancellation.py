"""Add durable cooperative cancellation to ingest tasks.

Revision ID: 0072_cooperative_upload_cancellation
Revises: 0071_backfill_directory_rule_defaults
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0072_cooperative_upload_cancellation"
down_revision = "0071_backfill_directory_rule_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ingest_tasks",
        sa.Column(
            "cancel_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "ingest_tasks",
        sa.Column("cancellation_cleaned_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ingest_tasks", "cancellation_cleaned_at")
    op.drop_column("ingest_tasks", "cancel_requested")
