"""add recoverable local upload sessions

Revision ID: 0051_upload_sessions
Revises: 0050_ingest_task_result_version
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0051_upload_sessions"
down_revision: str | None = "0050_ingest_task_result_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "upload_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("total_files", sa.Integer(), nullable=False),
        sa.Column("total_batches", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "upload_session_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("ingest_task_id", sa.Uuid(), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("batch_index", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=500), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("file_type", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("safe_error_code", sa.String(length=50), nullable=True),
        sa.Column("safe_error_message", sa.String(length=300), nullable=True),
        sa.Column("same_name_warning", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ingest_task_id"], ["ingest_tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["upload_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ingest_task_id"),
    )
    op.create_index(
        "ix_upload_session_items_session_id",
        "upload_session_items",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        "uq_upload_session_items_order",
        "upload_session_items",
        ["session_id", "ordinal"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_upload_session_items_order", table_name="upload_session_items")
    op.drop_index("ix_upload_session_items_session_id", table_name="upload_session_items")
    op.drop_table("upload_session_items")
    op.drop_table("upload_sessions")
