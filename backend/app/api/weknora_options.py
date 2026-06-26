"""顾问只读模型选项 API（PBC-38）。

业务用户在入库 / 建库前查看可选模型（embedding / rerank 等），用于在高级设置里切换模型。
**只读：无任何 CRUD**——模型注册 / 修改仍归 `/admin/weknora/*`（admin-only）。

权限：active 业务用户可读（admin / 治理角色若本身是业务用户也可读）。纯 admin（非业务用户）
与 inactive 一律 403——纯 admin 走 `/admin/weknora/models`，此端点不扩大其业务知识权限。

安全：只回安全展示字段（model_ref / name / type / provider / description / enabled / is_default），
绝不回真实 model_id / api_key / base_url / 底座 payload。WeKnora 未配置 → 安全 503。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.permission import CallerContext
from app.schemas.weknora_admin import ModelOptionsResponse
from app.services import weknora_models
from app.services.weknora_client import (
    NullWeKnoraClient,
    WeKnoraClient,
    WeKnoraError,
    get_weknora_client,
    weknora_enabled,
)

router = APIRouter(prefix="/api/v1/weknora", tags=["weknora-options"])


def _require_business_user(caller: CallerContext) -> None:
    """active 业务用户闸。纯 admin / inactive → 403（不扩大业务知识权限）。"""
    if not caller.is_active or not caller.is_business_user:
        raise HTTPException(
            403,
            detail={
                "denied_reason": "weknora_options_forbidden",
                "message": "仅业务用户可查看模型选项",
            },
        )


@router.get("/model-options", response_model=ModelOptionsResponse)
async def list_model_options(
    request: Request,
    type: str | None = None,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    weknora: WeKnoraClient | NullWeKnoraClient = Depends(get_weknora_client),
) -> ModelOptionsResponse:
    """列可选模型（可按 type 过滤，如 embedding / rerank）。仅安全字段 + is_default + default_missing。"""
    _require_business_user(caller)
    if not weknora_enabled():
        raise HTTPException(
            503,
            detail={"denied_reason": "weknora_not_configured", "message": "WeKnora 未配置"},
        )
    try:
        return await weknora_models.list_model_options(
            session, weknora, model_type=type, trace_id=get_trace_id(request)
        )
    except WeKnoraError:
        raise HTTPException(
            502,
            detail={
                "denied_reason": "weknora_call_failed",
                "message": "底座模型列举失败，请稍后重试",
            },
        )
