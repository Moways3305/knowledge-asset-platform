"""Explicit MCP operation adapters; reuse first-party workflows, never impersonate via headers.

Legacy qa tokens remain read-only. Only user-issued, unrestricted operations credentials
are accepted here; managed registry ceilings must not be bypassed by first-party workflows.
Large file bytes use multipart HTTP with the same bearer, not the bounded MCP JSON channel.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api import ingest as ingest_api
from app.api.agent_gateway import require_bound_caller
from app.core.errors import denied
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.models.ingest import IngestTask
from app.models.review import ReviewTask
from app.schemas.enums import KnowledgeScope
from app.schemas.ingest import IngestConfirmRequest, UploadSessionInitRequest
from app.schemas.naming import NamingPreviewRequest
from app.services import agent_workbench, naming_rules, review
from app.services.desensitization import get_desensitizer
from app.services.generation_models import get_generation_llm_client
from app.services.storage import get_storage
from app.services.upload_session_types import (
    SINGLE_FILE_MAX_BYTES,
    TRANSPORT_BATCH_MAX_BYTES,
    TRANSPORT_BATCH_MAX_FILES,
)
from app.services.weknora_client import get_weknora_client

router = APIRouter(prefix="/api/v1/agent-gateway/operations", tags=["agent-operations"])


async def operation_context(
    bound=Depends(require_bound_caller),
    session=Depends(get_db),
    storage=Depends(get_storage),
    llm=Depends(get_generation_llm_client),
    desensitizer=Depends(get_desensitizer),
    weknora=Depends(get_weknora_client),
):
    rule, caller = bound
    if (
        rule.capability != "qa_operations"
        or not rule.is_self_service
        or rule.provider != "workbuddy"
        or rule.allowed_scope not in (None, "all")
        or rule.allowed_project_id is not None
    ):
        raise denied(403, "agent_operations_disabled", "请由本人生成启用操作权限的 MCP 凭证")
    return dict(
        session=session,
        caller=caller,
        storage=storage,
        llm=llm,
        desensitizer=desensitizer,
        weknora=weknora,
        rule=rule,
    )


def upload_context(ctx):
    return {key: ctx[key] for key in ("session", "caller", "storage", "llm", "desensitizer")}


@router.get("/naming-options")
async def naming_options(
    scope: KnowledgeScope, project_id: uuid.UUID | None = None, ctx=Depends(operation_context)
):
    return await naming_rules.options(ctx["session"], ctx["caller"], scope, project_id)


@router.post("/ingest/{task_id}/naming-preview")
async def naming_preview(
    task_id: uuid.UUID, body: NamingPreviewRequest, ctx=Depends(operation_context)
):
    await owned_task(ctx, task_id)
    return await naming_rules.preview(ctx["session"], ctx["caller"], task_id, body)


class ConfirmCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: datetime
    confirmed: Literal[True]
    confirmation: IngestConfirmRequest


class ReviewCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: datetime
    confirmed: Literal[True]
    action: Literal["approve", "reject", "withdraw"]
    comment: str = Field(min_length=1, max_length=2000, pattern=r"\S")


def check_version(actual, expected):
    def utc(value):
        return (
            value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None
            else value.astimezone(timezone.utc)
        )

    if utc(actual) != utc(expected):
        raise denied(409, "agent_operation_stale", "资料已变化，请重新读取后确认；不要盲目重试")


async def owned_task(ctx, task_id, *, lock=False):
    query = select(IngestTask).where(
        IngestTask.id == task_id, IngestTask.created_by == ctx["caller"].user_id
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    task = await ctx["session"].scalar(query)
    if task is None:
        raise denied(404, "ingest_not_found", "入库任务不存在或不可访问")
    return task


@router.post("/uploads/init")
async def init_upload(
    body: UploadSessionInitRequest, request: Request, ctx=Depends(operation_context)
):
    result = await ingest_api.initialize_upload_session(
        body=body, request=request, **upload_context(ctx)
    )
    return {
        "session": result.model_dump(mode="json"),
        "transport": {
            "method": "POST",
            "path": f"/api/v1/agent-gateway/operations/uploads/{result.id}/batches",
            "content_type": "multipart/form-data",
            "authentication": "same_bearer",
            "fields": ["batch_id", "batch_index", "item_ids (JSON array)", "files"],
            "max_files_per_batch": TRANSPORT_BATCH_MAX_FILES,
            "max_file_bytes": SINGLE_FILE_MAX_BYTES,
            "max_batch_bytes": TRANSPORT_BATCH_MAX_BYTES,
            "single_file_batch_exception": {
                "file_count": 1,
                "max_batch_bytes": SINGLE_FILE_MAX_BYTES,
            },
        },
    }


@router.post("/uploads/{session_id}/batches")
async def upload_batch(
    session_id: uuid.UUID,
    request: Request,
    batch_id: str = Form(),
    batch_index: int = Form(),
    item_ids: str = Form(),
    files: list[UploadFile] = File(),
    ctx=Depends(operation_context),
):
    return await ingest_api.append_upload_transport_batch(
        session_id=session_id,
        request=request,
        batch_id=batch_id,
        batch_index=batch_index,
        item_ids=item_ids,
        files=files,
        **upload_context(ctx),
    )


@router.post("/uploads/{session_id}/complete")
async def complete_upload(session_id: uuid.UUID, request: Request, ctx=Depends(operation_context)):
    return await ingest_api.complete_upload_transport_session(
        session_id=session_id, request=request, **upload_context(ctx)
    )


@router.get("/uploads/{session_id}")
async def upload_status(session_id: uuid.UUID, request: Request, ctx=Depends(operation_context)):
    return await ingest_api.get_upload_session(
        session_id=session_id, request=request, **upload_context(ctx)
    )


@router.get("/ingest/{task_id}")
async def ingest_detail(task_id: uuid.UUID, ctx=Depends(operation_context)):
    task = await owned_task(ctx, task_id)
    progress = await ingest_api.get_task_status(
        task_id, caller=ctx["caller"], session=ctx["session"], storage=ctx["storage"]
    )
    ai = await ingest_api.get_ai_result(task_id, caller=ctx["caller"], session=ctx["session"])
    safe_fields = {
        "suggested_title",
        "suggested_one_liner",
        "suggested_summary",
        "suggested_key_points",
        "suggested_tags",
        "suggested_formed_on",
        "suggested_confidentiality_level",
        "status",
    }
    return {
        "task_id": str(task.id),
        "expected_updated_at": task.updated_at.isoformat(),
        "progress": progress.model_dump(mode="json"),
        "suggestions": ai.model_dump(mode="json", include=safe_fields),
    }


@router.post("/ingest/{task_id}/confirm")
async def confirm_ingest(
    task_id: uuid.UUID, body: ConfirmCommand, request: Request, ctx=Depends(operation_context)
):
    task = await owned_task(ctx, task_id, lock=True)
    check_version(task.updated_at, body.expected_updated_at)
    return await ingest_api.confirm(
        task_id=task_id,
        req=body.confirmation,
        request=request,
        caller=ctx["caller"],
        session=ctx["session"],
        storage=ctx["storage"],
        weknora=ctx["weknora"],
    )


async def visible_review(ctx, review_id, *, lock=False):
    detail = await review.get_review(ctx["session"], ctx["caller"], review_id)
    # Preserve agent-channel visibility in addition to the workflow's own reviewer rules.
    if detail.target_asset_id:
        await agent_workbench.get_knowledge_summary(
            ctx["session"], ctx["caller"], ctx["rule"], detail.target_asset_id
        )
    query = select(ReviewTask).where(ReviewTask.id == review_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    task = await ctx["session"].scalar(query)
    return detail, task


@router.get("/reviews/{review_id}")
async def review_detail(review_id: uuid.UUID, ctx=Depends(operation_context)):
    detail, task = await visible_review(ctx, review_id)
    return {
        "review": detail.model_dump(mode="json"),
        "expected_updated_at": task.updated_at.isoformat(),
    }


@router.post("/reviews/{review_id}/decision")
async def decide_review(
    review_id: uuid.UUID, body: ReviewCommand, request: Request, ctx=Depends(operation_context)
):
    _, task = await visible_review(ctx, review_id, lock=True)
    check_version(task.updated_at, body.expected_updated_at)
    args = (ctx["session"], ctx["caller"], review_id, body.comment, get_trace_id(request))
    if body.action == "approve":
        return await review.approve(*args, storage=ctx["storage"], weknora=ctx["weknora"])
    if body.action == "reject":
        return await review.reject(*args)
    return await review.withdraw_review(*args)
