"""weknora_kb_display_name

PBC-29 个人知识库管理：为 `weknora_kb_mappings` 增加 `display_name`（用户可读名称）。

- 只加列 + 回填，不改既有列语义、不动 kb_name（slug 技术标识保持向后兼容）。
- 个人 KB 必有可读名称：既有 personal 映射回填默认值「我的知识库」（仅当为 NULL 时）。
- project / company 映射保持 NULL（项目名来自 projects 表，公司 KB 用固定文案）。

PostgreSQL / SQLite 兼容（add_column + UPDATE）。可逆 downgrade（drop_column）。
SQLite 测试库由 create_all 直接建表覆盖，不走本迁移。

Revision ID: 0029_weknora_kb_display_name
Revises: 0028_auth_login_attempts
Create Date: 2026-06-15

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0029_weknora_kb_display_name"
down_revision: str | None = "0028_auth_login_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "weknora_kb_mappings",
        sa.Column("display_name", sa.String(length=200), nullable=True),
    )
    # 既有个人映射回填用户可读默认名（仅 NULL 行；项目/公司保持 NULL）。
    op.execute(
        "UPDATE weknora_kb_mappings SET display_name = '我的知识库' "
        "WHERE scope = 'personal' AND display_name IS NULL"
    )


def downgrade() -> None:
    op.drop_column("weknora_kb_mappings", "display_name")
