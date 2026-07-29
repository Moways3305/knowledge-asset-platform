"""track successful WorkBuddy connector activity

Revision ID: 0048_workbuddy_last_connected_at
Revises: 0047_indexing_ops_parse_failed
Create Date: 2026-07-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0048_workbuddy_last_connected_at"
down_revision: str | None = "0047_indexing_ops_parse_failed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agent_whitelist_rules") as batch_op:
        batch_op.add_column(sa.Column("last_connected_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    with op.batch_alter_table("agent_whitelist_rules") as batch_op:
        batch_op.drop_column("last_connected_at")
