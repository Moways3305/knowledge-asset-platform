"""Knowledge 读 API 的响应 schema。

字段使用 snake_case；前端 ViewModel 适配由前端完成。
**绝不包含文件对象的内部存储引用、原文内容、真实 token/URL 等内部/敏感字段。**
（内部存储引用字段名见数据模型，禁止进入任何响应 schema。）
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class AccessInfoOut(BaseModel):
    """调用人对某资产的三层权限状态（由权限服务决策得到）。"""

    discovery: bool
    summary: bool
    original: bool
    effective_source: str
    can_request_original: bool = False
    # 资产来自调用人的其他项目；可见摘要不代表拥有项目空间成员权限。
    cross_project_summary: bool = False
    # 以下两项由 真实 access_info 驱动：existing_request_status 反映本人 pending 原文申请，
    # existing_grant_expires_at 反映 active access_grant 过期时间；无申请 / 无授权时为 None。
    existing_request_status: str | None = None
    existing_grant_expires_at: datetime | None = None
    # 调用人是否有权对该资产执行受控删除 / 撤下（后端权威，前端据此显示按钮）。
    can_delete: bool = False
    # 生命周期治理权限独立于删除权限；项目维护人可治理但不一定可删除。
    can_manage_lifecycle: bool = False
    # 调用人是否有权对该资产重试底座索引（仅在可重试状态 + 有业务管理权时为 True）。
    can_retry_index: bool = False


class KnowledgeListItemOut(BaseModel):
    """知识列表条目。summary_text 已按权限/保密级别过滤（L3/L4 为脱敏/安全摘要）。"""

    id: uuid.UUID
    title: str
    canonical_name: str | None = None
    scope: str
    zone: str
    asset_type: str
    confidentiality_level: str
    ai_access_level: str
    asset_status: str
    visibility: str
    tags: list[str]
    summary_text: str | None
    project_name: str | None
    lifecycle_phase: str | None
    # confidence 当前未在 knowledge_assets 落地（见 差异），固定 None。
    confidence: float | None = None
    last_called_at: datetime | None
    updated_at: datetime | None
    access_info: AccessInfoOut
    # 平台级底座索引安全状态（不含任何 kb_id / doc_id / 内部存储引用）。
    # index_status: not_indexed | indexing | indexed | index_failed | skipped。
    index_status: str | None = None
    weknora_parse_status: str | None = None
    index_error_message: str | None = None
    indexed_at: datetime | None = None
    directory_key: str | None = None
    directory_path: str | None = None


class KnowledgeSortField(str, Enum):
    updated_at = "updated_at"
    created_at = "created_at"
    title_ = "title"
    confidentiality_level = "confidentiality_level"
    asset_status = "asset_status"


class SortDirection(str, Enum):
    asc = "asc"
    desc = "desc"


class KnowledgeItemsResponse(BaseModel):
    items: list[KnowledgeListItemOut]
    total: int


class KnowledgeListResponse(KnowledgeItemsResponse):
    page: int = 1
    page_size: int = 50
    has_next: bool = False


class MaintainerOut(BaseModel):
    id: uuid.UUID
    name: str


class SummaryOut(BaseModel):
    """详情摘要对象。

    按权限过滤；L3/L4 的 one_liner / detailed 分别使用短版与完整版安全脱敏文本，
    且不暴露 key_points。
    """

    one_liner: str | None = None
    detailed: str | None = None
    key_points: list[str] = []


class CurrentVersionOut(BaseModel):
    id: uuid.UUID
    version_no: str
    version_status: str
    display_version: str | None = None


class KnowledgeDetailOut(BaseModel):
    id: uuid.UUID
    title: str
    canonical_name: str | None = None
    scope: str
    zone: str
    asset_type: str
    confidentiality_level: str
    ai_access_level: str
    asset_status: str
    visibility: str
    tags: list[str]
    project_id: uuid.UUID | None
    project_name: str | None
    lifecycle_phase: str | None
    maintainer: MaintainerOut | None
    maintainer_name: str | None = None
    category_path: str | None = None
    safe_version: str | None = None
    retrieval_available: bool | None = None
    qa_available: bool | None = None
    confidence: float | None = None
    last_called_at: datetime | None
    updated_at: datetime | None
    archived_at: datetime | None
    archive_reason: str | None
    # summary 仅在 summary 层允许时返回；original 内容不随详情返回（走 Preview API）。
    summary: SummaryOut | None
    current_version: CurrentVersionOut | None
    canonical_markdown_status: str | None  # generated | not_generated；跨项目摘要投影为 None
    access_info: AccessInfoOut
    # 平台级底座索引安全状态（无 kb_id / doc_id / 内部存储引用）。
    index_status: str | None = None
    weknora_parse_status: str | None = None
    index_error_code: str | None = None
    index_error_message: str | None = None
    indexed_at: datetime | None = None
    directory_key: str | None = None
    directory_path: str | None = None


class DirectoryOut(BaseModel):
    directory_key: str
    name: str
    description: str | None = None
    scope: str
    display_path: str
    parent_key: str | None = None
    project_id: uuid.UUID | None = None
    project_name: str | None = None


class DirectoryListResponse(BaseModel):
    items: list[DirectoryOut]


class KnowledgeDeleteRequest(BaseModel):
    """受控删除 / 撤下请求。reason 为安全删除说明（误上传 / 重复等），非敏感。"""

    reason: str | None = None


class KnowledgeDeleteResponse(BaseModel):
    """删除响应：仅安全状态字段，绝不含原文 / 内部存储引用 / WeKnora id。"""

    asset_id: uuid.UUID
    asset_status: str
    deleted_at: datetime | None
    trace_id: str | None = None


class RetryIndexRequest(BaseModel):
    """底座索引重试请求（PBC-38，可选）。

    只接收对底座 id 不可逆的 model_ref，绝不接收真实 model_id。缺省沿用该 KB 已绑定模型；
    显式传入与已绑定 embedding 不同的 model_ref 会切换知识库嵌入模型并更新绑定；
    切换后存量文档需重新解析以完成重新向量化。
    """

    embedding_model_ref: str | None = None
    rerank_model_ref: str | None = None


class RetryIndexResponse(BaseModel):
    """底座索引重试响应：仅安全索引状态，绝不含 kb_id / doc_id / 内部存储引用。"""

    asset_id: uuid.UUID
    index_status: str  # indexed | index_failed | skipped
    weknora_parse_status: str | None = None
    index_error_code: str | None = None
    index_error_message: str | None = None
    trace_id: str | None = None
