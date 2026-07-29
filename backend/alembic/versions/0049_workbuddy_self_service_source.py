"""mark server-created WorkBuddy self-service rules

Revision ID: 0049_workbuddy_self_service_source
Revises: 0048_workbuddy_last_connected_at
Create Date: 2026-07-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0049_workbuddy_self_service_source"
down_revision: str | None = "0048_workbuddy_last_connected_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agent_whitelist_rules") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_self_service",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )

    # 历史自助服务会写 token_rotated_at，管理员 CRUD 无法写该字段。两项同时满足才迁移，
    # 不能只信任管理员可控的 agent_identifier。
    op.execute(
        sa.text(
            """
            UPDATE agent_whitelist_rules
            SET is_self_service = true
            WHERE provider = 'workbuddy'
              AND token_rotated_at IS NOT NULL
              AND agent_identifier LIKE 'workbuddy:self:%'
            """
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("agent_whitelist_rules") as batch_op:
        batch_op.drop_column("is_self_service")
