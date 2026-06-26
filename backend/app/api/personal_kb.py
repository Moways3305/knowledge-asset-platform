"""个人知识库管理 API（PBC-29）。

- POST /api/v1/my/knowledge-base  显式创建（幂等 / init_failed 重试）。
- GET  /api/v1/my/knowledge-base  查看状态（无映射 → exists=false）。
- PUT  /api/v1/my/knowledge-base  改名（同步底座，底座失败降级）。

owner-only：仅 active 业务用户管理自己的 KB；纯 admin 403（走 /admin/weknora/*）。
权限与审计委托 `app.services.personal_kb`，本层只编排。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.permission import CallerContext
from app.schemas.personal_kb import (
    PersonalKbCreateRequest,
    PersonalKbOut,
    PersonalKbRenameRequest,
)
from app.services import personal_kb as personal_kb_service
from app.services.weknora_client import (
    NullWeKnoraClient,
    WeKnoraClient,
    get_weknora_client,
)

router = APIRouter(prefix="/api/v1/my/knowledge-base", tags=["my-knowledge-base"])


@router.post("", response_model=PersonalKbOut)
async def create_my_kb(
    req: PersonalKbCreateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    weknora: WeKnoraClient | NullWeKnoraClient = Depends(get_weknora_client),
) -> PersonalKbOut:
    return await personal_kb_service.create_personal_kb(
        session,
        weknora,
        caller,
        display_name=req.display_name,
        embedding_model_ref=req.embedding_model_ref,
        rerank_model_ref=req.rerank_model_ref,
        trace_id=get_trace_id(request),
    )


@router.get("", response_model=PersonalKbOut)
async def get_my_kb(
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> PersonalKbOut:
    return await personal_kb_service.get_personal_kb(
        session, caller, trace_id=get_trace_id(request)
    )


@router.put("", response_model=PersonalKbOut)
async def rename_my_kb(
    req: PersonalKbRenameRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    weknora: WeKnoraClient | NullWeKnoraClient = Depends(get_weknora_client),
) -> PersonalKbOut:
    return await personal_kb_service.rename_personal_kb(
        session, weknora, caller, display_name=req.display_name, trace_id=get_trace_id(request)
    )
