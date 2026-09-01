"""Authenticated WorkBuddy Streamable HTTP MCP adapter.

The protocol adapter never queries business tables directly. Every tool re-enters the
existing agent-gateway through an in-process ASGI request, so the bound caller, tenant,
project/resource permissions, safe response models and existing audit path remain canonical.
"""

from __future__ import annotations

import time
import uuid
from collections import OrderedDict, deque
from contextlib import asynccontextmanager
from datetime import timezone
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.trace import get_trace_id
from app.db.session import get_db, get_sessionmaker
from app.schemas.enums import AuditAction, AuditLogType
from app.services import agent_registry
from app.services import audit as audit_service
from app.services import external_agent_gateway as gateway

_TOOL_NAMES = (
    "kap_search_knowledge",
    "kap_list_knowledge_directories",
    "kap_answer_from_knowledge",
    "kap_list_accessible_projects",
    "kap_list_my_todos",
    "kap_list_recent_knowledge",
    "kap_list_my_personal_knowledge",
    "kap_list_accessible_knowledge",
    "kap_get_knowledge_summary",
    "kap_get_knowledge_detail",
    "kap_get_knowledge_content",
    "kap_list_tags",
    "kap_list_project_knowledge",
    "kap_get_project_brief",
    "kap_list_pending_reviews",
    "kap_list_original_access_requests",
)
_RATE_WINDOW_MAX_KEYS = 4096

_CARD_FIELDS = (
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
_CITATION_FIELDS = (
    "asset_id",
    "asset_title",
    "scope",
    "snippet",
    "citation_order",
    "directory_key",
    "directory_path",
)
_DIRECTORY_FIELDS = (
    "directory_key",
    "name",
    "description",
    "scope",
    "display_path",
    "parent_key",
    "project_id",
    "project_name",
)
_PROJECT_FIELDS = ("project_id", "name", "status", "access_mode", "access_label")
_TODO_FIELDS = (
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
_TODO_COUNT_FIELDS = ("reviews", "ingest", "original_access_mine", "original_access_inbox")
_KNOWLEDGE_CARD_FIELDS = (
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
_SUMMARY_FIELDS = (
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
_CONTENT_FIELDS = (
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
_PROJECT_BRIEF_FIELDS = (
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
_REVIEW_FIELDS = (
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
_ORIGINAL_ACCESS_FIELDS = (
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


class RemoteMcpMetrics:
    def __init__(self) -> None:
        self.requests = 0
        self.authentication_failures = 0
        self.permission_denials = 0
        self.protocol_errors = 0
        self.tool_errors = 0
        self.upstream_timeouts = 0
        self.rate_limited = 0
        self.active = 0

    def snapshot(self) -> dict[str, int | bool]:
        return {
            "enabled": get_settings().workbuddy_remote_mcp_enabled,
            "requests": self.requests,
            "authentication_failures": self.authentication_failures,
            "permission_denials": self.permission_denials,
            "protocol_errors": self.protocol_errors,
            "tool_errors": self.tool_errors,
            "upstream_timeouts": self.upstream_timeouts,
            "rate_limited": self.rate_limited,
            "active": self.active,
        }


remote_mcp_metrics = RemoteMcpMetrics()


async def _record_mcp_event(
    kap_app: FastAPI,
    bearer: str,
    *,
    action: AuditAction,
    trace_id: str,
    tool_name: str | None,
    result: str,
    duration_ms: int,
    denied_reason: str | None = None,
) -> None:
    """Best-effort structured audit. Never stores token, arguments, content or paths."""
    try:
        async with _database_session(kap_app) as session:
            rule = await agent_registry.lookup_enabled_rule(session, bearer)
            if rule is None or rule.bound_user_id is None:
                return
            caller = await gateway.resolve_caller(session, rule.bound_user_id)
            if caller is None:
                return
            await audit_service.record_event(
                session,
                caller=caller,
                log_type=AuditLogType.operation,
                action=action.value,
                trace_id=trace_id,
                target_type="workbuddy_mcp",
                target_id=rule.id,
                extra={
                    "provider": "workbuddy",
                    "tool_name": tool_name,
                    "result": result,
                    "duration_ms": max(0, duration_ms),
                    "denied_reason": denied_reason,
                },
            )
            await session.commit()
    except Exception:
        # Auditing must not turn a safe protocol response into a token-bearing traceback.
        return


class RemoteMcpOperationalGuard(BaseHTTPMiddleware):
    """Bounded request guard around the SDK transport; no business authorization lives here."""

    def __init__(self, app, *, kap_app: FastAPI) -> None:
        super().__init__(app)
        self._kap_app = kap_app
        self._semaphore = __import__("asyncio").Semaphore(
            max(1, get_settings().workbuddy_remote_concurrency)
        )
        self._rate_windows: OrderedDict[str, deque[float]] = OrderedDict()

    def _allow_rate_request(self, rate_key: str, now: float, limit: int) -> bool:
        """Apply a bounded sliding window without retaining attacker-controlled keys forever."""
        cutoff = now - 60
        while self._rate_windows:
            oldest_key = next(iter(self._rate_windows))
            oldest_window = self._rate_windows[oldest_key]
            if oldest_window and oldest_window[-1] > cutoff:
                break
            self._rate_windows.popitem(last=False)

        window = self._rate_windows.get(rate_key)
        if window is None:
            if len(self._rate_windows) >= _RATE_WINDOW_MAX_KEYS:
                # Never evict an active credential window: doing so would reset its
                # counter and let a caller bypass the limit by flooding distinct keys.
                # Unknown keys fail closed until an existing window naturally expires.
                return False
            window = deque()
            self._rate_windows[rate_key] = window
        else:
            while window and window[0] <= cutoff:
                window.popleft()

        if len(window) >= limit:
            return False
        window.append(now)
        self._rate_windows.move_to_end(rate_key)
        return True

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        import asyncio
        import hashlib
        import json

        settings = get_settings()
        remote_mcp_metrics.requests += 1
        if not settings.workbuddy_remote_mcp_enabled:
            return JSONResponse({"error": "remote_mcp_disabled"}, status_code=503)
        forwarded_scheme = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
        if settings.app_env == "prod" and not (
            request.url.scheme == "https" or forwarded_scheme == "https"
        ):
            return JSONResponse({"error": "https_required"}, status_code=400)
        content_length = request.headers.get("content-length")
        if (
            content_length
            and content_length.isdigit()
            and int(content_length) > max(1024, settings.workbuddy_remote_request_max_bytes)
        ):
            remote_mcp_metrics.protocol_errors += 1
            return JSONResponse({"error": "request_too_large"}, status_code=413)
        body = await request.body()
        if len(body) > max(1024, settings.workbuddy_remote_request_max_bytes):
            remote_mcp_metrics.protocol_errors += 1
            return JSONResponse({"error": "request_too_large"}, status_code=413)

        authorization = request.headers.get("authorization", "")
        rate_key = hashlib.sha256(authorization.encode("utf-8")).hexdigest()
        now = time.monotonic()
        if not self._allow_rate_request(
            rate_key,
            now,
            max(1, settings.workbuddy_remote_rate_limit_per_minute),
        ):
            remote_mcp_metrics.rate_limited += 1
            return JSONResponse({"error": "rate_limited"}, status_code=429)

        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=0.01)
        except TimeoutError:
            remote_mcp_metrics.rate_limited += 1
            return JSONResponse({"error": "concurrency_limited"}, status_code=429)
        remote_mcp_metrics.active += 1
        started = time.monotonic()
        try:
            response = await asyncio.wait_for(
                call_next(request),
                timeout=max(1.0, settings.workbuddy_remote_timeout_seconds),
            )
        except TimeoutError:
            remote_mcp_metrics.upstream_timeouts += 1
            return JSONResponse({"error": "request_timeout"}, status_code=504)
        finally:
            remote_mcp_metrics.active -= 1
            self._semaphore.release()

        if response.status_code == 401:
            remote_mcp_metrics.authentication_failures += 1
        elif response.status_code == 403:
            remote_mcp_metrics.permission_denials += 1
        elif response.status_code >= 400:
            remote_mcp_metrics.protocol_errors += 1

        try:
            payload = json.loads(body) if body else {}
        except ValueError:
            payload = {}
        if payload.get("method") == "tools/list" and authorization.lower().startswith("bearer "):
            await _record_mcp_event(
                self._kap_app,
                authorization.split(" ", 1)[1],
                action=AuditAction.agent_mcp_tools_listed,
                trace_id=get_trace_id(request),
                tool_name=None,
                result="success" if response.status_code < 400 else "rejected",
                duration_ms=int((time.monotonic() - started) * 1000),
                denied_reason=None if response.status_code < 400 else "protocol_rejected",
            )
        return response


def _pick(value: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {key: value[key] for key in fields if key in value}


@asynccontextmanager
async def _database_session(kap_app: FastAPI):
    override = kap_app.dependency_overrides.get(get_db)
    if override is not None:
        generator = override()
        session = await anext(generator)
        try:
            yield session
        finally:
            await generator.aclose()
        return
    async with get_sessionmaker()() as session:
        yield session


class _KapTokenVerifier:
    def __init__(self, kap_app: FastAPI) -> None:
        self._kap_app = kap_app

    async def verify_token(self, token: str) -> AccessToken | None:
        async with _database_session(self._kap_app) as session:
            rule = await agent_registry.lookup_enabled_rule(session, token)
            if (
                rule is None
                or rule.provider != "workbuddy"
                or rule.capability != "qa"
                or rule.bound_user_id is None
            ):
                return None
            caller = await gateway.resolve_caller(session, rule.bound_user_id)
            if caller is None or not caller.is_business_user:
                return None
            expires_at = rule.token_expires_at
            expires_epoch = None
            if expires_at is not None:
                aware = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
                expires_epoch = int(aware.timestamp())
            return AccessToken(
                token=token,
                client_id=f"workbuddy:{rule.id}",
                scopes=["qa"],
                expires_at=expires_epoch,
            )


def _request_bearer(ctx: Context) -> str:
    try:
        request = ctx.request_context.request
        authorization = request.headers.get("authorization")
    except Exception as exc:
        raise ToolError("连接凭据无效或已过期，请重新生成配置。") from exc
    if not authorization:
        raise ToolError("连接凭据无效或已过期，请重新生成配置。")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ToolError("连接凭据无效或已过期，请重新生成配置。")
    return token.strip()


class _ToolGateway:
    def __init__(self, kap_app: FastAPI) -> None:
        self._kap_app = kap_app

    async def request(
        self,
        ctx: Context,
        tool_name: str,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        bearer = _request_bearer(ctx)
        trace_id = uuid.uuid4().hex
        transport = httpx.ASGITransport(app=self._kap_app)
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://kap.internal",
                timeout=get_settings().workbuddy_remote_timeout_seconds,
                follow_redirects=False,
            ) as client:
                response = await client.request(
                    method,
                    path,
                    params=params,
                    json=body,
                    headers={
                        "Authorization": f"Bearer {bearer}",
                        "X-Trace-Id": trace_id,
                    },
                )
        except (httpx.TimeoutException, TimeoutError) as exc:
            remote_mcp_metrics.upstream_timeouts += 1
            await _record_mcp_event(
                self._kap_app,
                bearer,
                action=AuditAction.agent_mcp_tool_called,
                trace_id=trace_id,
                tool_name=tool_name,
                result="timeout",
                duration_ms=int((time.monotonic() - started) * 1000),
                denied_reason="upstream_timeout",
            )
            raise ToolError("工具调用超时，请稍后重试。") from exc
        except httpx.HTTPError as exc:
            remote_mcp_metrics.tool_errors += 1
            await _record_mcp_event(
                self._kap_app,
                bearer,
                action=AuditAction.agent_mcp_tool_called,
                trace_id=trace_id,
                tool_name=tool_name,
                result="error",
                duration_ms=int((time.monotonic() - started) * 1000),
                denied_reason="service_unavailable",
            )
            raise ToolError("KAP 服务暂不可用，请稍后重试。") from exc
        denied_reason = None
        result = "success"
        if response.status_code == 401:
            denied_reason, result = "authentication_failed", "rejected"
            message = "连接凭据无效或已过期，请重新生成配置。"
        elif response.status_code in {403, 404}:
            remote_mcp_metrics.permission_denials += 1
            denied_reason, result = "permission_denied", "rejected"
            message = "当前账号无权访问该资源。"
        elif response.status_code == 429:
            denied_reason, result = "rate_limited", "rejected"
            message = "调用过于频繁，请稍后重试。"
        elif response.status_code >= 500:
            remote_mcp_metrics.tool_errors += 1
            denied_reason, result = "service_unavailable", "error"
            message = "KAP 服务暂不可用，请稍后重试。"
        elif response.status_code >= 400:
            denied_reason, result = "invalid_arguments", "rejected"
            message = "请求参数无效，请检查后重试。"
        else:
            message = None
        await _record_mcp_event(
            self._kap_app,
            bearer,
            action=AuditAction.agent_mcp_tool_called,
            trace_id=trace_id,
            tool_name=tool_name,
            result=result,
            duration_ms=int((time.monotonic() - started) * 1000),
            denied_reason=denied_reason,
        )
        if message is not None:
            raise ToolError(message)
        try:
            data = response.json()
        except ValueError as exc:
            raise ToolError("KAP 服务暂不可用，请稍后重试。") from exc
        if not isinstance(data, dict):
            raise ToolError("KAP 服务暂不可用，请稍后重试。")
        return data


def _enabled_tool_names() -> set[str]:
    raw = get_settings().workbuddy_remote_mcp_tools.strip()
    if not raw or raw == "*":
        return set(_TOOL_NAMES)
    return {name.strip() for name in raw.split(",") if name.strip() in _TOOL_NAMES}


def build_remote_mcp(kap_app: FastAPI) -> FastMCP:
    """Build the server-side registry. Registration itself is the per-tool rollback switch."""
    settings = get_settings()
    base_url = urlsplit(settings.kap_public_base_url)
    host = base_url.netloc
    allowed_hosts = [host] if host else []
    allowed_origins = [
        value.strip()
        for value in settings.workbuddy_remote_allowed_origins.split(",")
        if value.strip()
    ]
    if settings.app_env != "prod":
        allowed_hosts.extend(["test", "kap.internal", "127.0.0.1:*", "localhost:*"])
        allowed_origins.extend(["http://127.0.0.1:*", "http://localhost:*"])
    public_origin = (
        f"{base_url.scheme}://{base_url.netloc}" if base_url.netloc else "http://localhost:8000"
    )
    mcp = FastMCP(
        "KAP WorkBuddy",
        instructions="只按当前绑定用户的实时 KAP 权限读取知识；不得推断或请求越权内容。",
        token_verifier=_KapTokenVerifier(kap_app),
        auth=AuthSettings(
            issuer_url=public_origin,
            resource_server_url=f"{public_origin}/mcp",
            required_scopes=["qa"],
        ),
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=sorted(set(allowed_hosts)),
            allowed_origins=sorted(set(allowed_origins)),
        ),
    )
    gateway_client = _ToolGateway(kap_app)
    enabled = _enabled_tool_names()

    if "kap_search_knowledge" in enabled:

        @mcp.tool()
        async def kap_search_knowledge(
            query: str,
            scope: str | None = None,
            top_k: int | None = None,
            tags: list[str] | None = None,
            phase: str | None = None,
            directory_key: str | None = None,
            project_id: str | None = None,
            ctx: Context | None = None,
        ) -> object:
            """检索 KAP 知识，返回按当前用户权限裁剪的安全摘要卡片。"""
            filters = {
                key: value
                for key, value in {
                    "tags": tags,
                    "phase": phase,
                    "directory_key": directory_key,
                    "project_id": project_id,
                }.items()
                if value
            }
            if directory_key:
                filters["include_descendants"] = False
            data = await gateway_client.request(
                ctx,
                "kap_search_knowledge",
                "POST",
                "/api/v1/agent-gateway/tools/knowledge-search",
                body={
                    "query": query,
                    "intent": "search",
                    **({"scope": scope} if scope else {}),
                    **({"filters": filters} if filters else {}),
                },
            )
            cards = [_pick(item, _CARD_FIELDS) for item in data.get("cards", [])]
            return cards[:top_k] if top_k else cards

    if "kap_list_knowledge_directories" in enabled:

        @mcp.tool()
        async def kap_list_knowledge_directories(ctx: Context | None = None) -> object:
            """列出当前用户可见的正式目录键与路径，不返回资产计数。"""
            data = await gateway_client.request(
                ctx,
                "kap_list_knowledge_directories",
                "GET",
                "/api/v1/agent-gateway/knowledge/directories",
            )
            return [_pick(item, _DIRECTORY_FIELDS) for item in data.get("items", [])]

    if "kap_answer_from_knowledge" in enabled:

        @mcp.tool()
        async def kap_answer_from_knowledge(
            query: str, scope: str | None = None, ctx: Context | None = None
        ) -> object:
            """基于权限范围内的 KAP 知识生成带安全引用的回答。"""
            data = await gateway_client.request(
                ctx,
                "kap_answer_from_knowledge",
                "POST",
                "/api/v1/agent-gateway/tools/knowledge-search",
                body={"query": query, "intent": "qa", **({"scope": scope} if scope else {})},
            )
            return {
                "answer": data.get("answer"),
                "citations": [_pick(item, _CITATION_FIELDS) for item in data.get("citations", [])],
            }

    if "kap_list_accessible_projects" in enabled:

        @mcp.tool()
        async def kap_list_accessible_projects(ctx: Context | None = None) -> object:
            """列出当前用户可发现的项目以及真实访问模式。"""
            data = await gateway_client.request(
                ctx,
                "kap_list_accessible_projects",
                "GET",
                "/api/v1/agent-gateway/projects",
            )
            return [_pick(item, _PROJECT_FIELDS) for item in data.get("items", [])]

    if "kap_list_my_todos" in enabled:

        @mcp.tool()
        async def kap_list_my_todos(limit: int | None = None, ctx: Context | None = None) -> object:
            """列出当前用户可见的审核、入库和原文申请待办。"""
            data = await gateway_client.request(
                ctx,
                "kap_list_my_todos",
                "GET",
                "/api/v1/agent-gateway/todos",
                params={"limit": limit} if limit is not None else None,
            )
            return {
                "items": [_pick(item, _TODO_FIELDS) for item in data.get("items", [])],
                "counts": _pick(data.get("counts") or {}, _TODO_COUNT_FIELDS),
            }

    if "kap_list_recent_knowledge" in enabled:

        @mcp.tool()
        async def kap_list_recent_knowledge(
            scope: str | None = None,
            project_id: str | None = None,
            limit: int | None = None,
            ctx: Context | None = None,
        ) -> object:
            """列出当前用户最近可见的知识资产安全卡片。"""
            params = {k: v for k, v in locals().items() if k != "ctx" and v is not None}
            data = await gateway_client.request(
                ctx,
                "kap_list_recent_knowledge",
                "GET",
                "/api/v1/agent-gateway/knowledge/recent",
                params=params,
            )
            return [_pick(item, _KNOWLEDGE_CARD_FIELDS) for item in data.get("items", [])]

    async def _knowledge_page(
        ctx: Context,
        tool_name: str,
        path: str,
        *,
        scope: str | None,
        tags: list[str] | None,
        asset_status: str | None,
        updated_from: str | None,
        updated_to: str | None,
        offset: int,
        limit: int,
    ) -> dict[str, Any]:
        params = {
            key: value
            for key, value in {
                "scope": scope,
                "tags": tags,
                "asset_status": asset_status,
                "updated_from": updated_from,
                "updated_to": updated_to,
                "offset": offset,
                "limit": limit,
            }.items()
            if value is not None
        }
        data = await gateway_client.request(ctx, tool_name, "GET", path, params=params)
        return {
            "items": [_pick(item, _KNOWLEDGE_CARD_FIELDS) for item in data.get("items", [])],
            "total": data.get("total", 0),
            "offset": data.get("offset", offset),
            "limit": data.get("limit", limit),
            "has_more": bool(data.get("has_more", False)),
        }

    if "kap_list_my_personal_knowledge" in enabled:

        @mcp.tool()
        async def kap_list_my_personal_knowledge(
            tags: list[str] | None = None,
            asset_status: str | None = None,
            updated_from: str | None = None,
            updated_to: str | None = None,
            offset: int = 0,
            limit: int = 20,
            ctx: Context | None = None,
        ) -> object:
            """列出当前绑定用户自己的个人知识，支持安全筛选与分页。"""
            return await _knowledge_page(
                ctx,
                "kap_list_my_personal_knowledge",
                "/api/v1/agent-gateway/knowledge/personal",
                scope=None,
                tags=tags,
                asset_status=asset_status,
                updated_from=updated_from,
                updated_to=updated_to,
                offset=offset,
                limit=limit,
            )

    if "kap_list_accessible_knowledge" in enabled:

        @mcp.tool()
        async def kap_list_accessible_knowledge(
            scope: str | None = None,
            tags: list[str] | None = None,
            asset_status: str | None = None,
            updated_from: str | None = None,
            updated_to: str | None = None,
            offset: int = 0,
            limit: int = 20,
            ctx: Context | None = None,
        ) -> object:
            """列出当前用户实时可见的个人、项目和公司知识。"""
            return await _knowledge_page(
                ctx,
                "kap_list_accessible_knowledge",
                "/api/v1/agent-gateway/knowledge",
                scope=scope,
                tags=tags,
                asset_status=asset_status,
                updated_from=updated_from,
                updated_to=updated_to,
                offset=offset,
                limit=limit,
            )

    async def _summary(ctx: Context, tool_name: str, asset_id: str, suffix: str) -> dict:
        data = await gateway_client.request(
            ctx,
            tool_name,
            "GET",
            f"/api/v1/agent-gateway/knowledge/{asset_id}{suffix}",
        )
        return _pick(data, _SUMMARY_FIELDS)

    if "kap_get_knowledge_summary" in enabled:

        @mcp.tool()
        async def kap_get_knowledge_summary(asset_id: str, ctx: Context | None = None) -> object:
            """获取知识资产的权限裁剪安全摘要，不返回原文。"""
            return await _summary(ctx, "kap_get_knowledge_summary", asset_id, "/summary")

    if "kap_get_knowledge_detail" in enabled:

        @mcp.tool()
        async def kap_get_knowledge_detail(asset_id: str, ctx: Context | None = None) -> object:
            """获取知识元数据、安全摘要和当前用户可用访问层。"""
            return await _summary(ctx, "kap_get_knowledge_detail", asset_id, "")

    if "kap_get_knowledge_content" in enabled:

        @mcp.tool()
        async def kap_get_knowledge_content(
            asset_id: str,
            offset: int = 0,
            max_chars: int = 4000,
            ctx: Context | None = None,
        ) -> object:
            """逐次校验原文权后分页读取文本；不可读时返回安全状态。"""
            data = await gateway_client.request(
                ctx,
                "kap_get_knowledge_content",
                "GET",
                f"/api/v1/agent-gateway/knowledge/{asset_id}/content",
                params={"offset": offset, "max_chars": max_chars},
            )
            return _pick(data, _CONTENT_FIELDS)

    if "kap_list_tags" in enabled:

        @mcp.tool()
        async def kap_list_tags(scope: str | None = None, ctx: Context | None = None) -> object:
            """列出当前用户可见知识中的安全标签及计数。"""
            data = await gateway_client.request(
                ctx,
                "kap_list_tags",
                "GET",
                "/api/v1/agent-gateway/knowledge/tags",
                params={"scope": scope} if scope else None,
            )
            return {
                "items": [_pick(item, ("name", "count")) for item in data.get("items", [])],
                "total": data.get("total", 0),
            }

    if "kap_list_project_knowledge" in enabled:

        @mcp.tool()
        async def kap_list_project_knowledge(
            project_id: str,
            limit: int | None = None,
            phase: str | None = None,
            tags: list[str] | None = None,
            ctx: Context | None = None,
        ) -> object:
            """列出项目内可发现资料；摘要项目只返回安全摘要卡片。"""
            params = {
                key: value
                for key, value in {"limit": limit, "phase": phase, "tags": tags}.items()
                if value is not None
            }
            data = await gateway_client.request(
                ctx,
                "kap_list_project_knowledge",
                "GET",
                f"/api/v1/agent-gateway/projects/{project_id}/knowledge",
                params=params,
            )
            return [_pick(item, _KNOWLEDGE_CARD_FIELDS) for item in data.get("items", [])]

    if "kap_get_project_brief" in enabled:

        @mcp.tool()
        async def kap_get_project_brief(project_id: str, ctx: Context | None = None) -> object:
            """获取项目安全概览；摘要项目返回最小视图。"""
            data = await gateway_client.request(
                ctx,
                "kap_get_project_brief",
                "GET",
                f"/api/v1/agent-gateway/projects/{project_id}/brief",
            )
            return _pick(data, _PROJECT_BRIEF_FIELDS)

    if "kap_list_pending_reviews" in enabled:

        @mcp.tool()
        async def kap_list_pending_reviews(
            limit: int | None = None, ctx: Context | None = None
        ) -> object:
            """列出当前用户可处理或可见的待审核事项。"""
            data = await gateway_client.request(
                ctx,
                "kap_list_pending_reviews",
                "GET",
                "/api/v1/agent-gateway/reviews/pending",
                params={"limit": limit} if limit is not None else None,
            )
            return [_pick(item, _REVIEW_FIELDS) for item in data.get("items", [])]

    if "kap_list_original_access_requests" in enabled:

        @mcp.tool()
        async def kap_list_original_access_requests(
            box: str = "mine",
            limit: int | None = None,
            ctx: Context | None = None,
        ) -> object:
            """列出我的原文申请或待我审批申请，不返回 grant 或预览地址。"""
            params: dict[str, Any] = {"box": box}
            if limit is not None:
                params["limit"] = limit
            data = await gateway_client.request(
                ctx,
                "kap_list_original_access_requests",
                "GET",
                "/api/v1/agent-gateway/original-access/requests",
                params=params,
            )
            return [_pick(item, _ORIGINAL_ACCESS_FIELDS) for item in data.get("items", [])]

    return mcp


__all__ = ["_TOOL_NAMES", "build_remote_mcp"]
