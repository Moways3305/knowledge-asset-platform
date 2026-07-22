"""user_password_credentials

PBC-12 密码凭证登录：给 users 增加 server-only 密码哈希字段。

新增列（仅 users，不动其它表）：
- password_hash     PBKDF2 编码哈希（server-only，绝不进响应/审计/日志）
- password_set_at   最近一次设置密码时间

PostgreSQL / SQLite 兼容（仅 add_column），可逆 downgrade。

Revision ID: 0025_user_password_credentials
Revises: 0024_version_index_status
Create Date: 2026-06-04

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0025_user_password_credentials"
down_revision: str | None = "0024_version_index_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("password_set_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "password_set_at")
    op.drop_column("users", "password_hash")
