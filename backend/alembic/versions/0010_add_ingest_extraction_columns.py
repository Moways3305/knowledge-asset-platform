"""add_ingest_extraction_columns

IMPLEMENT-14 入库抽取管线：窄 ALTER，仅给既有两表加列，不建新表、不动 knowledge 表。

- ingest_tasks: + source_file_hash
- ingest_task_ai_results: + extracted_text / extracted_char_count / extraction_status
  / duplicate_of_task_id / duplicate_of_asset_id

Revision ID: 0010_ingest_extract
Revises: 0009_session
Create Date: 2026-05-30

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_ingest_extract"
down_revision: str | None = "0009_session"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ingest_tasks",
        sa.Column("source_file_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "ingest_task_ai_results",
        sa.Column("extracted_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "ingest_task_ai_results",
        sa.Column("extracted_char_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "ingest_task_ai_results",
        sa.Column("extraction_status", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "ingest_task_ai_results",
        sa.Column("duplicate_of_task_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "ingest_task_ai_results",
        sa.Column("duplicate_of_asset_id", sa.Uuid(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ingest_task_ai_results", "duplicate_of_asset_id")
    op.drop_column("ingest_task_ai_results", "duplicate_of_task_id")
    op.drop_column("ingest_task_ai_results", "extraction_status")
    op.drop_column("ingest_task_ai_results", "extracted_char_count")
    op.drop_column("ingest_task_ai_results", "extracted_text")
    op.drop_column("ingest_tasks", "source_file_hash")
