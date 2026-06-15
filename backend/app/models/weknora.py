"""WeKnora scope→KB 映射 ORM 模型（WeKnora 底座接入）。

一张表 `weknora_kb_mappings`：把业务 scope 实体（personal 用户 / project 项目 /
company 全局）映射到 WeKnora 的知识库 id。

安全：`weknora_kb_id` 是 WeKnora 底座内部标识，**server-only**，视同 storage_ref，
绝不进任何 API 响应 / 审计 extra / 日志 / 前端。映射只供后端 scope 路由使用。

唯一约束 `(scope, owner_user_id, project_id)` 保证每个 scope 实体至多一个 KB
（KB 懒创建幂等的兜底；并发重复确认靠唯一冲突重查）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class WeknoraKbMapping(Base):
    __tablename__ = "weknora_kb_mappings"
    __table_args__ = (
        UniqueConstraint(
            "scope", "owner_user_id", "project_id", name="uq_weknora_kb_scope_entity"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # personal / project / company
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id"), nullable=True
    )
    # WeKnora 内部 KB id（server-only，绝不外泄）。
    weknora_kb_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # 建库时固定的 embedding 模型 id（全平台统一；事后不可改）。
    embedding_model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    kb_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # 用户可读名称（PBC-29）。personal KB 必有（创建时给定或回填「我的知识库」）；
    # project / company KB 可空（项目名来自 projects 表，公司 KB 用固定文案）。
    # 与 kb_name（slug 技术标识）解耦：改名只动 display_name，不动 slug。
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
