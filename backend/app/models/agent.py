"""外部 Agent / 工作流网关调用记录 ORM 模型。

仅四张表：agent_calls / agent_gateway_decisions / agent_gateway_decision_items /
agent_call_citations，记录网关调用与逐候选决策。原文授权（access_grants /
original_access_requests，PBC-06）、接入注册（agent_whitelist_rules）、审计
（audit_events）等由各自模块的表承载，不在本文件。

枚举值以 String 存储 + 应用层 enum 校验，不使用 DB 原生 enum。

安全：这些表**不保存且不返回** storage_ref / vector_id / Dify 内部 ID
（app_id / workflow_id / dataset_id / api_key）/ 对象存储 URL / 完整原文文件内容。
provider 字段保存的是平台抽象标识（R3 起为 weknora_llm；internal_stub 为已取代的旧桩），
不是 Dify / WeKnora / LLM 内部敏感标识。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AgentCall(Base):
    """Agent 调用记录（一次项目 Q&A 一条）。

    response_text 是 stub provider 生成的确定性占位回答；不含原文文件内容。
    """

    __tablename__ = "agent_calls"
    __table_args__ = (
        Index("ix_agent_calls_caller_created", "caller_user_id", "created_at"),
        Index("ix_agent_calls_project", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    caller_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("projects.id"), nullable=False
    )
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_key: Mapped[str] = mapped_column(String(50), nullable=False)
    # provider：平台抽象标识（R3 为 weknora_llm；internal_stub 为旧桩）。不保存 Dify 敏感标识。
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    capability: Mapped[str] = mapped_column(String(30), nullable=False)
    call_status: Mapped[str] = mapped_column(String(20), nullable=False)
    denied_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AgentGatewayDecision(Base):
    """网关调用级决策主记录（一次调用一条聚合记录）。

    布尔字段为聚合值（是否存在任一可发现/可摘要/可原文的候选），不代表单个候选。
    """

    __tablename__ = "agent_gateway_decisions"
    __table_args__ = (Index("ix_agent_decisions_call", "call_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    call_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agent_calls.id"), nullable=False
    )
    caller_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    decision_status: Mapped[str] = mapped_column(String(20), nullable=False)
    discovery_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    summary_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    original_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allowed_scope: Mapped[str | None] = mapped_column(String(50), nullable=True)
    denied_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    effective_access_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AgentGatewayDecisionItem(Base):
    """候选项三层访问判断明细（每个候选资产一条）。

    是审计与"为什么某条知识未被引用"的解释基础。returned_layer 为该候选的实际
    可达最高层级（null = 连发现层都不可，不得产生 citation）。
    """

    __tablename__ = "agent_gateway_decision_items"
    __table_args__ = (
        Index("ix_agent_items_decision", "decision_id"),
        Index("ix_agent_items_call", "call_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    decision_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agent_gateway_decisions.id"), nullable=False
    )
    call_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agent_calls.id"), nullable=False
    )
    caller_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    target_asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_assets.id"), nullable=False
    )
    # target_chunk_id 是到本系统 knowledge_asset_chunks 的 FK；R1/R2 不落地我们自己的
    # chunk 行（切块在 WeKnora 黑盒内），故恒 NULL。R3 真实 chunk 级召回来自 WeKnora，
    # 其引用存于下方 server-only 的 target_weknora_chunk_ref。
    target_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("knowledge_asset_chunks.id"), nullable=True
    )
    # R3：WeKnora chunk 引用（doc_id#chunk_index 形态），**server-only**，视同 storage_ref，
    # 绝不进任何响应 / 审计 / 日志；仅供后端审计追溯命中片段来源。
    target_weknora_chunk_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    target_project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id"), nullable=True
    )
    target_scope: Mapped[str] = mapped_column(String(20), nullable=False)
    target_confidentiality_level: Mapped[str] = mapped_column(String(2), nullable=False)
    target_ai_access_level: Mapped[str] = mapped_column(String(2), nullable=False)
    discovery_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    summary_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    original_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    returned_layer: Mapped[str | None] = mapped_column(String(20), nullable=True)
    effective_access_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    denied_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AgentCallCitation(Base):
    """Agent 回答引用记录（每条引用一条）。

    关键约束（由服务层保证）：
    - 引用必须来自同一 call 的 allowed decision_items（returned_layer ≠ null）。
    - used_access_layer 不得超过对应 decision_item 的 returned_layer。
    后端审计可经 cited_asset_id / cited_chunk_id 追溯真实资产；对外只返回安全展示字段。
    """

    __tablename__ = "agent_call_citations"
    __table_args__ = (Index("ix_agent_citations_call", "call_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    call_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agent_calls.id"), nullable=False
    )
    decision_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agent_gateway_decision_items.id"), nullable=False
    )
    cited_asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_assets.id"), nullable=False
    )
    cited_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("knowledge_asset_chunks.id"), nullable=True
    )
    # R3：WeKnora chunk 引用，**server-only**（同 target_weknora_chunk_ref），绝不外泄。
    cited_weknora_chunk_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # R3：脱敏后的引用片段（安全，可对外）+ 安全序号 seq（非内部 id，可对外）。
    cited_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    cited_seq: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_access_layer: Mapped[str] = mapped_column(String(20), nullable=False)
    cited_zone: Mapped[str] = mapped_column(String(20), nullable=False)
    citation_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
