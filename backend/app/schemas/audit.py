"""Admin Audit API 的请求 / 响应 schema。

响应按角色做视图级二次脱敏（BE-09 §7.3 / §8）：
- admin 视图只回系统元数据，不回 before/after 快照、不回 L5 资产存在信息（title / 被
  L5 标记时连 target_id 也隐藏），extra 仅保留安全子集。
- boss / 咨询总监视图可回业务治理字段（含快照、title、L5 强审计），但技术敏感标识本就
  不入库，视图层不回填。

无论何视图都不返回服务端内部存储引用 / 完整 token / 对象存储 URL / Dify 内部标识。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class AuditEventOut(BaseModel):
    """单条审计事件（字段按视图档位选择性填充）。"""

    id: uuid.UUID
    log_type: str
    action: str
    actor_user_id: uuid.UUID | None
    actor_name: str | None
    actor_company_role: str | None
    actor_project_role: str | None
    target_type: str | None
    target_id: uuid.UUID | None
    severity: str | None
    is_processed: bool
    processed_by: uuid.UUID | None
    processed_at: datetime | None
    trace_id: str
    denied_reason: str | None
    risk_level: str | None
    created_at: datetime
    # 业务治理视图（boss / 咨询总监）才填充；admin 视图为 None。
    before_snapshot: dict | None = None
    after_snapshot: dict | None = None
    extra: dict | None = None


class AuditListResponse(BaseModel):
    items: list[AuditEventOut]
    total: int
    page: int
    page_size: int
    # 当前响应所用视图档位：admin_metadata / governance。
    view: str


class AuditTraceResponse(BaseModel):
    trace_id: str
    items: list[AuditEventOut]
    view: str


class MarkProcessedResponse(BaseModel):
    event_id: uuid.UUID
    is_processed: bool
    processed_by: uuid.UUID | None
    processed_at: datetime | None

