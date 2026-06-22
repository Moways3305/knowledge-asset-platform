"""外部 Agent / 工作流网关的 **provider 中立** 请求 / 响应 schema。

平台核心是 provider 中立的「外部 Agent / 工作流网关」；Dify 只是其中一个兼容适配器
（见 `app/api/dify.py`）。本模块定义与具体 provider 无关的安全数据形态：

- `ExternalRetrievalRecord`：网关返回给上层调用方的安全检索证据（已脱敏 / 安全摘要）。
- 接入注册（registry）的安全管理视图与请求体。

安全：所有响应**绝不**含 token / token_hash / provider 内部标识（app/workflow/dataset id）/
agent_identifier / WeKnora kb·doc·chunk id / 内部存储引用 / api_key。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# ---------------- 网关检索结果（provider 中立）----------------
class ExternalRetrievalRecord(BaseModel):
    """网关返回的安全检索证据。content 仅安全上下文（已脱敏 / 摘要），绝不未脱敏 chunk。

    形态（content / score / title / metadata）与多数外部知识协议兼容，适配器可直接转译。
    """

    content: str
    score: float
    title: str
    # 绝不为 null；只放安全业务标识（asset_id / scope / zone / used_access_layer / citation_order）。
    metadata: dict = Field(default_factory=dict)


# ---------------- 接入注册管理（admin）----------------
class RegistryRuleOut(BaseModel):
    """注册行安全视图：不含 token_hash / provider 内部标识 / agent_identifier。"""

    id: uuid.UUID
    provider: str
    agent_name: str
    capability: str
    allowed_scope: str | None
    allowed_project_id: uuid.UUID | None
    max_confidentiality_level: str
    max_ai_access_level: str
    enabled: bool
    # WorkBuddy 绑定用户安全展示（admin 视图；绝不含 token / token_hash）。
    bound_user_id: uuid.UUID | None = None
    bound_user_name: str | None = None
    bound_user_active: bool | None = None
    risk_level: str | None
    risk_note: str | None
    created_at: datetime
    updated_at: datetime


class RegistryListResponse(BaseModel):
    items: list[RegistryRuleOut]


class RegistryCreateRequest(BaseModel):
    provider: str = "custom"
    # per-user 绑定：provider=workbuddy 时必填；指向 active 业务用户。
    bound_user_id: uuid.UUID | None = None
    agent_identifier: str
    agent_name: str
    capability: str = "qa"
    allowed_scope: str | None = None
    allowed_project_id: uuid.UUID | None = None
    max_confidentiality_level: str = "L2"
    max_ai_access_level: str = "A2"
    enabled: bool = True
    risk_level: str | None = None
    risk_note: str | None = None
    # provider 内部标识（如某 provider 的 app/workflow 引用）：server-only，仅入库不回显。
    external_app_id: str | None = None
    external_workflow_id: str | None = None


class RegistryUpdateRequest(BaseModel):
    enabled: bool | None = None
    capability: str | None = None
    allowed_scope: str | None = None
    allowed_project_id: uuid.UUID | None = None
    max_confidentiality_level: str | None = None
    max_ai_access_level: str | None = None
    risk_level: str | None = None
    risk_note: str | None = None
    # 重置 token（明文仅一次性返回）。
    regenerate_token: bool = False


class RegistryCreateResponse(BaseModel):
    """创建 / 重置 token 响应。token 明文**仅此一次**返回，之后不可再取。"""

    rule: RegistryRuleOut
    # 仅创建或重置 token 时非空（明文一次性）。
    token: str | None = None
