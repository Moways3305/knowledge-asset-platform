"""OCR worker leases, orphan recovery and page checkpoints.

Revision ID: 0069_ocr_queue_recovery
Revises: 0068_upload_duplicate_decisions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0069_ocr_queue_recovery"
down_revision = "0068_upload_duplicate_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingest_tasks", sa.Column("processing_started_at", sa.DateTime(timezone=True)))
    op.add_column("ingest_tasks", sa.Column("processing_heartbeat_at", sa.DateTime(timezone=True)))
    op.add_column(
        "ingest_tasks",
        sa.Column("processing_attempt", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("ingest_tasks", sa.Column("processing_worker_id", sa.String(length=255)))
    op.add_column("ingest_tasks", sa.Column("processing_job_id", sa.String(length=255)))
    op.add_column("ingest_tasks", sa.Column("recovery_not_before", sa.DateTime(timezone=True)))
    op.create_index(
        "ix_ingest_tasks_processing_heartbeat_at",
        "ingest_tasks",
        ["processing_heartbeat_at"],
    )
    op.add_column("ingest_task_ai_results", sa.Column("ocr_page_texts", sa.JSON()))


def downgrade() -> None:
    op.drop_column("ingest_task_ai_results", "ocr_page_texts")
    op.drop_index("ix_ingest_tasks_processing_heartbeat_at", table_name="ingest_tasks")
    op.drop_column("ingest_tasks", "recovery_not_before")
    op.drop_column("ingest_tasks", "processing_job_id")
    op.drop_column("ingest_tasks", "processing_worker_id")
    op.drop_column("ingest_tasks", "processing_attempt")
    op.drop_column("ingest_tasks", "processing_heartbeat_at")
    op.drop_column("ingest_tasks", "processing_started_at")
