"""indexing_operation_jobs

PBC-15 索引批量重试 / 显式 reparse / 后台队列：新增运维任务表
`indexing_operation_jobs`，记录批量索引运维作业的安全状态与统计。

新表仅含安全运维元数据：operation_type / status / 安全 scope_filter（JSON）/ 计数 /
安全 error_code+message / trace_id；**绝不**含原文 / 文件名 / storage ref / source ref /
WeKnora kb·doc id / 上游原始 message。

PostgreSQL / SQLite 兼容（create_table），可逆 downgrade（drop_table）。SQLite 测试库
由 create_all 直接建表覆盖。

Revision ID: 0027_indexing_operation_jobs
Revises: 0026_ingest_desensitization_metadata
Create Date: 2026-06-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0027_indexing_operation_jobs"
down_revision: str | None = "0026_ingest_desensitization_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "indexing_operation_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("operation_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="queued"),
        sa.Column("scope_filter", sa.JSON(), nullable=True),
        sa.Column(
            "requested_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("indexing_operation_jobs")
