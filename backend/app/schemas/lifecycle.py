"""知识生命周期动作 API 的请求 / 响应 schema。

生命周期变更是治理流程，不是物理删除；request 类动作只产生预警/候选，confirm
类动作才人工确认状态变更。响应均为安全元数据，不含业务原文 / 内部存储标识。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


# ---- 请求 ----
class ArchiveRequestBody(BaseModel):
    reason: str
    candidate_source: str | None = None
    expected_archive_at: datetime | None = None
    idempotency_key: str | None = None


class ArchiveConfirmBody(BaseModel):
    reason: str
    review_task_id: uuid.UUID | None = None
    idempotency_key: str | None = None


class ReenableRequestBody(BaseModel):
    reason: str
    target_status: str | None = None
    idempotency_key: str | None = None


class ReenableConfirmBody(BaseModel):
    reason: str
    target_status: str
    review_task_id: uuid.UUID | None = None
    idempotency_key: str | None = None


# ---- 响应 ----
class LifecycleActionResponse(BaseModel):
    """request 类动作（archive-request / reenable-request）响应。"""

    lifecycle_event_id: uuid.UUID
    review_task_id: uuid.UUID | None = None
    status: str
    trace_id: str


class ArchiveConfirmResponse(BaseModel):
    asset_id: uuid.UUID
    asset_status: str
    archived_at: datetime | None
    archive_reason: str | None
    trace_id: str


class ReenableConfirmResponse(BaseModel):
    asset_id: uuid.UUID
    asset_status: str
    lifecycle_event_id: uuid.UUID
    trace_id: str


class LifecycleEventOut(BaseModel):
    event_id: uuid.UUID
    event_type: str
    old_status: str | None
    new_status: str | None
    reason: str | None
    actor_display: str | None
    created_at: datetime
    trace_id: str | None


class LifecycleEventsResponse(BaseModel):
    items: list[LifecycleEventOut]

