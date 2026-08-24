"""入库流水线 API 的请求 / 响应 schema。

**绝不包含 source_file_ref / 文件对象内部存储引用 / 真实上传或下载 URL。**
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.bulk_operations import BulkItemResult, BulkOperationResponse, BulkRequestContext
from app.schemas.enums import (
    ConfidentialityLevel,
    KnowledgeScope,
    KnowledgeZone,
)
from app.schemas.naming import NamingConfirmationFields, NamingWarningCode


class IngestUploadRequest(BaseModel):
    file_name: str
    file_mime_type: str
    file_size: int | None = None
    target_scope: str | None = None
    target_project_id: uuid.UUID | None = None


class IngestUploadResponse(BaseModel):
    ingest_task_id: uuid.UUID
    status: str
    # 不返回签名上传地址：固定为 None（上传走平台中转，见 README）。
    upload_url: None = None


class UploadSessionItemResponse(BaseModel):
    id: uuid.UUID
    ordinal: int
    batch_number: int
    file_name: str
    file_size: int
    file_type: str | None
    status: str
    error_code: str | None = None
    error_message: str | None = None
    same_name_warning: bool = False
    retryable: bool = False
    retry_count: int = 0
    last_attempt_at: datetime | None = None
    processing_stage: str | None = None


class UploadSessionResponse(BaseModel):
    id: uuid.UUID
    status: str
    total_files: int
    completed_files: int
    processing_files: int
    waiting_files: int
    failed_files: int
    current_batch_number: int | None
    total_batches: int
    created_at: datetime
    updated_at: datetime
    items: list[UploadSessionItemResponse]


class UploadSessionListResponse(BaseModel):
    items: list[UploadSessionResponse]
    total: int


class UploadClientRejection(BaseModel):
    """A client-side intake failure. The server revalidates safe claims."""

    file_name: str
    file_size: int = 0
    file_type: str | None = None
    error_code: Literal[
        "file_unreadable",
        "file_read_timeout",
        "macos_metadata",
        "unsupported_file_type",
        "file_too_large",
    ]


class IngestTaskStage(str, Enum):
    upload_saved = "upload_saved"
    text_extraction = "text_extraction"
    ocr_queued = "ocr_queued"
    ocr_in_progress = "ocr_in_progress"
    ocr_failed = "ocr_failed"
    canonical_markdown_generation = "canonical_markdown_generation"
    content_generation = "content_generation"
    waiting_generation_config = "waiting_generation_config"
    content_generation_failed = "content_generation_failed"
    awaiting_confirmation = "awaiting_confirmation"
    confirmation = "confirmation"
    indexing_queued = "indexing_queued"
    indexing_in_progress = "indexing_in_progress"
    completed = "completed"
    failed = "failed"
    degraded_complete = "degraded_complete"


class IngestTaskWorkflowStatus(str, Enum):
    processing = "processing"
    action_required = "action_required"
    waiting = "waiting"
    completed = "completed"
    degraded = "degraded"
    failed = "failed"


class IngestTaskNextAction(BaseModel):
    key: str
    route_key: str | None = None
    enabled: bool


class IngestTaskSafeError(BaseModel):
    code: str
    message: str
    recovery_hint: str


class IngestTaskStatusResponse(BaseModel):
    """Permission-filtered task progress without provider or storage internals."""

    task_id: uuid.UUID
    stage: IngestTaskStage
    status: IngestTaskWorkflowStatus
    updated_at: datetime | None
    retryable: bool
    next_action: IngestTaskNextAction | None = None
    error: IngestTaskSafeError | None = None
    result_asset_id: uuid.UUID | None = None
    review_id: uuid.UUID | None = None


class IngestAiResultResponse(BaseModel):
    """AI 建议结果（按调用人权限裁剪）。

    admin 视图：business 字段（suggested_title / suggested_summary）置 None，
    仅保留运营元数据（状态、命名校验、级别、置信度）。
    """

    ingest_task_id: uuid.UUID
    status: str
    suggested_title: str | None = None
    # 三层摘要建议（仅完整视图返回；admin 元数据视图为 None）。
    suggested_one_liner: str | None = None
    suggested_summary: str | None = None  # detailed
    # generated summary only. 未配置/失败降级时保持 None，避免把抽取文本误标成 AI 摘要。
    summary: str | None = None
    summary_status: str | None = None
    generation_model_ref: str | None = None
    generation_error_category: str | None = None
    generation_recovery_hint: str | None = None
    suggested_key_points: list[str] | None = None
    suggested_tags: list[str] | None = None
    suggested_asset_type: str | None = None
    suggested_version: str | None = None
    version_source: (
        Literal["source_filename", "ai_content", "default_needs_confirmation"] | None
    ) = None
    version_confidence: Literal["high", "medium", "low"] | None = None
    version_reason: str | None = None
    suggested_confidentiality_level: str | None = None
    confidentiality_source: Literal["ai_content", "default_needs_confirmation"] | None = None
    confidentiality_confidence: Literal["high", "medium", "low"] | None = None
    confidentiality_reason: str | None = None
    suggested_ai_access_level: str | None = None
    suggested_phase_key: str | None = None
    confidence: float | None = Field(
        default=None,
        deprecated=True,
        description="Deprecated compatibility field; never use for UI or decisions.",
    )
    suggestion_generation_status: str
    suggestion_generation_reason: str
    naming_compliant: bool | None = None
    naming_parsed_fields: dict | None = None
    naming_anomalies: list | None = None
    # 抽取与去重。extraction_status / 错误为运营元数据（两视图均可见）；
    # extracted_text_preview 是业务内容**仅完整视图**返回，admin 元数据视图为 None。
    extraction_status: str | None = None
    extracted_char_count: int | None = None
    ocr_status: str | None = None
    ocr_page_results: list | None = None
    ocr_confidence: float | None = None
    ocr_attempted_at: datetime | None = None
    error_type: str | None = None
    error_message: str | None = None
    is_possible_duplicate: bool = False
    duplicate_of_task_id: uuid.UUID | None = None
    duplicate_of_asset_id: uuid.UUID | None = None
    extracted_text_preview: str | None = None
    # 内容处理所用 provider/model（安全运营元数据，非密钥）+ 状态（llm/degraded）。
    llm_provider: str | None = None
    llm_model: str | None = None
    content_processing_status: str | None = None
    # 入库前置脱敏安全元数据（两视图均可见；仅状态 + 类别计数 + 人读文案，
    # **绝不**返回脱敏前/后正文、脱敏文本 ref、原始文件 ref）。
    # 当前口径：not_applicable（入库建议由受信外部 API 处理，未启用前置脱敏，counts=null）。
    # applied|unchanged|skipped|failed 仅兼容历史数据行。counts: 类别 → 替换数量。
    desensitization_status: str | None = None
    desensitization_counts: dict | None = None
    desensitization_message: str | None = None


class IngestConfirmRequest(BaseModel):
    """入库确认请求。

    枚举字段用 `app.schemas.enums` 的 Enum 做 Pydantic 校验，非法值自动 422；
    数据库仍以 String 存储（写入时取 `.value`）。
    """

    model_config = ConfigDict(extra="forbid")

    title: str
    # 三层摘要（人工校正后）：summary 复用为 detailed；one_liner / key_points 可选。
    one_liner: str | None = None
    summary: str | None = None
    key_points: list[str] = []
    tags: list[str] = []
    target_scope: KnowledgeScope
    target_project_id: uuid.UUID | None = None
    target_zone: KnowledgeZone = KnowledgeZone.material
    confidentiality_level: ConfidentialityLevel
    # PBC-38：可选模型选择（对底座 id 不可逆的 model_ref，绝不接收真实 model_id）。
    # 缺省走平台默认；显式选择仅在首建该 scope 的 KB 时生效，已有 KB 冲突会被锁定拒绝。
    embedding_model_ref: str | None = None
    rerank_model_ref: str | None = None
    # The server recomputes every warning. These codes only record the user's
    # explicit decision to proceed; they cannot suppress a blocking validation.
    acknowledged_naming_warning_codes: list[NamingWarningCode] = Field(
        default_factory=list, max_length=20
    )
    # Project/company canonical naming facts. The final filename is deliberately
    # absent: the backend renders it from the currently published policy.
    naming: NamingConfirmationFields | None = None
    # Exactly one stable governed directory. Never accept a free-form path.
    directory_key: str | None = None


class IngestConfirmResponse(BaseModel):
    task_id: uuid.UUID
    status: str
    result_asset_id: uuid.UUID | None
    review_id: uuid.UUID | None = None
    # WeKnora 解析的安全业务状态（pending/processing/completed/failed/duplicate）；
    # 未启用 WeKnora 时为 None。不暴露任何 kb_id / doc_id。
    parse_status: str | None = None
    # 平台级索引状态：indexed | index_failed | skipped。
    # 资产已确认落库（status=completed），index_failed 表示底座索引失败但资产保留、可重试，
    # 前端据此提示"已提交、索引暂未完成"，不得表现为完全成功且可检索。安全业务状态，无 kb/doc id。
    index_status: str | None = None
    canonical_name: str | None = None


class IngestBulkConfirmItem(BaseModel):
    task_id: uuid.UUID
    # Kept raw so one malformed item produces one safe terminal result instead
    # of rejecting the entire batch at request parsing time.
    confirmation: dict[str, object] | IngestConfirmRequest


class IngestBulkConfirmRequest(BulkRequestContext):
    items: list[IngestBulkConfirmItem] = Field(min_length=1, max_length=500)
    target_scope: KnowledgeScope
    target_project_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def require_one_explicit_destination(self) -> IngestBulkConfirmRequest:
        if len({item.task_id for item in self.items}) != len(self.items):
            raise ValueError("task ids must not contain duplicates")
        if self.target_scope == KnowledgeScope.project and self.target_project_id is None:
            raise ValueError("target_project_id is required for project scope")
        for item in self.items:
            confirmation = (
                item.confirmation.model_dump(mode="json")
                if isinstance(item.confirmation, IngestConfirmRequest)
                else item.confirmation
            )
            if confirmation.get("target_scope") != self.target_scope.value:
                raise ValueError("all items must use the explicit batch target_scope")
            supplied_project = confirmation.get("target_project_id")
            if supplied_project is not None:
                supplied_project = str(supplied_project)
            expected_project = str(self.target_project_id) if self.target_project_id else None
            if supplied_project != expected_project:
                raise ValueError("all items must use the explicit batch target_project_id")
        return self


class IngestBulkConfirmItemResult(BulkItemResult):
    """Safe confirmation result; the asset link exists only after creation succeeded."""

    result_asset_id: uuid.UUID | None = None
    index_status: str | None = None


class IngestBulkConfirmResponse(BulkOperationResponse):
    # Pydantic supports this response-schema narrowing; mypy's invariant list
    # rule cannot express that the API always returns the extended item shape.
    items: list[IngestBulkConfirmItemResult]  # type: ignore[assignment]


class IngestParseRefreshResponse(BaseModel):
    """解析状态对账响应（只回安全业务状态，绝不含 weknora_doc_id / kb_id）。"""

    task_id: uuid.UUID
    result_asset_id: uuid.UUID | None
    parse_status: str | None


class AdminIngestItem(BaseModel):
    """运营视图：仅运营元数据，不含业务原文与任何服务端内部存储引用。"""

    id: uuid.UUID
    source: str
    source_file_name: str
    status: str
    target_scope: str | None
    confidentiality_level: str | None
    ai_access_level: str | None
    confidence: float | None = Field(
        default=None,
        deprecated=True,
        description="Deprecated compatibility field; never use for UI or decisions.",
    )
    suggestion_generation_status: str
    suggestion_generation_reason: str
    naming_compliant: bool | None
    # 抽取状态为运营元数据（不含抽取全文）。
    extraction_status: str | None = None
    error_type: str | None
    error_message: str | None
    result_asset_id: uuid.UUID | None
    created_at: datetime | None


class AdminIngestListResponse(BaseModel):
    items: list[AdminIngestItem]
    total: int


class PendingIngestItem(BaseModel):
    """业务侧待确认任务视图：仅校正 / 运营所需安全元数据。

    **绝不包含**任何内部存储引用 / WeCom 文件标识 / 下载地址 / 凭证 token /
    WeKnora 内部 id / 原文全文 / 抽取全文。
    """

    id: uuid.UUID
    source: str
    status: str
    source_file_name: str
    target_scope: str | None = None
    target_project_id: uuid.UUID | None = None
    # 文件形成日期建议（YYYY-MM-DD；客户端文件修改时间 / 文件名兜底），人工可改可清空。
    suggested_formed_on: str | None = None
    # Server-derived UX capability. This never replaces confirmation endpoint
    # authorization or validation.
    can_batch_confirm: bool = False
    can_batch_reject: bool = False
    # 抽取 / 错误为运营元数据（不含抽取全文）。
    extraction_status: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    processing_stage: str | None = None
    retryable: bool = False
    retry_count: int = 0
    # 允许前端在列表预览 / 进入校正前展示的 AI 建议元数据。
    suggested_title: str | None = None
    suggested_one_liner: str | None = None
    suggested_version: str | None = None
    version_source: (
        Literal["source_filename", "ai_content", "default_needs_confirmation"] | None
    ) = None
    version_confidence: Literal["high", "medium", "low"] | None = None
    version_reason: str | None = None
    suggested_confidentiality_level: str | None = None
    confidentiality_source: Literal["ai_content", "default_needs_confirmation"] | None = None
    confidentiality_confidence: Literal["high", "medium", "low"] | None = None
    confidentiality_reason: str | None = None
    naming_parsed_fields: dict | None = None
    confidence: float | None = Field(
        default=None,
        deprecated=True,
        description="Deprecated compatibility field; never use for UI or decisions.",
    )
    suggestion_generation_status: str
    suggestion_generation_reason: str
    result_asset_id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PendingIngestListResponse(BaseModel):
    items: list[PendingIngestItem]
    total: int
