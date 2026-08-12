"""原文访问申请与授权 API 的请求 / 响应 schema。

只暴露安全治理元数据：request/grant id、asset id/title/scope/project、安全显示名、
status/时间/expires_at、reason/review_note。绝不返回原文 / 对象存储引用 / 外部系统内部 id /
token / URL / WeKnora id / provider 内部标识。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class CreateRequestBody(BaseModel):
    reason: str | None = None


class ReviewBody(BaseModel):
    note: str | None = None


class RevokeBody(BaseModel):
    reason: str | None = None


class OriginalAccessRequestOut(BaseModel):
    request_id: uuid.UUID
    asset_id: uuid.UUID
    asset_title: str | None = None
    scope: str | None = None
    project_id: uuid.UUID | None = None
    requester_user_id: uuid.UUID
    requester_name: str | None = None
    reviewer_user_id: uuid.UUID | None = None
    reviewer_name: str | None = None
    requested_access_layer: str
    status: str
    reason: str | None = None
    review_note: str | None = None
    created_at: datetime
    reviewed_at: datetime | None = None
    grant_status: str | None = None
    grant_expires_at: datetime | None = None
    grant_revoked_at: datetime | None = None
    can_reapply: bool = False


class AccessGrantOut(BaseModel):
    grant_id: uuid.UUID
    asset_id: uuid.UUID
    grantee_user_id: uuid.UUID
    grant_type: str
    source_request_id: uuid.UUID | None = None
    status: str
    expires_at: datetime | None = None
    created_at: datetime
    revoked_at: datetime | None = None


class CreateRequestResponse(BaseModel):
    """申请 / 审批 / 拒绝的统一响应。status 见各动作；request/grant 视情况非空。"""

    status: str  # created / pending_exists / already_granted / approved / rejected
    message: str
    request: OriginalAccessRequestOut | None = None
    grant: AccessGrantOut | None = None


class RequestsListResponse(BaseModel):
    items: list[OriginalAccessRequestOut]
    total: int
