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
from app.schemas.bulk_operations import BulkOperationResponse, ReviewBulkActionRequest
from app.schemas.enums import AuditAction
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
from app.services import bulk_operations as bulk_service
from app.services import review as review_service
from app.services.storage import LocalFileStorage, get_storage
from app.services.weknora_client import (
    NullWeKnoraClient,
    WeKnoraClient,
    get_weknora_client,
)

router = APIRouter(prefix="/api/v1", tags=["review"])


@router.post("/reviews/bulk-action", response_model=BulkOperationResponse)
async def bulk_review_action(
    req: ReviewBulkActionRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
    weknora: WeKnoraClient | NullWeKnoraClient = Depends(get_weknora_client),
) -> BulkOperationResponse:
    """逐项复用单项审核语义；并发变化只跳过对应项。"""
    from fastapi import HTTPException

    operation_id = uuid.uuid4()
    trace_id = get_trace_id(request)

    async def process_batch(batch):
        batch_results = []
        for review_id in batch:
            try:
                if req.action == "approve":
                    await review_service.approve(
                        session,
                        caller,
                        review_id,
                        req.review_comment,
                        trace_id,
                        storage=storage,
                        weknora=weknora,
                    )
                else:
                    await review_service.reject(
                        session,
                        caller,
                        review_id,
                        (req.review_comment or "").strip(),
                        trace_id,
                    )
                batch_results.append(
                    bulk_service.BulkItemResult(item_id=review_id, status="succeeded")
                )
            except HTTPException as exc:
                await session.rollback()
                batch_results.append(bulk_service.skipped_from_http(review_id, exc))
            except Exception:
                await session.rollback()
                batch_results.append(bulk_service.failed_item(review_id))
        return batch_results

    results = await bulk_service.execute_in_controlled_batches(req.item_ids, process_batch)
    response = bulk_service.terminal_response(operation_id, req.item_ids, results)
    await bulk_service.record_terminal_audit(
        session,
        caller=caller,
        action=AuditAction.review_bulk_decided.value,
        trace_id=trace_id,
        response=response,
        operation=req.action,
        target_scope="review_queue",
        client_operation_id=req.client_operation_id,
        request_index=req.request_index,
        request_count=req.request_count,
        total_submitted=req.total_submitted,
    )
    return response


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
