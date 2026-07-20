"""WorkBuddy 只读工作台工具的 **provider 中立** 响应 schema。

这些 schema 服务于 `/api/v1/agent-gateway/*` 下的只读工作台端点（todos / recent /
summary / project knowledge / project brief / reviews / original-access）。全部为
**白名单投影**：只承载安全治理元数据，绝不含原文 / 摘要全文以外的敏感内容、对象存储引用、
下载 / 预览 URL、WeKnora kb·doc·chunk id、provider 内部标识（app/workflow/dataset id）、
token / token_hash / api_key、客户敏感数据。

调用人不在请求体——身份由 token 在后端绑定解析（见 `agent_gateway.require_bound_caller`）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


# ---------------- todos ----------------
class AgentWorkbenchTodoItem(BaseModel):
    """工作台待办条目（安全聚合）。asset_title 已按权限边界裁剪，无权看标题时为安全占位。"""

    todo_id: str
    type: str  # review | original_access_mine | original_access_inbox | ingest
    title: str
    status: str
    priority: str = "normal"
    project_id: uuid.UUID | None = None
    project_name: str | None = None
    asset_id: uuid.UUID | None = None
    asset_title: str | None = None
    created_at: datetime | None = None


class WorkbenchTodoCounts(BaseModel):
    reviews: int = 0
    ingest: int = 0
    original_access_mine: int = 0
    original_access_inbox: int = 0


class WorkbenchTodosResponse(BaseModel):
    items: list[AgentWorkbenchTodoItem]
    counts: WorkbenchTodoCounts


# ---------------- knowledge cards（recent / project）----------------
class WorkbenchKnowledgeCard(BaseModel):
    """可见知识资产的安全卡片（discovery + 安全 one_liner）。绝不含原文 / 内部引用。"""

    asset_id: uuid.UUID
    title: str
    scope: str
    zone: str
    asset_type: str
    confidentiality_level: str
    one_liner: str | None = None
    updated_at: datetime | None = None
    project_id: uuid.UUID | None = None
    project_name: str | None = None
    can_view_original: bool = False


class WorkbenchKnowledgeListResponse(BaseModel):
    items: list[WorkbenchKnowledgeCard]
    total: int


# ---------------- knowledge summary ----------------
class WorkbenchKnowledgeSummary(BaseModel):
    """单个知识资产的安全摘要（discovery/summary 层）。summary 为安全 / 脱敏摘要。

    即使 can_view_original=True，也**绝不**经此返回原文 / 文件 / 预览。
    """

    asset_id: uuid.UUID
    title: str
    scope: str
    zone: str
    asset_type: str
    confidentiality_level: str
    summary: str | None = None
    key_points: list[str] = []
    tags: list[str] = []
    project_id: uuid.UUID | None = None
    project_name: str | None = None
    access_layer: str  # discovery | summary | original（调用人可达最高层级）
    can_view_original: bool = False
    existing_original_request_status: str | None = None


# ---------------- project brief ----------------
class WorkbenchProjectBrief(BaseModel):
    """调用人可见的项目概览（不含客户敏感信息 / 成员名单 / 内部配置开关）。"""

    project_id: uuid.UUID
    name: str
    status: str
    phase: str | None = None
    my_role: str | None = None
    knowledge_count: int = 0
    recent_asset_count: int = 0
    pending_review_count: int = 0
    pending_original_request_count: int = 0


# ---------------- pending reviews ----------------
class WorkbenchReviewItem(BaseModel):
    """调用人可处理 / 可见的待审核事项（只读，安全字段）。"""

    review_id: uuid.UUID
    review_type: str
    status: str
    asset_id: uuid.UUID | None = None
    asset_title: str | None = None
    project_id: uuid.UUID | None = None
    project_name: str | None = None
    created_at: datetime | None = None
    due_hint: str | None = None


class WorkbenchReviewsResponse(BaseModel):
    items: list[WorkbenchReviewItem]
    total: int


# ---------------- original-access requests ----------------
class WorkbenchOriginalAccessItem(BaseModel):
    """原文访问申请安全视图（只读）。reason 复用现有安全输出口径（创建时已脱敏）。"""

    request_id: uuid.UUID
    box: str  # mine | inbox
    status: str
    asset_id: uuid.UUID | None = None
    asset_title: str | None = None
    requester_name: str | None = None
    reviewer_name: str | None = None
    reason: str | None = None
    created_at: datetime | None = None
    reviewed_at: datetime | None = None
    expires_at: datetime | None = None


class WorkbenchOriginalAccessResponse(BaseModel):
    items: list[WorkbenchOriginalAccessItem]
    total: int
