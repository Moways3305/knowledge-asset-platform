"""Dify **适配器** 的 wire-protocol schema（PBC-01）。

平台核心是 provider 中立的外部 Agent / 工作流网关（见 `app/schemas/external_agent.py`
与 `app/services/external_agent_gateway.py`）。本模块只承载 **Dify 专属的请求线缆形态**：

1. Dify External Knowledge API（`/dify/external-knowledge/retrieval`）——官方协议形态。
2. Dify HTTP Tool（`/dify/tools/knowledge-search`）——复用 R3 SearchResponse。

接入注册（registry）schema 与网关检索记录已迁到 provider 中立的 `external_agent` 模块；
此处仅 **re-export** 以保持向后兼容的导入路径。

安全：所有响应**绝不**含 token / token_hash / provider 内部标识 / WeKnora kb·doc·chunk id /
内部存储引用 / api_key。
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel

# provider 中立 record 即 Dify external-knowledge record 的安全载体（content/score/title/metadata）。
from app.schemas.external_agent import ExternalRetrievalRecord as DifyRecord
from app.schemas.external_agent import (  # noqa: F401  向后兼容 re-export（注册 schema 现为 provider 中立）
    RegistryCreateRequest,
    RegistryCreateResponse,
    RegistryListResponse,
    RegistryRuleOut,
    RegistryUpdateRequest,
)

__all__ = [
    "DifyRetrievalSetting",
    "DifyExternalRequest",
    "DifyRecord",
    "DifyExternalResponse",
    "DifyToolFilters",
    "DifyToolRequest",
    "RegistryRuleOut",
    "RegistryListResponse",
    "RegistryCreateRequest",
    "RegistryUpdateRequest",
    "RegistryCreateResponse",
]


# ---------------- Dify External Knowledge API（官方协议线缆形态）----------------
class DifyRetrievalSetting(BaseModel):
    top_k: int = 3
    score_threshold: float = 0.0


class DifyExternalRequest(BaseModel):
    """官方字段：knowledge_id / query / retrieval_setting / metadata_condition?。"""

    knowledge_id: str
    query: str
    retrieval_setting: DifyRetrievalSetting = DifyRetrievalSetting()
    metadata_condition: dict | None = None


class DifyExternalResponse(BaseModel):
    records: list[DifyRecord]


# ---------------- Dify HTTP Tool（线缆形态）----------------
class DifyToolFilters(BaseModel):
    zone: str | None = None
    tags: list[str] = []
    phase: str | None = None
    include_archived: bool = False


class DifyToolRequest(BaseModel):
    """Dify workflow HTTP Tool 调用：显式携带 caller / scope / project 等参数。"""

    caller_user_id: uuid.UUID
    query: str
    scope: str | None = None
    intent: str | None = None
    filters: DifyToolFilters = DifyToolFilters()
    want_original: bool = False
    asset_id: uuid.UUID | None = None
