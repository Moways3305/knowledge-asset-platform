"""agent_token_rotated_at

自助 WorkBuddy token：为 agent_whitelist_rules 增加 token_rotated_at（nullable），
记录最近一次轮换时间(last_rotated_at 展示用)。可逆 downgrade(drop_column)。
SQLite 测试库由 create_all 直接建表覆盖，不走本迁移。

Revision ID: 0032_agent_token_rotated_at
Revises: 0031_agent_rule_bound_user
Create Date: 2026-06-22

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0032_agent_token_rotated_at"
down_revision: str | None = "0031_agent_rule_bound_user"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_whitelist_rules",
        sa.Column("token_rotated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_whitelist_rules", "token_rotated_at")
