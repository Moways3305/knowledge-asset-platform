"""FastAPI 应用入口。

注册全部业务路由：健康检查与运维、身份会话、知识读写与检索问答、个人知识、
原文访问授权、入库、审核、预览、外部 Agent 网关（含 Dify 兼容适配器）、审计、
生命周期、告警、微盘扫描、人员 / 权限 / 项目管理、WeKnora 管理，
并挂载 CSRF 与 trace_id 中间件。
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api import (
    agent,
    agent_gateway,
    alert,
    audit,
    auth,
    dify,
    generation_models,
    health,
    ingest,
    knowledge,
    lifecycle,
    model_connections,
    my_knowledge,
    ops,
    original_access,
    people,
    permissions,
    personal_kb,
    preview,
    projects,
    review,
    search,
    wecom_scan,
    weknora_admin,
    weknora_options,
)
from app.core.config import get_settings
from app.core.csrf import CsrfMiddleware
from app.core.logging import configure_logging
from app.core.trace import TraceIdMiddleware


def create_app() -> FastAPI:
    """应用工厂。"""
    settings = get_settings()
    # 结构化 JSON 日志基线（按 LOG_LEVEL；幂等）。
    configure_logging()
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
    app.include_router(personal_kb.router)
    app.include_router(original_access.router)
    app.include_router(ingest.router)
    app.include_router(review.router)
    app.include_router(preview.router)
    app.include_router(generation_models.router)
    app.include_router(model_connections.router)
    app.include_router(agent.router)
    app.include_router(search.router)
    app.include_router(dify.router)
    app.include_router(agent_gateway.router)
    app.include_router(audit.router)
    app.include_router(lifecycle.router)
    app.include_router(alert.router)
    app.include_router(wecom_scan.router)
    app.include_router(people.router)
    app.include_router(permissions.router)
    app.include_router(projects.router)
    app.include_router(weknora_admin.router)
    app.include_router(weknora_options.router)

    return app


app = create_app()
