"""project archived status declaration

项目归档状态：projects.status 列自 0001 迁移起即已存在（VARCHAR(20) NOT NULL，
默认 'active'），应用层枚举 ProjectStatus（active / completed / archived）也早已
覆盖 archived 值。本迁移为声明性 no-op：仅固化 archived 作为受支持的 status 值，
不新增 / 不修改任何列。

Revision ID: 0045_project_archived_status
Revises: 0044_agent_whitelist_unique_provider_user
Create Date: 2026-07-21
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0045_project_archived_status"
down_revision: str | None = "0044_agent_whitelist_unique_provider_user"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # projects.status 列已存在（迁移 0001），无需新增 / 修改。
    # archived 值由应用层 ProjectStatus 枚举约束；此处仅为迁移链记录，不改 schema。
    pass


def downgrade() -> None:
    # 声明性迁移，无 schema 变更可回滚。
    pass
