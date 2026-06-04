"""个人知识写动作 API 的请求 / 响应 schema（PBC-05）。

只暴露**安全治理元数据**：submission/asset/project/review/evidence id + 安全枚举 + 文案。
绝不返回：原文 chunk / 摘要全文 / 文件对象内部引用 / 真实附件 URL / WeKnora id /
token / OAuth state·code / provider 内部标识。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.enums import EvidenceCategory, EvidenceType


class SubmitToProjectRequest(BaseModel):
    """个人知识提交到项目资料区。"""

    target_project_id: uuid.UUID
    note: str | None = None


class ValidationCandidateRequest(BaseModel):
    """内部分享候选 / 客户验证候选的证据登记。

    evidence_type=internal_sharing → 内部分享候选；client_validation → 客户验证候选。
    系统只登记候选证据线索，不证明分享 / 客户验证真实发生。
    """

    target_project_id: uuid.UUID
    evidence_type: EvidenceType
    evidence_category: EvidenceCategory
    description: str | None = None
    # 占位 metadata（不接收真实文件路径 / 下载 URL；服务层拦截敏感字段）。
    attachments: list[dict] | None = None
    note: str | None = None


class ConfirmAssetResponse(BaseModel):
    """本人个人资产确认结果（material → asset，幂等）。"""

    asset_id: uuid.UUID
    zone: str
    status: str
    message: str


class PersonalKnowledgeSubmissionOut(BaseModel):
    """个人知识提交记录安全视图。"""

    submission_id: uuid.UUID
    asset_id: uuid.UUID
    target_project_id: uuid.UUID | None = None
    target_project_name: str | None = None
    submission_type: str
    status: str
    review_task_id: uuid.UUID | None = None
    evidence_id: uuid.UUID | None = None
    created_at: datetime
    # 诚实文案：提交=待审核 / 候选=用户登记线索，系统不自动证明真实发生。
    message: str
    next_action: str
