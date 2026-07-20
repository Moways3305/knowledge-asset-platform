"""审核流 API 的请求 / 响应 schema。

枚举字段用 `app.schemas.enums` 的 Enum 做 Pydantic 校验，非法值 422；DB 仍 String 存储。
响应不含任何服务端内部存储引用或真实附件下载 URL。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.enums import EvidenceCategory, EvidenceType


class EvidenceCreateRequest(BaseModel):
    evidence_type: EvidenceType
    evidence_category: EvidenceCategory
    description: str | None = None
    # 占位 metadata（如 {"name": "...", "note": "..."}）；不接收真实文件路径/下载 URL。
    # 真实 URL / 路径 / 内部引用 / 凭证的拦截在 services/review.py（避免 schema 文件出现敏感字段名）。
    attachments: list[dict] | None = None


class EvidenceOut(BaseModel):
    id: uuid.UUID
    evidence_type: str
    evidence_category: str
    description: str | None
    submitted_by: uuid.UUID
    created_at: datetime | None


class ReviewListItem(BaseModel):
    id: uuid.UUID
    review_type: str
    trigger_source: str
    status: str
    target_asset_id: uuid.UUID | None
    asset_title: str | None
    target_scope: str | None
    target_project_id: uuid.UUID | None
    project_name: str | None
    submitted_by: uuid.UUID | None
    reviewer_user_id: uuid.UUID | None
    evidence_count: int
    can_decide: bool = False
    can_withdraw: bool = False
    general_manager_confirmation_status: str | None = None
    consulting_director_confirmation_status: str | None = None
    review_comment: str | None
    reviewed_at: datetime | None
    created_at: datetime | None


class ReviewListResponse(BaseModel):
    items: list[ReviewListItem]
    total: int


class ReviewDetail(ReviewListItem):
    evidences: list[EvidenceOut]


class ReviewActionRequest(BaseModel):
    review_comment: str | None = None


class ReviewRejectRequest(BaseModel):
    review_comment: str


class ReviewActionResponse(BaseModel):
    review_id: uuid.UUID
    status: str
    target_asset_id: uuid.UUID | None
    asset_zone: str | None
    index_status: str | None = None


class ReviewWithdrawRequest(BaseModel):
    review_comment: str | None = None
