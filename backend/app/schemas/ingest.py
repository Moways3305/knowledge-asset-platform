"""入库流水线 API 的请求 / 响应 schema。

**绝不包含 source_file_ref / 文件对象内部存储引用 / 真实上传或下载 URL。**
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.enums import (
    AiAccessLevel,
    AssetType,
    ConfidentialityLevel,
    KnowledgeScope,
    KnowledgeZone,
    Visibility,
)


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
    suggested_key_points: list[str] | None = None
    suggested_tags: list[str] | None = None
    suggested_asset_type: str | None = None
    suggested_confidentiality_level: str | None = None
    suggested_ai_access_level: str | None = None
    suggested_phase_key: str | None = None
    confidence: float | None = None
    naming_compliant: bool | None = None
    naming_parsed_fields: dict | None = None
    naming_anomalies: list | None = None
    # 抽取与去重。extraction_status / 错误为运营元数据（两视图均可见）；
    # extracted_text_preview 是业务内容**仅完整视图**返回，admin 元数据视图为 None。
    extraction_status: str | None = None
    extracted_char_count: int | None = None
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

    title: str
    # 三层摘要（人工校正后）：summary 复用为 detailed；one_liner / key_points 可选。
    one_liner: str | None = None
    summary: str | None = None
    key_points: list[str] = []
    tags: list[str] = []
    target_scope: KnowledgeScope
    target_project_id: uuid.UUID | None = None
    target_zone: KnowledgeZone = KnowledgeZone.material
    asset_type: AssetType
    visibility: Visibility = Visibility.project_only
    confidentiality_level: ConfidentialityLevel
    ai_access_level: AiAccessLevel
    lifecycle_phase_key: str | None = None


class IngestConfirmResponse(BaseModel):
    task_id: uuid.UUID
    status: str
    result_asset_id: uuid.UUID
    # WeKnora 解析的安全业务状态（pending/processing/completed/failed/duplicate）；
    # 未启用 WeKnora 时为 None。不暴露任何 kb_id / doc_id。
    parse_status: str | None = None
    # 平台级索引状态：indexed | index_failed | skipped。
    # 资产已确认落库（status=completed），index_failed 表示底座索引失败但资产保留、可重试，
    # 前端据此提示"已提交、索引暂未完成"，不得表现为完全成功且可检索。安全业务状态，无 kb/doc id。
    index_status: str | None = None


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
    confidence: float | None
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
    # 抽取 / 错误为运营元数据（不含抽取全文）。
    extraction_status: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    # 允许前端在列表预览 / 进入校正前展示的 AI 建议元数据。
    suggested_title: str | None = None
    suggested_one_liner: str | None = None
    naming_parsed_fields: dict | None = None
    confidence: float | None = None
    result_asset_id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PendingIngestListResponse(BaseModel):
    items: list[PendingIngestItem]
    total: int
