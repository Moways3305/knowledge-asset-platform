"""个人知识写动作 API。

- POST /api/v1/my/knowledge/{asset_id}/confirm-asset          （本人 material → asset，幂等）
- POST /api/v1/my/knowledge/{asset_id}/submit-to-project      （提交进项目资料区 + 审核任务）
- POST /api/v1/my/knowledge/{asset_id}/validation-evidence    （内部分享 / 客户验证候选）

仅 owner 本人可操作；写动作支持 Idempotency-Key header 防重复。响应只含安全治理元数据。
个人知识只读列表 `GET /api/v1/my/knowledge` 仍在 `app/api/knowledge.py`。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.bulk_operations import BulkOperationResponse, PersonalSubmitBulkRequest
from app.schemas.enums import AuditAction
from app.schemas.my_knowledge import (
    ConfirmAssetResponse,
    PersonalKnowledgeItemOut,
    PersonalKnowledgeSubmissionOut,
    PersonalKnowledgeUpdateRequest,
    SubmitToProjectRequest,
    ValidationCandidateRequest,
)
from app.schemas.permission import CallerContext
from app.services import bulk_operations as bulk_service
from app.services import my_knowledge as my_knowledge_service

router = APIRouter(prefix="/api/v1/my/knowledge", tags=["my-knowledge"])


@router.post("/bulk-submit-to-project", response_model=BulkOperationResponse)
async def bulk_submit_to_project(
    req: PersonalSubmitBulkRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> BulkOperationResponse:
    """逐项复用个人知识提交服务，并对目标项目和成员资格重新校验。"""
    from fastapi import HTTPException

    operation_id = uuid.uuid4()
    trace_id = get_trace_id(request)
    single_request = SubmitToProjectRequest(target_project_id=req.target_project_id, note=req.note)

    async def process_batch(batch):
        batch_results = []
        for asset_id in batch:
            try:
                await my_knowledge_service.submit_to_project(
                    session,
                    caller,
                    asset_id,
                    single_request,
                    trace_id,
                    f"bulk:{operation_id}:{asset_id}",
                )
                batch_results.append(
                    bulk_service.BulkItemResult(item_id=asset_id, status="succeeded")
                )
            except HTTPException as exc:
                await session.rollback()
                batch_results.append(bulk_service.skipped_from_http(asset_id, exc))
            except Exception:
                await session.rollback()
                batch_results.append(bulk_service.failed_item(asset_id))
        return batch_results

    results = await bulk_service.execute_in_controlled_batches(req.item_ids, process_batch)
    response = bulk_service.terminal_response(operation_id, req.item_ids, results)
    await bulk_service.record_terminal_audit(
        session,
        caller=caller,
        action=AuditAction.personal_knowledge_bulk_submitted.value,
        trace_id=trace_id,
        response=response,
        operation="submit_to_project",
        target_scope="project",
        project_id=req.target_project_id,
        client_operation_id=req.client_operation_id,
        request_index=req.request_index,
        request_count=req.request_count,
        total_submitted=req.total_submitted,
    )
    return response


@router.patch("/{asset_id}", response_model=PersonalKnowledgeItemOut)
async def update_personal_knowledge(
    asset_id: uuid.UUID,
    body: PersonalKnowledgeUpdateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> PersonalKnowledgeItemOut:
    return await my_knowledge_service.update_personal_asset(
        session, caller, asset_id, body, get_trace_id(request)
    )


@router.post("/{asset_id}/confirm-asset", response_model=ConfirmAssetResponse)
async def confirm_personal_asset(
    asset_id: uuid.UUID,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ConfirmAssetResponse:
    return await my_knowledge_service.confirm_asset(
        session, caller, asset_id, get_trace_id(request)
    )


@router.post("/{asset_id}/submit-to-project", response_model=PersonalKnowledgeSubmissionOut)
async def submit_to_project(
    asset_id: uuid.UUID,
    req: SubmitToProjectRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> PersonalKnowledgeSubmissionOut:
    return await my_knowledge_service.submit_to_project(
        session, caller, asset_id, req, get_trace_id(request), idempotency_key
    )


@router.post("/{asset_id}/validation-evidence", response_model=PersonalKnowledgeSubmissionOut)
async def register_validation_candidate(
    asset_id: uuid.UUID,
    req: ValidationCandidateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> PersonalKnowledgeSubmissionOut:
    return await my_knowledge_service.register_validation_candidate(
        session, caller, asset_id, req, get_trace_id(request), idempotency_key
    )
