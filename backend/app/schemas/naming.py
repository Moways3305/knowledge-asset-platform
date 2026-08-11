"""Safe contracts for naming policy governance and confirmation preview."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.enums import AssetType, ConfidentialityLevel, KnowledgeScope

_PROJECT_CODE = re.compile(r"^[A-Z][A-Z0-9-]{1,19}$")
_VERSION = re.compile(r"^V[1-9]\d*(?:\.\d+)*$")
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_text(value: str, *, label: str, maximum: int) -> str:
    normalized = " ".join(value.strip().split())
    if not normalized:
        raise ValueError(f"{label}不能为空")
    if len(normalized) > maximum:
        raise ValueError(f"{label}不能超过 {maximum} 个字符")
    if _UNSAFE.search(normalized) or normalized.endswith((".", " ")):
        raise ValueError(f"{label}包含非法文件名字符")
    return normalized


class ProjectCodeConfig(BaseModel):
    project_id: uuid.UUID
    code: str
    enabled: bool = True
    default_confidentiality: ConfidentialityLevel = ConfidentialityLevel.L2
    client_aliases: list[str] = Field(default_factory=list, max_length=20)
    client_aliases_enabled: bool = True

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not _PROJECT_CODE.fullmatch(normalized):
            raise ValueError("项目代码须为 2-20 位大写字母、数字或短横线，且以字母开头")
        return normalized

    @field_validator("client_aliases")
    @classmethod
    def validate_client_aliases(cls, values: list[str]) -> list[str]:
        normalized = [_safe_text(value, label="客户命名别名", maximum=80) for value in values]
        if any(len(value) < 2 for value in normalized):
            raise ValueError("客户命名别名不能少于 2 个字符")
        folded = [value.casefold() for value in normalized]
        if len(folded) != len(set(folded)):
            raise ValueError("同一项目的客户命名别名不能重复")
        return normalized


class NamingCategoryConfig(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    scope: Literal["project", "company"]
    primary: str
    secondary: str
    prefix: str
    asset_type: AssetType | None = None
    description: str | None = None
    default_confidentiality: ConfidentialityLevel = ConfidentialityLevel.L2
    enabled: bool = True
    sort_order: int = Field(default=100, ge=0, le=10000)

    @field_validator("primary")
    @classmethod
    def validate_primary(cls, value: str) -> str:
        return _safe_text(value, label="一级类", maximum=40)

    @field_validator("secondary")
    @classmethod
    def validate_secondary(cls, value: str) -> str:
        return _safe_text(value, label="二级类", maximum=40)

    @field_validator("prefix")
    @classmethod
    def validate_prefix(cls, value: str) -> str:
        return _safe_text(value, label="前缀", maximum=80)

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return _safe_text(value, label="类别说明", maximum=300)


class NamingRuleConfig(BaseModel):
    schema_version: int = 2
    enforced: bool = True
    project_codes: list[ProjectCodeConfig] = Field(default_factory=list)
    categories: list[NamingCategoryConfig] = Field(default_factory=list)
    migration_missing_asset_type_category_ids: list[uuid.UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_business_keys(self) -> NamingRuleConfig:
        project_ids = [item.project_id for item in self.project_codes]
        codes = [item.code for item in self.project_codes]
        category_ids = [item.id for item in self.categories]
        if len(project_ids) != len(set(project_ids)):
            raise ValueError("同一项目只能配置一个项目代码")
        if len(codes) != len(set(codes)):
            raise ValueError("项目代码必须唯一")
        if len(category_ids) != len(set(category_ids)):
            raise ValueError("目录类别标识不能重复")
        return self


class NamingRuleRevisionOut(BaseModel):
    version: int
    status: str
    base_published_version: int
    config: NamingRuleConfig
    updated_at: datetime
    published_at: datetime | None = None


class NamingRuleCenterOut(BaseModel):
    published: NamingRuleRevisionOut
    draft: NamingRuleRevisionOut
    projects: list[dict]


class NamingDraftUpdateRequest(BaseModel):
    expected_base_version: int
    config: NamingRuleConfig


class NamingPublishRequest(BaseModel):
    expected_base_version: int


class NamingConfirmationFields(BaseModel):
    category_id: uuid.UUID
    subject: str
    formed_on: date
    version: str
    applicable_to: str | None = None

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, value: str) -> str:
        return _safe_text(value, label="主题", maximum=120)

    @field_validator("applicable_to")
    @classmethod
    def validate_applicable_to(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _safe_text(value, label="适用对象", maximum=60)

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not _VERSION.fullmatch(normalized):
            raise ValueError("版本须为 V 加正整数序列，例如 V1 或 V1.1")
        return normalized


class NamingPreviewRequest(BaseModel):
    target_scope: KnowledgeScope
    target_project_id: uuid.UUID | None = None
    confidentiality_level: ConfidentialityLevel
    naming: NamingConfirmationFields | None = None


NamingWarningCode = Literal[
    "project_subject_business_name",
    "exact_duplicate",
    "suspected_duplicate",
    "version_source_unreliable",
    "confidentiality_source_unreliable",
    "historical_naming_noncompliant",
    "ai_suggestion_uncertain",
]


class NamingDuplicateNotice(BaseModel):
    code: NamingWarningCode
    kind: Literal["exact", "suspected", "semantic", "advisory"]
    message: str


class NamingPreviewResponse(BaseModel):
    required: bool
    canonical_name: str | None
    rule_version: int | None
    fields: dict | None
    notices: list[NamingDuplicateNotice] = Field(default_factory=list)
    message: str | None = None
    suggested_version: str = "V1"
    version_source: Literal["source_filename", "ai_content", "default_needs_confirmation"] = (
        "default_needs_confirmation"
    )
    version_confidence: Literal["high", "medium", "low"] = "low"
    version_reason: str = "未能可靠判断版本，已使用规则默认值"
    suggested_confidentiality_level: ConfidentialityLevel = ConfidentialityLevel.L2
    confidentiality_source: Literal["ai_content", "default_needs_confirmation"] = (
        "default_needs_confirmation"
    )
    confidentiality_confidence: Literal["high", "medium", "low"] = "low"
    confidentiality_reason: str = "AI 未能可靠判断内容密级，已使用规则默认值"


class BatchNamingConfirmationFields(BaseModel):
    """Field-shaped carrier that keeps business validation item-scoped."""

    model_config = ConfigDict(extra="forbid")

    category_id: uuid.UUID | str | None = None
    subject: str | None = None
    formed_on: date | str | None = None
    version: str | None = None
    applicable_to: str | None = None


class BatchNamingPreviewItemRequest(BaseModel):
    task_id: uuid.UUID
    confidentiality_level: ConfidentialityLevel
    naming: BatchNamingConfirmationFields | None = None


class BatchNamingPreviewRequest(BaseModel):
    items: list[BatchNamingPreviewItemRequest] = Field(min_length=1, max_length=500)
    target_scope: KnowledgeScope
    target_project_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def require_explicit_destination(self) -> BatchNamingPreviewRequest:
        if len({item.task_id for item in self.items}) != len(self.items):
            raise ValueError("task ids must not contain duplicates")
        if self.target_scope == KnowledgeScope.project and self.target_project_id is None:
            raise ValueError("target_project_id is required for project scope")
        if self.target_scope == KnowledgeScope.personal:
            raise ValueError("personal scope does not require governed naming preview")
        return self


class BatchNamingPreviewItemResponse(BaseModel):
    task_id: uuid.UUID
    submittable: bool
    canonical_name: str | None = None
    rule_version: int | None = None
    fields: dict | None = None
    notices: list[NamingDuplicateNotice] = Field(default_factory=list)
    error_code: str | None = None
    message: str | None = None
    suggested_version: str = "V1"
    version_source: Literal["source_filename", "ai_content", "default_needs_confirmation"] = (
        "default_needs_confirmation"
    )
    version_confidence: Literal["high", "medium", "low"] = "low"
    version_reason: str = "未能可靠判断版本，已使用规则默认值"
    suggested_confidentiality_level: ConfidentialityLevel = ConfidentialityLevel.L2
    confidentiality_source: Literal["ai_content", "default_needs_confirmation"] = (
        "default_needs_confirmation"
    )
    confidentiality_confidence: Literal["high", "medium", "low"] = "low"
    confidentiality_reason: str = "AI 未能可靠判断内容密级，已使用规则默认值"


class BatchNamingPreviewResponse(BaseModel):
    items: list[BatchNamingPreviewItemResponse]


class NamingOptionItem(BaseModel):
    id: uuid.UUID
    scope: Literal["project", "company"]
    primary: str
    secondary: str
    prefix: str
    asset_type: AssetType
    description: str | None = None
    default_confidentiality: ConfidentialityLevel
    enabled: bool = True
    sort_order: int


class NamingOptionsResponse(BaseModel):
    required: bool
    rule_version: int | None
    categories: list[NamingOptionItem] = Field(default_factory=list)
    default_confidentiality: ConfidentialityLevel | None = None
    message: str | None = None


CategorySource = Literal["ai_content", "rule_only_option", "needs_manual", "manual"]
CategoryConfidence = Literal["high", "medium", "low"]


class CategoryClassificationBatchRequest(BaseModel):
    task_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    target_scope: KnowledgeScope
    target_project_id: uuid.UUID | None = None
    retry: bool = False

    @model_validator(mode="after")
    def require_explicit_destination(self) -> CategoryClassificationBatchRequest:
        if len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("task ids must not contain duplicates")
        if self.target_scope == KnowledgeScope.personal:
            raise ValueError("personal scope does not use governed category classification")
        if self.target_scope == KnowledgeScope.project and self.target_project_id is None:
            raise ValueError("target_project_id is required for project scope")
        return self


class CategoryClassificationItemResponse(BaseModel):
    task_id: uuid.UUID
    suggested_category_id: uuid.UUID | None = None
    category_source: CategorySource
    category_confidence: CategoryConfidence
    category_reason: str
    candidate_rule_revision: int | None = None
    status: Literal["classified", "needs_manual", "failed", "unchanged"]
    retryable: bool = False


class CategoryClassificationBatchResponse(BaseModel):
    target_label: str
    candidate_rule_revision: int | None = None
    candidate_count: int
    items: list[CategoryClassificationItemResponse]


class ManualCategorySelectionRequest(BaseModel):
    target_scope: KnowledgeScope
    target_project_id: uuid.UUID | None = None
    category_id: uuid.UUID

    @model_validator(mode="after")
    def require_project(self) -> ManualCategorySelectionRequest:
        if self.target_scope == KnowledgeScope.personal:
            raise ValueError("personal scope does not use governed category selection")
        if self.target_scope == KnowledgeScope.project and self.target_project_id is None:
            raise ValueError("target_project_id is required for project scope")
        return self
