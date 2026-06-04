"""wecom_scan_config_name

PBC-10A 企微微盘扫描配置 CRUD：给 wecom_scan_configs 表新增人类可读的配置名 `name`。
仅安全配置元数据，不存任何 secret / file_id / token。历史行允许 NULL（读侧回退展示）。
PostgreSQL / SQLite 兼容。

Revision ID: 0022_wecom_scan_config_name
Revises: 0021_original_access
Create Date: 2026-06-03

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_wecom_scan_config_name"
down_revision: str | None = "0021_original_access"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "wecom_scan_configs",
        sa.Column("name", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("wecom_scan_configs", "name")
