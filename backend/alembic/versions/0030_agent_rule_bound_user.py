"""agent_rule_bound_user

WorkBuddy per-user token 绑定：为 agent_whitelist_rules 增加 bound_user_id（FK users.id，nullable）。
legacy（dify）行保持 NULL。可逆 downgrade（drop_column）。
SQLite 测试库由 create_all 直接建表覆盖，不走本迁移。

Revision ID: 0030_agent_rule_bound_user
Revises: 0029_weknora_kb_display_name
Create Date: 2026-06-22

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0030_agent_rule_bound_user"
down_revision: str | None = "0029_weknora_kb_display_name"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_whitelist_rules",
        sa.Column("bound_user_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_whitelist_bound_user",
        "agent_whitelist_rules",
        "users",
        ["bound_user_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_agent_whitelist_bound_user", "agent_whitelist_rules", type_="foreignkey")
    op.drop_column("agent_whitelist_rules", "bound_user_id")
