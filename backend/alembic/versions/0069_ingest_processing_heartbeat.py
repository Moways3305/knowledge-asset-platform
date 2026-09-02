"""add ingest processing heartbeat

Revision ID: 0069_ingest_processing_heartbeat
Revises: 0068_upload_duplicate_decisions
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0069_ingest_processing_heartbeat"
down_revision: str | None = "0068_upload_duplicate_decisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ingest_tasks", sa.Column("processing_heartbeat_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_ingest_tasks_processing_heartbeat_at", "ingest_tasks", ["processing_heartbeat_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_ingest_tasks_processing_heartbeat_at", table_name="ingest_tasks")
    op.drop_column("ingest_tasks", "processing_heartbeat_at")
