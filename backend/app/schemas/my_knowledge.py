"""个人知识写动作 API 的请求 / 响应 schema。

只暴露**安全治理元数据**：submission/asset/project/review/evidence id + 安全枚举 + 文案。
绝不返回：原文 chunk / 摘要全文 / 文件对象内部引用 / 真实附件 URL / WeKnora id /
token / OAuth state·code / provider 内部标识。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.enums import (
    AssetType,
    ConfidentialityLevel,
    EvidenceCategory,
    EvidenceType,
    PersonalKnowledgeState,
)
from app.schemas.knowledge import KnowledgeListItemOut
from app.schemas.naming import NamingConfirmationFields


class PersonalProjectSubmissionSummary(BaseModel):
    """项目提交的安全摘要，不含任何内部或项目 UUID。"""

    status: str
    target_project_name: str | None = None
    submitted_at: datetime
    resolved_at: datetime | None = None


class PersonalEvidenceSummary(BaseModel):
    """候选证据安全聚合，不返回正文、附件或内部 ID。"""

    registered_count: int = 0
    latest_status: str | None = None
    updated_at: datetime | None = None


class PersonalKnowledgeItemOut(KnowledgeListItemOut):
    created_at: datetime
    personal_state: PersonalKnowledgeState
    personal_state_label: str
    project_submission: PersonalProjectSubmissionSummary | None = None
    evidence_summary: PersonalEvidenceSummary | None = None


class PersonalKnowledgeSummary(BaseModel):
    total_assets: int
    awaiting_confirmation: int
    pending_project_review: int
    active_in_project: int
    created_this_month: int


class PersonalKnowledgeListResponse(BaseModel):
    items: list[PersonalKnowledgeItemOut]
    total: int
    page: int
    page_size: int
    has_next: bool
    summary: PersonalKnowledgeSummary


class PersonalKnowledgeUpdateRequest(BaseModel):
    """仅允许修改个人资料的安全元数据。"""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=500)
    asset_type: AssetType | None = None
    tags: list[str] | None = Field(default=None, max_length=20)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        clean = value.strip()
        if not clean:
            raise ValueError("标题不能为空")
        return clean

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        clean: list[str] = []
        for tag in value:
            item = tag.strip()
            if not item or len(item) > 100:
                raise ValueError("标签必须为 1 至 100 个字符")
            if item not in clean:
                clean.append(item)
        return clean

    @model_validator(mode="after")
    def require_change(self) -> PersonalKnowledgeUpdateRequest:
        if self.title is None and self.asset_type is None and self.tags is None:
            raise ValueError("至少提供一个可修改字段")
        return self


class SubmitToProjectRequest(BaseModel):
    """个人知识提交到项目资料区。"""

    target_project_id: uuid.UUID
    confidentiality_level: ConfidentialityLevel
    naming: NamingConfirmationFields
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
