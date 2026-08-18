"""KAP agent-gateway HTTP 客户端 + 安全字段投影 + 错误收口。

- 仅带 Authorization: Bearer；绝不带任何身份 header（caller 由 token 绑定在后端解析）。
- 响应只透出显式 allowlist 字段（后端即便多回字段也不外泄）。
- 后端 401/403/5xx → 统一安全文案；不回显 denied_reason / trace / token / URL / 内部 id。
"""

from __future__ import annotations

import httpx

from .config import Config

_SEARCH_PATH = "/api/v1/agent-gateway/tools/knowledge-search"
_DIRECTORIES_PATH = "/api/v1/agent-gateway/knowledge/directories"
_PROJECTS_PATH = "/api/v1/agent-gateway/projects"
# 只读工作台端点（PBC-37）。
_TODOS_PATH = "/api/v1/agent-gateway/todos"
_RECENT_PATH = "/api/v1/agent-gateway/knowledge/recent"
_KNOWLEDGE_PATH = "/api/v1/agent-gateway/knowledge"
_PERSONAL_KNOWLEDGE_PATH = "/api/v1/agent-gateway/knowledge/personal"
_DETAIL_PATH = "/api/v1/agent-gateway/knowledge/{asset_id}"
_CONTENT_PATH = "/api/v1/agent-gateway/knowledge/{asset_id}/content"
_TAGS_PATH = "/api/v1/agent-gateway/knowledge/tags"
_SUMMARY_PATH = "/api/v1/agent-gateway/knowledge/{asset_id}/summary"
_PROJECT_KNOWLEDGE_PATH = "/api/v1/agent-gateway/projects/{project_id}/knowledge"
_PROJECT_BRIEF_PATH = "/api/v1/agent-gateway/projects/{project_id}/brief"
_REVIEWS_PATH = "/api/v1/agent-gateway/reviews/pending"
_ORIGINAL_ACCESS_PATH = "/api/v1/agent-gateway/original-access/requests"

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
    "directory_key",
    "directory_path",
)
CITATION_FIELDS = (
    "asset_id",
    "asset_title",
    "scope",
    "snippet",
    "citation_order",
    "directory_key",
    "directory_path",
)
DIRECTORY_FIELDS = (
    "directory_key",
    "name",
    "description",
    "scope",
    "display_path",
    "parent_key",
    "project_id",
    "project_name",
)
PROJECT_FIELDS = ("project_id", "name", "status", "access_mode", "access_label")

# 工作台端点字段白名单（后端即便多回字段，MCP 也只透出这些）。
TODO_FIELDS = (
    "todo_id",
    "type",
    "title",
    "status",
    "priority",
    "project_id",
    "project_name",
    "asset_id",
    "asset_title",
    "created_at",
)
TODO_COUNTS_FIELDS = (
    "reviews",
    "ingest",
    "original_access_mine",
    "original_access_inbox",
)
KNOWLEDGE_CARD_FIELDS = (
    "asset_id",
    "title",
    "scope",
    "zone",
    "asset_type",
    "confidentiality_level",
    "one_liner",
    "updated_at",
    "project_id",
    "project_name",
    "can_view_original",
)
SUMMARY_FIELDS = (
    "asset_id",
    "title",
    "scope",
    "zone",
    "asset_type",
    "confidentiality_level",
    "summary",
    "key_points",
    "tags",
    "project_id",
    "project_name",
    "access_layer",
    "available_access_layers",
    "can_view_original",
    "existing_original_request_status",
)
CONTENT_FIELDS = (
    "asset_id",
    "content",
    "content_available",
    "content_status",
    "message",
    "offset",
    "returned_chars",
    "next_offset",
    "has_more",
)
TAG_FIELDS = ("name", "count")
PROJECT_BRIEF_FIELDS = (
    "project_id",
    "name",
    "status",
    "access_mode",
    "access_label",
    "message",
    "phase",
    "my_role",
    "knowledge_count",
    "recent_asset_count",
    "pending_review_count",
    "pending_original_request_count",
)
REVIEW_FIELDS = (
    "review_id",
    "review_type",
    "status",
    "asset_id",
    "asset_title",
    "project_id",
    "project_name",
    "created_at",
    "due_hint",
)
ORIGINAL_ACCESS_FIELDS = (
    "request_id",
    "box",
    "status",
    "asset_id",
    "asset_title",
    "requester_name",
    "reviewer_name",
    "reason",
    "created_at",
    "reviewed_at",
    "expires_at",
)

_DENIED_MSG = "无访问权限或调用身份无效"
_UNAVAILABLE_MSG = "知识服务暂不可用，请稍后重试"


class KapError(Exception):
    """安全错误（消息已收口，可直接回给 WorkBuddy/LLM）。"""


def _pick(obj: dict, fields: tuple[str, ...]) -> dict:
    return {k: obj[k] for k in fields if k in obj}


class KapClient:
    def __init__(self, config: Config, *, client: httpx.Client | None = None) -> None:
        self._cfg = config
        self._http = client or httpx.Client(
            base_url=config.base_url,
            timeout=30.0,
            follow_redirects=False,
        )

    def _headers(self, bearer: str | None) -> dict:
        # 远程多用户：bearer 来自本次请求（调用人本人 token）；stdio：用进程级 token。
        token = bearer or self._cfg.agent_token
        if not token:
            raise KapError(_DENIED_MSG)
        return {"Authorization": f"Bearer {token}"}

    def _handle(self, resp: httpx.Response) -> dict:
        if 300 <= resp.status_code < 400:
            raise KapError(_UNAVAILABLE_MSG)
        if resp.status_code in (401, 403):
            raise KapError(_DENIED_MSG)
        if resp.status_code >= 500 or resp.status_code == 404:
            raise KapError(_UNAVAILABLE_MSG)
        if resp.status_code >= 400:
            raise KapError(_DENIED_MSG)
        content_type = resp.headers.get("content-type", "").lower()
        if "json" not in content_type:
            raise KapError(_UNAVAILABLE_MSG)
        try:
            data = resp.json()
        except ValueError:
            raise KapError(_UNAVAILABLE_MSG) from None
        if not isinstance(data, dict):
            raise KapError(_UNAVAILABLE_MSG)
        return data

    def post(self, path: str, body: dict, *, bearer: str | None = None) -> dict:
        try:
            resp = self._http.post(path, json=body, headers=self._headers(bearer))
        except httpx.HTTPError:
            raise KapError(_UNAVAILABLE_MSG) from None
        return self._handle(resp)

    def get(self, path: str, *, params: dict | None = None, bearer: str | None = None) -> dict:
        try:
            resp = self._http.get(path, params=params or None, headers=self._headers(bearer))
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
    directory_key: str | None = None,
    project_id: str | None = None,
    bearer: str | None = None,
) -> list[dict]:
    body: dict = {"query": query, "intent": "search"}
    if scope:
        body["scope"] = scope
    filters: dict = {}
    if tags:
        filters["tags"] = tags
    if phase:
        filters["phase"] = phase
    if directory_key:
        filters["directory_key"] = directory_key
        filters["include_descendants"] = False
    if project_id:
        filters["project_id"] = project_id
    if filters:
        body["filters"] = filters
    data = client.post(_SEARCH_PATH, body, bearer=bearer)
    cards = [_pick(c, CARD_FIELDS) for c in data.get("cards", [])]
    return cards[:top_k] if top_k else cards


def list_directories(client: KapClient, *, bearer: str | None = None) -> list[dict]:
    data = client.get(_DIRECTORIES_PATH, bearer=bearer)
    return [_pick(item, DIRECTORY_FIELDS) for item in data.get("items", [])]


def answer_from_knowledge(
    client: KapClient,
    query: str,
    *,
    scope: str | None = None,
    bearer: str | None = None,
) -> dict:
    body: dict = {"query": query, "intent": "qa"}
    if scope:
        body["scope"] = scope
    data = client.post(_SEARCH_PATH, body, bearer=bearer)
    return {
        "answer": data.get("answer"),
        "citations": [_pick(c, CITATION_FIELDS) for c in data.get("citations", [])],
    }


def list_accessible_projects(client: KapClient, *, bearer: str | None = None) -> list[dict]:
    data = client.get(_PROJECTS_PATH, bearer=bearer)
    return [_pick(p, PROJECT_FIELDS) for p in data.get("items", [])]


# --------------------- 只读工作台工具（PBC-37）---------------------
def list_my_todos(
    client: KapClient, *, limit: int | None = None, bearer: str | None = None
) -> dict:
    params: dict = {}
    if limit is not None:
        params["limit"] = limit
    data = client.get(_TODOS_PATH, params=params, bearer=bearer)
    return {
        "items": [_pick(i, TODO_FIELDS) for i in data.get("items", [])],
        "counts": _pick(data.get("counts") or {}, TODO_COUNTS_FIELDS),
    }


def list_recent_knowledge(
    client: KapClient,
    *,
    scope: str | None = None,
    project_id: str | None = None,
    limit: int | None = None,
    bearer: str | None = None,
) -> list[dict]:
    params: dict = {}
    if scope:
        params["scope"] = scope
    if project_id:
        params["project_id"] = project_id
    if limit is not None:
        params["limit"] = limit
    data = client.get(_RECENT_PATH, params=params, bearer=bearer)
    return [_pick(c, KNOWLEDGE_CARD_FIELDS) for c in data.get("items", [])]


def list_accessible_knowledge(
    client: KapClient,
    *,
    scope: str | None = None,
    tags: list[str] | None = None,
    asset_status: str | None = None,
    updated_from: str | None = None,
    updated_to: str | None = None,
    offset: int = 0,
    limit: int = 20,
    personal_only: bool = False,
    bearer: str | None = None,
) -> dict:
    params: dict = {"offset": offset, "limit": limit}
    if scope and not personal_only:
        params["scope"] = scope
    if tags:
        params["tags"] = tags
    if asset_status:
        params["asset_status"] = asset_status
    if updated_from:
        params["updated_from"] = updated_from
    if updated_to:
        params["updated_to"] = updated_to
    path = _PERSONAL_KNOWLEDGE_PATH if personal_only else _KNOWLEDGE_PATH
    data = client.get(path, params=params, bearer=bearer)
    return {
        "items": [_pick(c, KNOWLEDGE_CARD_FIELDS) for c in data.get("items", [])],
        "total": data.get("total", 0),
        "offset": data.get("offset", offset),
        "limit": data.get("limit", limit),
        "has_more": bool(data.get("has_more", False)),
    }


def get_knowledge_summary(client: KapClient, asset_id: str, *, bearer: str | None = None) -> dict:
    data = client.get(_SUMMARY_PATH.format(asset_id=asset_id), bearer=bearer)
    return _pick(data, SUMMARY_FIELDS)


def get_knowledge_detail(client: KapClient, asset_id: str, *, bearer: str | None = None) -> dict:
    data = client.get(_DETAIL_PATH.format(asset_id=asset_id), bearer=bearer)
    return _pick(data, SUMMARY_FIELDS)


def get_knowledge_content(
    client: KapClient,
    asset_id: str,
    *,
    offset: int = 0,
    max_chars: int = 4000,
    bearer: str | None = None,
) -> dict:
    data = client.get(
        _CONTENT_PATH.format(asset_id=asset_id),
        params={"offset": offset, "max_chars": max_chars},
        bearer=bearer,
    )
    return _pick(data, CONTENT_FIELDS)


def list_tags(client: KapClient, *, scope: str | None = None, bearer: str | None = None) -> dict:
    params = {"scope": scope} if scope else None
    data = client.get(_TAGS_PATH, params=params, bearer=bearer)
    return {
        "items": [_pick(item, TAG_FIELDS) for item in data.get("items", [])],
        "total": data.get("total", 0),
    }


def list_project_knowledge(
    client: KapClient,
    project_id: str,
    *,
    limit: int | None = None,
    phase: str | None = None,
    tags: list[str] | None = None,
    bearer: str | None = None,
) -> list[dict]:
    params: dict = {}
    if limit is not None:
        params["limit"] = limit
    if phase:
        params["phase"] = phase
    if tags:
        params["tags"] = tags
    data = client.get(
        _PROJECT_KNOWLEDGE_PATH.format(project_id=project_id),
        params=params,
        bearer=bearer,
    )
    return [_pick(c, KNOWLEDGE_CARD_FIELDS) for c in data.get("items", [])]


def get_project_brief(client: KapClient, project_id: str, *, bearer: str | None = None) -> dict:
    data = client.get(_PROJECT_BRIEF_PATH.format(project_id=project_id), bearer=bearer)
    return _pick(data, PROJECT_BRIEF_FIELDS)


def list_pending_reviews(
    client: KapClient, *, limit: int | None = None, bearer: str | None = None
) -> list[dict]:
    params: dict = {}
    if limit is not None:
        params["limit"] = limit
    data = client.get(_REVIEWS_PATH, params=params, bearer=bearer)
    return [_pick(i, REVIEW_FIELDS) for i in data.get("items", [])]


def list_original_access_requests(
    client: KapClient,
    *,
    box: str = "mine",
    limit: int | None = None,
    bearer: str | None = None,
) -> list[dict]:
    params: dict = {"box": box}
    if limit is not None:
        params["limit"] = limit
    data = client.get(_ORIGINAL_ACCESS_PATH, params=params, bearer=bearer)
    return [_pick(i, ORIGINAL_ACCESS_FIELDS) for i in data.get("items", [])]
