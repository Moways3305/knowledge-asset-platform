"""auth_login_attempts

PBC-18 登录失败守卫：新增 `auth_login_attempts` 表，记录登录失败/成功的**不可逆**安全统计，
驱动短时锁定 / IP 限流。表内仅含 server-only 安全字段：identifier_hash（HMAC，不可逆）/
可选 identifier_hint（hash 前缀）/ user_id（已知用户）/ ip_hash（HMAC，无原始 IP）/
login_method / result / reason_code / trace_id。**绝不**含原始 email / password / hash /
salt / digest / session token / OAuth state / cookie / token_hash / 原始 IP。

PostgreSQL / SQLite 兼容（create_table + create_index），可逆 downgrade。SQLite 测试库
由 create_all 直接建表覆盖。

Revision ID: 0028_auth_login_attempts
Revises: 0027_indexing_operation_jobs
Create Date: 2026-06-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0028_auth_login_attempts"
down_revision: str | None = "0027_indexing_operation_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "auth_login_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("identifier_hash", sa.String(length=64), nullable=False),
        sa.Column("identifier_hint", sa.String(length=16), nullable=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("login_method", sa.String(length=30), nullable=False, server_default="password"),
        sa.Column("result", sa.String(length=20), nullable=False),
        sa.Column("reason_code", sa.String(length=50), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_auth_login_attempts_identifier",
        "auth_login_attempts",
        ["identifier_hash", "created_at"],
    )
    op.create_index("ix_auth_login_attempts_ip", "auth_login_attempts", ["ip_hash", "created_at"])
    op.create_index("ix_auth_login_attempts_user", "auth_login_attempts", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_auth_login_attempts_user", table_name="auth_login_attempts")
    op.drop_index("ix_auth_login_attempts_ip", table_name="auth_login_attempts")
    op.drop_index("ix_auth_login_attempts_identifier", table_name="auth_login_attempts")
    op.drop_table("auth_login_attempts")
