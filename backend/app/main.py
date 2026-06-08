"""FastAPI 应用入口。

已注册：`/health`、`/api/v1/auth/me`、Knowledge 读 API（`/api/v1/knowledge`、
`/api/v1/knowledge/{asset_id}`、`/api/v1/my/knowledge`），并挂载 trace_id 中间件。
覆盖 ~04（工作台 / 身份 / 知识资产模型 / 权限服务 / 知识读 API）。
尚不包含入库、审核、原文预览、Agent、审计表、生命周期动作等写侧业务模块。
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api import (
    agent,
    alert,
    audit,
    auth,
    dify,
    health,
    ingest,
    knowledge,
    lifecycle,
    my_knowledge,
    ops,
    original_access,
    people,
    permissions,
    preview,
    projects,
    review,
    search,
    wecom_scan,
    weknora_admin,
)
from app.core.config import get_settings
from app.core.csrf import CsrfMiddleware
from app.core.trace import TraceIdMiddleware


def create_app() -> FastAPI:
    """应用工厂。"""
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="AI Knowledge Asset Platform backend。",
    )

    # CSRF 中间件：cookie 会话下的 unsafe 请求 fail-closed。先 add → 内层；
    # TraceIdMiddleware 后 add → 外层，确保 CSRF 403 响应仍带 X-Trace-Id。
    app.add_middleware(CsrfMiddleware)
    # trace_id 关联中间件（X-Trace-Id）；它只用于链路关联，不是鉴权机制。
    app.add_middleware(TraceIdMiddleware)

    # 路由注册：健康检查 + 身份上下文 + 知识读 API。
    app.include_router(health.router)
    app.include_router(ops.router)
    app.include_router(auth.router)
    app.include_router(knowledge.router)
    app.include_router(my_knowledge.router)
    app.include_router(original_access.router)
    app.include_router(ingest.router)
    app.include_router(review.router)
    app.include_router(preview.router)
    app.include_router(agent.router)
    app.include_router(search.router)
    app.include_router(dify.router)
    app.include_router(audit.router)
    app.include_router(lifecycle.router)
    app.include_router(alert.router)
    app.include_router(wecom_scan.router)
    app.include_router(people.router)
    app.include_router(permissions.router)
    app.include_router(projects.router)
    app.include_router(weknora_admin.router)

    return app


app = create_app()

