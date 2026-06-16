"""Knowledge 运营洞察 API 的响应 schema。

只承载**安全聚合统计 + 安全提示**：绝不含 WeKnora kb/doc id、storage/source ref、
下载 URL、token/cookie/api_key、provider 内部 id、文件名、原文 / chunk 原文。
drilldown item 最多 asset_id + safe scope + status + safe message + updated_at；
标题是否返回沿用权限边界（纯 admin title_visible=false）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class InsightCard(BaseModel):
    key: str
    label: str
    count: int
    severity: str  # info | warning | error
    action_hint: str | None = None


class InsightJobItem(BaseModel):
    """最近索引运维作业安全摘要（无标题 / 原文 / WeKnora id）。"""

    job_id: uuid.UUID
    operation_type: str
    status: str
    total_count: int
    success_count: int
    failed_count: int
    skipped_count: int
    requested_at: datetime | None = None
    finished_at: datetime | None = None


class IndexingInsights(BaseModel):
    index_failed: int = 0
    skipped: int = 0
    not_indexed: int = 0
    parse_failed: int = 0
    parse_pending: int = 0
    parse_processing: int = 0
    kb_init_failed: int = 0
    recent_jobs: list[InsightJobItem] = []


class AccessInsights(BaseModel):
    pending_original_requests: int = 0
    overdue_original_requests: int = 0
    recent_auto_approved: int = 0
    # 超时自动审批规则是否启用（access_request_timeout_hours）；未启用时 overdue 仅按窗口口径。
    timeout_enabled: bool = False


class LifecycleInsights(BaseModel):
    archive_candidates: int = 0
    archive_warnings: int = 0
    needs_update: int = 0
    reuse_upgrade_candidates: int = 0


class Recommendation(BaseModel):
    key: str
    severity: str  # info | warning | error
    message: str
    target: str | None = None


class InsightRecentItem(BaseModel):
    """drilldown 条目：仅安全字段。title 在 title_visible=false 时为 None。"""

    asset_id: uuid.UUID
    scope: str
    status: str  # index_status
    title: str | None = None
    message: str | None = None  # 安全用户/运营态文案
    updated_at: datetime | None = None


class KnowledgeOpsInsightsResponse(BaseModel):
    # 边界：纯 admin（非业务用户）→ false，不返回业务标题 / owner / 文件名。
    title_visible: bool
    scope: str
    window_days: int
    cards: list[InsightCard] = []
    indexing: IndexingInsights
    access: AccessInsights
    lifecycle: LifecycleInsights
    recommendations: list[Recommendation] = []
    recent_items: list[InsightRecentItem] = []
