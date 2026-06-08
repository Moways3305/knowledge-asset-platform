"""Agent / Dify Gateway API 的请求 / 响应 schema。

这些响应 schema **绝不包含** 服务端内部存储引用、向量库标识、Dify 内部标识
（凭证 / 数据集 / 工作流 ID）、对象存储 URL、完整原文文件内容或 chunk 原始主键。

citation 只返回安全展示字段（asset_id 作为平台业务 ID、标题、scope、zone、
used_access_layer 等）；asset_id 是平台业务主键，不是对象存储 / 向量库内部标识。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.enums import AgentCapability


class ProjectQaRequest(BaseModel):
    """项目 Q&A 请求。

    model_key / capability 可选；model_key 仅记录到 agent_calls，不改变权限判断逻辑。
    """

    query: str
    model_key: str = "system_default"
    capability: AgentCapability = AgentCapability.qa


class CitationOut(BaseModel):
    """安全引用结构（不暴露内部标识）。

    R3：新增 seq（安全序号，非 WeKnora 内部 id）+ snippet（已脱敏的引用片段）。
    WeKnora chunk 引用是 server-only（存 cited_weknora_chunk_ref），**绝不**进本响应。
    """

    # asset_id 是平台业务主键（非对象存储 / 向量库内部标识），可对外。
    asset_id: uuid.UUID
    asset_title: str
    scope: str
    # 契约 §10：引用字段名为 cited_zone（值仍是 material / asset）。
    cited_zone: str
    used_access_layer: str
    is_pending_review: bool
    is_asset_zone: bool
    citation_order: int
    # R3：引用来源片段（脱敏后，可空）+ 安全序号（chunk 序，非内部 id）。
    seq: int | None = None
    snippet: str | None = None


class ProjectQaResponse(BaseModel):
    """项目 Q&A 响应（治理控制台 / 上层调用方共用）。"""

    call_id: uuid.UUID
    response_text: str
    model_key: str
    decision_status: str
    citations: list[CitationOut]
    trace_id: str | None = None
    created_at: datetime


class AgentCallDetailResponse(BaseModel):
    """Agent 调用记录详情（本人 / boss / 咨询总监可见）。"""

    call_id: uuid.UUID
    caller_user_id: uuid.UUID
    project_id: uuid.UUID
    # 契约 §15：query_text + 人类可读名（用于 /admin/audit 等治理展示）。
    query_text: str
    caller_name: str
    project_name: str
    response_text: str | None
    model_key: str
    capability: str
    provider: str
    call_status: str
    denied_reason: str | None
    citations: list[CitationOut]
    trace_id: str | None
    created_at: datetime


class DecisionItemOut(BaseModel):
    """候选项决策明细（治理解释 / 审计用）。"""

    target_asset_id: uuid.UUID
    target_scope: str
    target_confidentiality_level: str
    target_ai_access_level: str
    discovery_allowed: bool
    summary_allowed: bool
    original_allowed: bool
    returned_layer: str | None
    effective_access_source: str | None
    denied_reason: str | None


class DecisionItemsResponse(BaseModel):
    call_id: uuid.UUID
    decision_status: str
    items: list[DecisionItemOut]

