"""project_settings

PBC-04 项目设置：给 projects 表新增项目设置字段（客户名 / 生命周期路线·阶段 /
入库强制审核开关 / 企微群配置）。只存安全配置值，不存任何 secret。PostgreSQL / SQLite 兼容。

Revision ID: 0019_project_settings
Revises: 0018_permission_rules
Create Date: 2026-06-02

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_project_settings"
down_revision: str | None = "0018_permission_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("client_name", sa.String(length=200), nullable=True))
    op.add_column(
        "projects",
        sa.Column("lifecycle_route_key", sa.String(length=20), nullable=True,
                  server_default="route_A"),
    )
    op.add_column("projects", sa.Column("lifecycle_phase_key", sa.String(length=50), nullable=True))
    op.add_column(
        "projects",
        sa.Column("force_review_on_ingest", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )
    op.add_column("projects", sa.Column("wecom_group_id", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "wecom_group_id")
    op.drop_column("projects", "force_review_on_ingest")
    op.drop_column("projects", "lifecycle_phase_key")
    op.drop_column("projects", "lifecycle_route_key")
    op.drop_column("projects", "client_name")
