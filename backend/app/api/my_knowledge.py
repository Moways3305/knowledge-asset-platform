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
from app.schemas.my_knowledge import (
    ConfirmAssetResponse,
    PersonalKnowledgeItemOut,
    PersonalKnowledgeSubmissionOut,
    PersonalKnowledgeUpdateRequest,
    SubmitToProjectRequest,
    ValidationCandidateRequest,
)
from app.schemas.permission import CallerContext
from app.services import my_knowledge as my_knowledge_service

router = APIRouter(prefix="/api/v1/my/knowledge", tags=["my-knowledge"])


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
