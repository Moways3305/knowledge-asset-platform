"""外部 Agent 接入注册 ORM 模型（provider 中立，抽象收口）。

一张表 `agent_whitelist_rules`（语义为
**外部 Agent 接入注册与 capability 边界**，非"逐 Agent 手工名单"）。`provider` 列区分
具体上层平台（dify / coze / 自研 / custom），其余字段（agent_identifier / agent_name /
capability / allowed_scope / allowed_project_id / max_*level / enabled / risk_*）均 provider 中立。

安全红线：
- **绝不存明文 token**：只存 `token_hash`（sha256）。
- `token_hash` / `external_app_id` / `external_workflow_id`（provider 内部标识）是 server-only，
  **绝不**进任何 API 响应 / 审计 / 日志 / 前端。
- `agent_identifier` 是 Gateway 内部标识，不暴露给任何 provider 响应。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AgentWhitelistRule(Base):
    __tablename__ = "agent_whitelist_rules"
    __table_args__ = (
        UniqueConstraint("agent_identifier", name="uq_agent_whitelist_identifier"),
        UniqueConstraint("token_hash", name="uq_agent_whitelist_token_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # provider：上层平台标识（dify / internal / custom），为未来自研平台替换 Dify 留抽象。
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="dify")
    # Gateway 内部标识（不暴露给 Dify 响应 / 前端）。
    agent_identifier: Mapped[str] = mapped_column(String(200), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # 允许的能力（当前启用 qa；其余值即便存在也按 capability 边界拒绝）。
    capability: Mapped[str] = mapped_column(String(30), nullable=False, default="qa")
    # 安全限制（None = 不额外约束 scope；具体仍由每调用人 decide() 收口）。
    allowed_scope: Mapped[str | None] = mapped_column(String(100), nullable=True)
    allowed_project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id"), nullable=True
    )
    max_confidentiality_level: Mapped[str] = mapped_column(String(2), nullable=False, default="L2")
    max_ai_access_level: Mapped[str] = mapped_column(String(2), nullable=False, default="A2")
    # Bearer token 的 sha256（**绝不存明文**，绝不外泄）。
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    risk_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    risk_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Dify 侧内部标识（server-only；绝不进响应 / 审计 / 前端）。
    external_app_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    external_workflow_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

