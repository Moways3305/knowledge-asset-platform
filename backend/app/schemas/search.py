"""统一检索 / 问答接口 `POST /knowledge/search` 的请求 / 响应 schema（R3）。

响应**绝不包含** weknora kb/doc/chunk id、内部存储引用、api_key、未脱敏原文 chunk。
卡片只暴露业务标识（asset_id 是平台业务主键）+ 安全摘要；原文片段只在有权 + 脱敏后给出。

该接口被设计为 R4 Dify 外部知识库协议适配的**底层**：`cards` 的"业务标识 + 安全摘要 +
relevance_score"形态可被 R4 直接映射为 Dify external-knowledge 的 records（content=安全
摘要、score=relevance_score、metadata=业务标识），无需暴露任何内部标识；本票不接 Dify。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class SearchFilters(BaseModel):
    """检索过滤项。include_archived 当前不放行归档（archived 始终排除，安全口径一致）。"""

    zone: str | None = None
    tags: list[str] = []
    phase: str | None = None
    include_archived: bool = False


class SearchRequest(BaseModel):
    """统一检索请求。

    - scope：personal / project / company / all（缺省=all 并集）。
    - intent：可显式指定 6 类意图之一；缺省由规则分类，降级默认 search。
    - want_original + asset_id：阶段2，取某资产脱敏原文。
    """

    query: str
    scope: str | None = None
    intent: str | None = None
    filters: SearchFilters = SearchFilters()
    want_original: bool = False
    asset_id: uuid.UUID | None = None


class SearchCardOut(BaseModel):
    """阶段1摘要卡片（§6.1）。绝不含原文 / kb/doc/chunk id / 客户敏感实体。"""

    asset_id: uuid.UUID
    title: str
    asset_type: str
    scope: str
    zone: str
    confidentiality_level: str
    phase: str | None
    tags: list[str]
    one_liner: str | None
    detailed: str | None
    key_points: list[str]
    owner_name: str | None
    maintainer_name: str | None
    project_name: str | None
    updated_at: datetime | None
    version: str | None
    relevance_score: float
    can_view_original: bool


class SearchCitationOut(BaseModel):
    """问答引用来源（只暴露业务标识 + 脱敏片段 + seq）。"""

    asset_id: uuid.UUID
    asset_title: str
    scope: str
    cited_zone: str
    used_access_layer: str
    seq: int | None = None
    snippet: str | None = None
    citation_order: int


class OriginalChunkOut(BaseModel):
    """阶段2脱敏原文片段（content 已实体脱敏；seq 为安全序号，非内部 id）。"""

    seq: int | None = None
    content: str


class OriginalOut(BaseModel):
    """阶段2原文结果。available=False 时无 chunk，只给联系人。"""

    asset_id: uuid.UUID | None
    available: bool
    chunks: list[OriginalChunkOut] = []
    degraded_reason: str | None = None
    owner_name: str | None = None
    maintainer_name: str | None = None


class SearchResponse(BaseModel):
    """统一检索响应。intent=问答/生成/总结/检查 时附 answer + citations；want_original 有权时附 original。"""

    intent: str
    cards: list[SearchCardOut]
    answer: str | None = None
    citations: list[SearchCitationOut] = []
    original: OriginalOut | None = None
    trace_id: str | None = None
