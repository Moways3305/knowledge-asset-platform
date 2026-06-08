"""version_index_status

PBC-11B 知识底座索引解耦：给 knowledge_asset_versions 增加平台级索引状态字段，把
「人工确认=资产落库」与「WeKnora 底座索引」拆成两个失败边界。confirm 成功即落库，
底座建库/初始化/上传失败不再回滚资产，而是在这些字段上记可诊断、可重试的失败状态。

新增列（仅 knowledge_asset_versions，不动其它表）：
- index_status        not_indexed | indexing | indexed | index_failed | skipped（NOT NULL，默认 not_indexed）
- index_error_code    安全错误码（如 weknora_upload_failed / weknora_init_failed）
- index_error_message 安全中文文案（绝不含 kb_id / doc_id / api_key / 原始 payload）
- indexed_at          索引成功时间

PostgreSQL / SQLite 兼容，可逆 downgrade。

Revision ID: 0024_version_index_status
Revises: 0023_knowledge_delete
Create Date: 2026-06-04

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_version_index_status"
down_revision: str | None = "0023_knowledge_delete"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "knowledge_asset_versions",
        sa.Column(
            "index_status",
            sa.String(length=20),
            nullable=False,
            server_default="not_indexed",
        ),
    )
    op.add_column(
        "knowledge_asset_versions",
        sa.Column("index_error_code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "knowledge_asset_versions",
        sa.Column("index_error_message", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "knowledge_asset_versions",
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_asset_versions", "indexed_at")
    op.drop_column("knowledge_asset_versions", "index_error_message")
    op.drop_column("knowledge_asset_versions", "index_error_code")
    op.drop_column("knowledge_asset_versions", "index_status")
