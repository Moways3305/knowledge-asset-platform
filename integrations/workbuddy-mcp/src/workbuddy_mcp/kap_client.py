"""KAP agent-gateway HTTP 客户端 + 安全字段投影 + 错误收口。

- 仅带 Authorization: Bearer；绝不带任何身份 header（caller 由 token 绑定在后端解析）。
- 响应只透出显式 allowlist 字段（后端即便多回字段也不外泄）。
- 后端 401/403/5xx → 统一安全文案；不回显 denied_reason / trace / token / URL / 内部 id。
"""

from __future__ import annotations

import httpx

from .config import Config

_SEARCH_PATH = "/api/v1/agent-gateway/tools/knowledge-search"
_PROJECTS_PATH = "/api/v1/agent-gateway/projects"

CARD_FIELDS = (
    "asset_id",
    "title",
    "asset_type",
    "scope",
    "zone",
    "confidentiality_level",
    "one_liner",
    "detailed",
    "relevance_score",
    "can_view_original",
)
CITATION_FIELDS = ("asset_id", "asset_title", "scope", "snippet", "citation_order")
PROJECT_FIELDS = ("project_id", "name", "status")

_DENIED_MSG = "无访问权限或调用身份无效"
_UNAVAILABLE_MSG = "知识服务暂不可用，请稍后重试"


class KapError(Exception):
    """安全错误（消息已收口，可直接回给 WorkBuddy/LLM）。"""


def _pick(obj: dict, fields: tuple[str, ...]) -> dict:
    return {k: obj[k] for k in fields if k in obj}


class KapClient:
    def __init__(self, config: Config, *, client: httpx.Client | None = None) -> None:
        self._cfg = config
        self._http = client or httpx.Client(base_url=config.base_url, timeout=30.0)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._cfg.agent_token}"}

    def _handle(self, resp: httpx.Response) -> dict:
        if resp.status_code in (401, 403):
            raise KapError(_DENIED_MSG)
        if resp.status_code >= 500 or resp.status_code == 404:
            raise KapError(_UNAVAILABLE_MSG)
        if resp.status_code >= 400:
            raise KapError(_DENIED_MSG)
        return resp.json()

    def post(self, path: str, body: dict) -> dict:
        try:
            resp = self._http.post(path, json=body, headers=self._headers())
        except httpx.HTTPError:
            raise KapError(_UNAVAILABLE_MSG) from None
        return self._handle(resp)

    def get(self, path: str) -> dict:
        try:
            resp = self._http.get(path, headers=self._headers())
        except httpx.HTTPError:
            raise KapError(_UNAVAILABLE_MSG) from None
        return self._handle(resp)


def search_knowledge(
    client: KapClient,
    query: str,
    *,
    scope: str | None = None,
    top_k: int | None = None,
    tags: list[str] | None = None,
    phase: str | None = None,
) -> list[dict]:
    body: dict = {"query": query, "intent": "search"}
    if scope:
        body["scope"] = scope
    filters: dict = {}
    if tags:
        filters["tags"] = tags
    if phase:
        filters["phase"] = phase
    if filters:
        body["filters"] = filters
    data = client.post(_SEARCH_PATH, body)
    cards = [_pick(c, CARD_FIELDS) for c in data.get("cards", [])]
    return cards[:top_k] if top_k else cards


def answer_from_knowledge(client: KapClient, query: str, *, scope: str | None = None) -> dict:
    body: dict = {"query": query, "intent": "qa"}
    if scope:
        body["scope"] = scope
    data = client.post(_SEARCH_PATH, body)
    return {
        "answer": data.get("answer"),
        "citations": [_pick(c, CITATION_FIELDS) for c in data.get("citations", [])],
    }


def list_accessible_projects(client: KapClient) -> list[dict]:
    data = client.get(_PROJECTS_PATH)
    return [_pick(p, PROJECT_FIELDS) for p in data.get("items", [])]
