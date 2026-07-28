"""索引批量运维 API 的请求 / 响应 schema。

**绝不包含** WeKnora kb/doc id、storage/source ref、下载 URL、token/cookie/api_key、
模型 id、原文或文件名、上游原始错误 message。只承载安全筛选条件与作业统计。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

# 批量 retry-index 允许处理的 index_status（绝不含 indexed）。
RETRYABLE_STATUSES = ("index_failed", "skipped", "not_indexed")
# reparse 允许处理的 weknora_parse_status。
REPARSABLE_PARSE_STATUSES = ("failed", "pending", "processing")
_SCOPES = ("personal", "project", "company", "all")
MAX_LIMIT = 200


class IndexingRetryRequest(BaseModel):
    """批量 retry-index 请求。statuses 默认仅 index_failed；非法值在 service 过滤。"""

    scope: str = "all"
    project_id: uuid.UUID | None = None
    statuses: list[str] = Field(default_factory=lambda: ["index_failed"])
    limit: int = 100


class IndexingReparseRequest(BaseModel):
    """显式 reparse 请求（针对已进底座但解析异常的资产）。"""

    scope: str = "all"
    project_id: uuid.UUID | None = None
    parse_statuses: list[str] = Field(default_factory=lambda: ["failed", "pending"])
    limit: int = 100


class IndexingJobSummary(BaseModel):
    """索引运维作业安全摘要（无标题 / 无原文 / 无内部 id）。"""

    job_id: uuid.UUID
    operation_type: str  # retry_index | reparse
    status: str  # queued | running | completed | completed_with_errors | failed
    # 安全筛选条件回显（scope / project_id / statuses / limit）。
    scope_filter: dict | None = None
    requested_by_name: str | None = None
    requested_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    total_count: int = 0
    success_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    # 安全目录 code + 安全文案（无上游原始 message / 内部 id）。
    error_code: str | None = None
    error_message: str | None = None
    trace_id: str | None = None


class IndexingJobListResponse(BaseModel):
    items: list[IndexingJobSummary]
    total: int


class IndexingHealthTrendPoint(BaseModel):
    observed_at: datetime
    index_failed: int
    indexing: int
    not_indexed: int
    skipped: int
    parse_pending: int
    parse_processing: int
    parse_failed: int = 0
    kb_init_failed: int
    completed_jobs: int
    failed_jobs: int
    queued_jobs: int
    oldest_queued_seconds: int | None


class RuntimeHealth(BaseModel):
    status: str  # healthy | stale | unknown
    last_heartbeat_at: datetime | None
    message: str


class QueueHealth(BaseModel):
    status: str  # healthy | degraded | unknown
    queued_count: int
    oldest_queued_seconds: int | None
    message: str


class IndexingHealthResponse(BaseModel):
    generated_at: datetime
    window_hours: int
    insufficient_data: bool
    message: str
    queue: QueueHealth
    worker: RuntimeHealth
    beat: RuntimeHealth
    trend_points: list[IndexingHealthTrendPoint]
