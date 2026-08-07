"""外部 Agent 接入注册 ORM 模型（provider 中立，抽象收口）。

一张表 `agent_whitelist_rules`（语义为
**外部 Agent 接入注册与 capability 边界**，非"逐 Agent 手工名单"）。`provider` 列区分
具体上层平台（workbuddy / custom 等），其余字段（agent_identifier / agent_name /
capability / allowed_scope / allowed_project_id / max_*level / enabled / risk_*）均 provider 中立。

安全红线：
- **绝不存明文 token**：只存 `token_hash`（sha256）。
- `token_hash` / `external_app_id` / `external_workflow_id`（provider 内部标识）是 server-only，
  **绝不**进任何 API 响应 / 审计 / 日志 / 前端。
- `agent_identifier` 是 Gateway 内部标识，不暴露给任何 provider 响应。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.utils import utc_now


class AgentWhitelistRule(Base):
    __tablename__ = "agent_whitelist_rules"
    __table_args__ = (
        UniqueConstraint("agent_identifier", name="uq_agent_whitelist_identifier"),
        UniqueConstraint("token_hash", name="uq_agent_whitelist_token_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # provider：上层平台标识（workbuddy / custom），provider 中立。默认中立 custom。
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="custom")
    # WorkBuddy/per-user 接入：token 绑定唯一 KAP 业务用户；调用时只从此解析 caller。
    # custom 可绑可不绑；未绑定的注册行仅可用于平台侧管理，不可发起 Agent 调用。
    bound_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    # Gateway 内部标识（不暴露给 provider 响应 / 前端）。
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
    # 仅服务器自助 token 服务可写的来源标记。管理员 CRUD schema 不接收/回显该字段；
    # agent_identifier 是管理员可控文本，绝不能替代此安全边界。
    is_self_service: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    risk_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    risk_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # provider 侧内部标识（server-only；绝不进响应 / 审计 / 前端）。
    external_app_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    external_workflow_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # 自助 WorkBuddy token 最近一次轮换时间（last_rotated_at 展示用；其它 provider 为 NULL）。
    token_rotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 最近一次成功完成 agent-gateway 调用的时间。只记录成功结果；鉴权/业务失败不更新。
    last_connected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
