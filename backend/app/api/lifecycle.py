"""知识生命周期动作 API。

5 个端点：archive-request / archive-confirm / reenable-request / reenable-confirm /
events。权限与状态机判断全部委托 `app.services.lifecycle`（其内部复用集中权限服务）。
trace_id 经中间件注入，统一透传进生命周期事件 / 审计 / 通知。
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.governance import GovernanceBatch, GovernanceBatchResult, GovernancePage
from app.schemas.knowledge_review import (
    CorrectionCommand,
    CorrectionTransition,
    MaintenancePage,
    ReplacementCommand,
    ReplacementOption,
    ReviewCommand,
    ReviewPolicyCommand,
    ReviewState,
)
from app.schemas.lifecycle import (
    ArchiveConfirmBody,
    ArchiveConfirmResponse,
    ArchiveRequestBody,
    LifecycleActionResponse,
    LifecycleEventsResponse,
    ReenableConfirmBody,
    ReenableConfirmResponse,
    ReenableRequestBody,
)
from app.schemas.permission import CallerContext
from app.services import company_governance, knowledge_review
from app.services import lifecycle as lifecycle_service

router = APIRouter(prefix="/api/v1", tags=["lifecycle"])


@router.get("/knowledge-maintenance", response_model=MaintenancePage)
async def knowledge_maintenance_list(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=50),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await knowledge_review.list_maintenance(session, caller, page=page, page_size=page_size)


@router.get("/knowledge/{asset_id}/trust", response_model=ReviewState)
async def knowledge_trust_state(
    asset_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await knowledge_review.get_state(session, caller, asset_id)


@router.patch("/knowledge/{asset_id}/trust/policy", response_model=ReviewState)
async def knowledge_trust_policy(
    asset_id: uuid.UUID,
    body: ReviewPolicyCommand,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await knowledge_review.set_policy(session, caller, asset_id, body, get_trace_id(request))


@router.post("/knowledge/{asset_id}/trust/review", response_model=ReviewState)
async def knowledge_trust_review(
    asset_id: uuid.UUID,
    body: ReviewCommand,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await knowledge_review.review(session, caller, asset_id, body, get_trace_id(request))


@router.post("/knowledge/{asset_id}/trust/replacement", response_model=ReviewState)
async def knowledge_trust_replacement(
    asset_id: uuid.UUID,
    body: ReplacementCommand,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await knowledge_review.replace(session, caller, asset_id, body, get_trace_id(request))


@router.get("/knowledge/{asset_id}/trust/replacements", response_model=list[ReplacementOption])
async def knowledge_trust_replacements(
    asset_id: uuid.UUID,
    keyword: str = Query("", max_length=200),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await knowledge_review.replacement_options(session, caller, asset_id, keyword)


@router.post("/knowledge/{asset_id}/trust/corrections", response_model=ReviewState)
async def knowledge_trust_report(
    asset_id: uuid.UUID,
    body: CorrectionCommand,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await knowledge_review.report(session, caller, asset_id, body, get_trace_id(request))


@router.post("/knowledge/{asset_id}/trust/corrections/{correction_id}", response_model=ReviewState)
async def knowledge_trust_transition(
    asset_id: uuid.UUID,
    correction_id: uuid.UUID,
    body: CorrectionTransition,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await knowledge_review.transition(
        session, caller, asset_id, correction_id, body, get_trace_id(request)
    )


@router.get("/company-governance", response_model=GovernancePage)
async def company_governance_list(
    view: Literal["candidates", "all", "archived"] = "candidates",
    signal: Literal[
        "same_title", "draft", "policy_age", "research_age", "content_check", "needs_update"
    ]
    | None = None,
    keyword: str = Query("", max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=50),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> GovernancePage:
    return await company_governance.list_company(
        session, caller, view=view, signal=signal, keyword=keyword, page=page, page_size=page_size
    )


@router.post("/company-governance/batch", response_model=GovernanceBatchResult)
async def company_governance_batch(
    body: GovernanceBatch,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> GovernanceBatchResult:
    return await company_governance.apply_batch(session, caller, body, get_trace_id(request))


_PREFIX = "/knowledge/{asset_id}/lifecycle"


@router.post(f"{_PREFIX}/archive-request", response_model=LifecycleActionResponse)
async def archive_request(
    asset_id: uuid.UUID,
    body: ArchiveRequestBody,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> LifecycleActionResponse:
    return await lifecycle_service.archive_request(
        session, caller, asset_id, body, get_trace_id(request)
    )


@router.post(f"{_PREFIX}/archive-confirm", response_model=ArchiveConfirmResponse)
async def archive_confirm(
    asset_id: uuid.UUID,
    body: ArchiveConfirmBody,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ArchiveConfirmResponse:
    return await lifecycle_service.archive_confirm(
        session, caller, asset_id, body, get_trace_id(request)
    )


@router.post(f"{_PREFIX}/reenable-request", response_model=LifecycleActionResponse)
async def reenable_request(
    asset_id: uuid.UUID,
    body: ReenableRequestBody,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> LifecycleActionResponse:
    return await lifecycle_service.reenable_request(
        session, caller, asset_id, body, get_trace_id(request)
    )


@router.post(f"{_PREFIX}/reenable-confirm", response_model=ReenableConfirmResponse)
async def reenable_confirm(
    asset_id: uuid.UUID,
    body: ReenableConfirmBody,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ReenableConfirmResponse:
    return await lifecycle_service.reenable_confirm(
        session, caller, asset_id, body, get_trace_id(request)
    )


@router.get(f"{_PREFIX}/events", response_model=LifecycleEventsResponse)
async def list_events(
    asset_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> LifecycleEventsResponse:
    return await lifecycle_service.list_events(session, caller, asset_id)
