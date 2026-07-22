"""create_ingest_pipeline_tables

建立入库流水线两张表：ingest_tasks / ingest_task_ai_results（IMPLEMENT-05）。
不创建 wecom_scan_* / review / audit / preview / agent 等后续业务表。

Revision ID: 0003_ingest
Revises: 0002_knowledge
Create Date: 2026-05-29

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_ingest"
down_revision: str | None = "0002_knowledge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingest_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("source_file_ref", sa.String(length=1000), nullable=False),
        sa.Column("source_file_name", sa.String(length=500), nullable=False),
        sa.Column("source_file_mime_type", sa.String(length=100), nullable=True),
        sa.Column("source_file_size", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("target_scope", sa.String(length=20), nullable=True),
        sa.Column("target_project_id", sa.Uuid(), nullable=True),
        sa.Column("target_zone", sa.String(length=20), nullable=True),
        sa.Column("result_asset_id", sa.Uuid(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("error_type", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["target_project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["result_asset_id"], ["knowledge_assets.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ingest_tasks_status_created_at",
        "ingest_tasks",
        ["status", "created_at"],
    )

    op.create_table(
        "ingest_task_ai_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ingest_task_id", sa.Uuid(), nullable=False),
        sa.Column("suggested_title", sa.String(length=500), nullable=True),
        sa.Column("suggested_summary", sa.Text(), nullable=True),
        sa.Column("suggested_tags", sa.JSON(), nullable=True),
        sa.Column("suggested_asset_type", sa.String(length=30), nullable=True),
        sa.Column("suggested_confidentiality_level", sa.String(length=2), nullable=True),
        sa.Column("suggested_ai_access_level", sa.String(length=2), nullable=True),
        sa.Column("suggested_phase_key", sa.String(length=50), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("naming_compliant", sa.Boolean(), nullable=True),
        sa.Column("naming_parsed_fields", sa.JSON(), nullable=True),
        sa.Column("naming_anomalies", sa.JSON(), nullable=True),
        sa.Column("human_corrected", sa.Boolean(), nullable=False),
        sa.Column("corrected_title", sa.String(length=500), nullable=True),
        sa.Column("corrected_summary", sa.Text(), nullable=True),
        sa.Column("corrected_tags", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ingest_task_id"], ["ingest_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("ingest_task_ai_results")
    op.drop_index("ix_ingest_tasks_status_created_at", table_name="ingest_tasks")
    op.drop_table("ingest_tasks")
