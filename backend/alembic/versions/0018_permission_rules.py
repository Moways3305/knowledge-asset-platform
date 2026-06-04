"""permission_rules

PBC-03 权限规则配置中心：建 permission_rules 表（阈值 / 开关 / 固定路径三类治理配置）。
只存配置值，绝不存任何 secret；rule_key 唯一。PostgreSQL / SQLite 兼容。不动其它表。

Revision ID: 0018_permission_rules
Revises: 0017_r7_preview_notify
Create Date: 2026-06-02

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_permission_rules"
down_revision: str | None = "0017_r7_preview_notify"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "permission_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rule_key", sa.String(length=100), nullable=False),
        sa.Column("rule_group", sa.String(length=50), nullable=False),
        sa.Column("rule_type", sa.String(length=30), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("value_bool", sa.Boolean(), nullable=True),
        sa.Column("value_number", sa.Numeric(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("default_bool", sa.Boolean(), nullable=True),
        sa.Column("default_number", sa.Numeric(), nullable=True),
        sa.Column("default_text", sa.Text(), nullable=True),
        sa.Column("unit", sa.String(length=30), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("editable", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_key", name="uq_permission_rules_rule_key"),
    )


def downgrade() -> None:
    op.drop_table("permission_rules")
