"""knowledge_delete

PBC-10B 知识资产受控删除（软删除）：给 knowledge_assets 新增 deleted_at / deleted_by /
delete_reason 追溯字段。不物理删除资产主记录，仅置 asset_status=deleted。PostgreSQL /
SQLite 兼容。

Revision ID: 0023_knowledge_delete
Revises: 0022_wecom_scan_config_name
Create Date: 2026-06-03

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023_knowledge_delete"
down_revision: str | None = "0022_wecom_scan_config_name"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("knowledge_assets", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("knowledge_assets", sa.Column("deleted_by", sa.Uuid(), nullable=True))
    op.add_column("knowledge_assets", sa.Column("delete_reason", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_knowledge_assets_deleted_by_users",
        "knowledge_assets", "users",
        ["deleted_by"], ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_knowledge_assets_deleted_by_users", "knowledge_assets", type_="foreignkey")
    op.drop_column("knowledge_assets", "delete_reason")
    op.drop_column("knowledge_assets", "deleted_by")
    op.drop_column("knowledge_assets", "deleted_at")
