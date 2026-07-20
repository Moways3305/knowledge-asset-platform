"""审核流 API。

权限/状态判断全部委托 `app.services.review`。不写审计、不通知、不调用 Agent。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.permission import CallerContext
from app.schemas.review import (
    EvidenceCreateRequest,
    EvidenceOut,
    ReviewActionRequest,
    ReviewActionResponse,
    ReviewDetail,
    ReviewListItem,
    ReviewListResponse,
    ReviewRejectRequest,
    ReviewWithdrawRequest,
)
from app.services import review as review_service
from app.services.storage import LocalFileStorage, get_storage
from app.services.weknora_client import (
    NullWeKnoraClient,
    WeKnoraClient,
    get_weknora_client,
)

router = APIRouter(prefix="/api/v1", tags=["review"])


@router.get("/reviews", response_model=ReviewListResponse)
async def list_reviews(
    review_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ReviewListResponse:
    items = await review_service.list_reviews(
        session, caller, review_type=review_type, status=status
    )
    return ReviewListResponse(items=items, total=len(items))


@router.get("/reviews/{review_id}", response_model=ReviewDetail)
async def get_review(
    review_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ReviewDetail:
    return await review_service.get_review(session, caller, review_id)


@router.post("/projects/{project_id}/knowledge/{asset_id}/evidence", response_model=EvidenceOut)
async def register_evidence(
    project_id: uuid.UUID,
    asset_id: uuid.UUID,
    req: EvidenceCreateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> EvidenceOut:
    return await review_service.register_evidence(
        session, caller, project_id, asset_id, req, get_trace_id(request)
    )


@router.post(
    "/projects/{project_id}/knowledge/{asset_id}/confirm-asset",
    response_model=ReviewListItem,
)
async def confirm_asset(
    project_id: uuid.UUID,
    asset_id: uuid.UUID,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ReviewListItem:
    return await review_service.create_or_get_confirm_asset(
        session, caller, project_id, asset_id, get_trace_id(request)
    )


@router.post(
    "/projects/{project_id}/knowledge/{asset_id}/upgrade-company",
    response_model=ReviewListItem,
)
async def request_company_upgrade(
    project_id: uuid.UUID,
    asset_id: uuid.UUID,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ReviewListItem:
    return await review_service.create_or_get_company_upgrade(
        session, caller, project_id, asset_id, get_trace_id(request)
    )


@router.post("/reviews/{review_id}/approve", response_model=ReviewActionResponse)
async def approve_review(
    review_id: uuid.UUID,
    request: Request,
    req: ReviewActionRequest | None = None,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
    weknora: WeKnoraClient | NullWeKnoraClient = Depends(get_weknora_client),
) -> ReviewActionResponse:
    comment = req.review_comment if req else None
    return await review_service.approve(
        session,
        caller,
        review_id,
        comment,
        get_trace_id(request),
        storage=storage,
        weknora=weknora,
    )


@router.post("/reviews/{review_id}/reject", response_model=ReviewActionResponse)
async def reject_review(
    review_id: uuid.UUID,
    req: ReviewRejectRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ReviewActionResponse:
    return await review_service.reject(
        session, caller, review_id, req.review_comment, get_trace_id(request)
    )


@router.post("/reviews/{review_id}/withdraw", response_model=ReviewActionResponse)
async def withdraw_review_confirmation(
    review_id: uuid.UUID,
    req: ReviewWithdrawRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ReviewActionResponse:
    return await review_service.withdraw_company_confirmation(
        session, caller, review_id, req.review_comment, get_trace_id(request)
    )
