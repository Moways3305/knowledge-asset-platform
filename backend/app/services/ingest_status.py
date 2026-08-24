"""Permission-safe progress and recovery contract for a single ingest task."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import safe_log_exception
from app.models.ingest import IngestTask
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.review import ReviewTask
from app.schemas.enums import AuditAction, AuditLogType, IngestStatus, ProjectRole
from app.schemas.ingest import (
    IngestTaskNextAction,
    IngestTaskSafeError,
    IngestTaskStage,
    IngestTaskStatusResponse,
    IngestTaskWorkflowStatus,
)
from app.schemas.permission import CallerContext
from app.services import audit as audit_service
from app.services import error_catalog, indexing
from app.services import knowledge as knowledge_service
from app.services.desensitization import DesensitizationEngine
from app.services.llm_client import LLMClient, NullLLMClient, safe_llm_diagnostic
from app.services.storage import LocalFileStorage
from app.services.weknora_client import NullWeKnoraClient, WeKnoraClient
from app.worker.enqueue import enqueue_ingest_processing

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _TaskContext:
    task: IngestTask
    review: ReviewTask | None
    asset: KnowledgeAsset | None
    version: KnowledgeAssetVersion | None


_SAFE_ERRORS = {
    "ingest_processing_failed": (
        "文件处理暂时失败。",
        "稍后重试；若持续失败，请联系管理员检查后台任务与文件存储。",
    ),
    "file_format_unsupported": (
        "当前文件格式不支持自动提取，文件仍已保存。",
        "人工补全标题和摘要后继续，或重新上传受支持的文本、PDF、DOCX 文件。",
    ),
    "file_parse_failed": (
        "文件内容无法解析。",
        "请确认文件未损坏且扩展名正确，然后重新上传。",
    ),
    "file_text_unavailable": (
        "文件中未提取到可用文本。",
        "请检查扫描清晰度后重试 OCR，或替换原文。",
    ),
    "ocr_failed": ("OCR 识别未完成，原文已保留。", "检查 OCR 服务或原文清晰度后重试此文件。"),
    "content_generation_unavailable": (
        "内容建议未生成，已保留原文和前置处理结果。",
        "请管理员修复内容生成模型配置，系统将从内容生成阶段恢复。",
    ),
    "review_rejected": (
        "本次入库确认未通过审核。",
        "根据审核意见修改内容后重新提交。",
    ),
    "indexing_skipped": (
        "资产已保存，但当前未进入知识底座索引。",
        "底座可用后可由具备权限的人员重试索引。",
    ),
    "weknora_parse_failed": (
        "资产已进入知识底座，但正文解析失败。",
        "可重新解析；若持续失败，请检查源文件格式或联系管理员。",
    ),
}


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"denied_reason": "ingest_task_not_found", "message": "入库任务不存在或不可见"},
    )


def _action(key: str, route_key: str | None, *, enabled: bool = True) -> IngestTaskNextAction:
    return IngestTaskNextAction(key=key, route_key=route_key, enabled=enabled)


def _safe_error(code: str) -> IngestTaskSafeError:
    message, hint = _SAFE_ERRORS[code]
    return IngestTaskSafeError(code=code, message=message, recovery_hint=hint)


def _index_error(code: str | None) -> IngestTaskSafeError:
    safe_code = error_catalog.safe_code(code)
    return IngestTaskSafeError(
        code=safe_code,
        message=error_catalog.user_message(safe_code),
        recovery_hint="稍后重试；若持续失败，请联系管理员检查知识底座配置与服务状态。",
    )


async def _load_context(
    session: AsyncSession, caller: CallerContext, task_id: uuid.UUID
) -> _TaskContext:
    task = (
        await session.execute(
            select(IngestTask)
            .where(IngestTask.id == task_id)
            .options(
                selectinload(IngestTask.ai_result),
                selectinload(IngestTask.canonical_markdown),
            )
        )
    ).scalar_one_or_none()
    if task is None or not caller.is_business_user:
        raise _not_found()

    review = (
        await session.execute(select(ReviewTask).where(ReviewTask.source_ingest_task_id == task.id))
    ).scalar_one_or_none()
    can_view_review = bool(
        review
        and (
            review.reviewer_user_id == caller.user_id
            or (
                review.target_project_id is not None
                and caller.active_project_roles.get(review.target_project_id)
                == ProjectRole.project_manager.value
            )
        )
    )
    if not (task.created_by == caller.user_id or caller.can_discover_l5 or can_view_review):
        raise _not_found()

    asset = None
    version = None
    if task.result_asset_id is not None:
        asset = await session.get(KnowledgeAsset, task.result_asset_id)
        version = (
            await session.execute(
                select(KnowledgeAssetVersion).where(
                    KnowledgeAssetVersion.asset_id == task.result_asset_id,
                    KnowledgeAssetVersion.version_status == "active",
                )
            )
        ).scalar_one_or_none()
    return _TaskContext(task=task, review=review, asset=asset, version=version)


def _generation_degraded(task: IngestTask) -> bool:
    ai = task.ai_result
    if ai is None:
        return True
    fields = ai.naming_parsed_fields if isinstance(ai.naming_parsed_fields, dict) else {}
    return fields.get("generation_status") != "generated"


def _generation_response_retryable(task: IngestTask) -> bool:
    ai = task.ai_result
    if ai is None or ai.extraction_status != "extracted":
        return False
    fields = ai.naming_parsed_fields if isinstance(ai.naming_parsed_fields, dict) else {}
    category = fields.get("generation_error_category")
    return (
        isinstance(category, str)
        and fields.get("generation_status") == "failed"
        and (safe_llm_diagnostic(category).retryable or category == "response_error")
    )


def _generation_error(task: IngestTask) -> IngestTaskSafeError:
    ai = task.ai_result
    fields = ai.naming_parsed_fields if ai and isinstance(ai.naming_parsed_fields, dict) else {}
    category = fields.get("generation_error_category")
    if not isinstance(category, str):
        return _safe_error("content_generation_unavailable")
    diagnostic = safe_llm_diagnostic(category)
    return IngestTaskSafeError(
        code=diagnostic.category,
        message=diagnostic.message,
        recovery_hint=diagnostic.remediation_hint,
    )


def _response(ctx: _TaskContext, caller: CallerContext) -> IngestTaskStatusResponse:
    task, review, asset, version = ctx.task, ctx.review, ctx.asset, ctx.version
    stage = IngestTaskStage.upload_saved
    status = IngestTaskWorkflowStatus.processing
    retryable = False
    next_action = _action("wait", None, enabled=False)
    error = None

    if task.status in {IngestStatus.pending.value, IngestStatus.processing.value}:
        stage_value = task.processing_stage or (
            "upload_saved" if task.status == IngestStatus.pending.value else "text_extraction"
        )
        stage = (
            IngestTaskStage(stage_value)
            if stage_value in {item.value for item in IngestTaskStage}
            else IngestTaskStage.text_extraction
        )
        if task.error_type == "processing_error":
            stage = IngestTaskStage.failed
            status = IngestTaskWorkflowStatus.failed
            retryable = task.created_by == caller.user_id or caller.can_discover_l5
            error = _safe_error("ingest_processing_failed")
            next_action = _action("retry_processing", "ingest_task_retry", enabled=retryable)
    elif task.status == IngestStatus.pending_confirmation.value:
        extraction_status = task.ai_result.extraction_status if task.ai_result else None
        if extraction_status == "unsupported":
            stage = IngestTaskStage.degraded_complete
            status = IngestTaskWorkflowStatus.degraded
            error = _safe_error("file_format_unsupported")
        elif _generation_degraded(task):
            stage = IngestTaskStage.degraded_complete
            status = IngestTaskWorkflowStatus.degraded
            error = _generation_error(task)
            retryable = bool(
                _generation_response_retryable(task)
                and (task.created_by == caller.user_id or caller.can_discover_l5)
            )
        else:
            stage = IngestTaskStage.awaiting_confirmation
            status = IngestTaskWorkflowStatus.action_required
        next_action = (
            _action("retry_processing", "ingest_task_retry")
            if retryable
            else _action("review_and_confirm", "upload_task")
        )
    elif task.status == IngestStatus.waiting_review.value:
        stage = IngestTaskStage.confirmation
        status = IngestTaskWorkflowStatus.waiting
        next_action = _action("view_review", "reviews", enabled=review is not None)
    elif task.status == IngestStatus.rejected.value:
        stage = IngestTaskStage.failed
        status = IngestTaskWorkflowStatus.action_required
        error = _safe_error("review_rejected")
        next_action = _action("edit_and_resubmit", "upload_task")
    elif task.status == IngestStatus.failed.value:
        stage_value = task.processing_stage or "failed"
        stage = (
            IngestTaskStage(stage_value)
            if stage_value in {item.value for item in IngestTaskStage}
            else IngestTaskStage.failed
        )
        status = IngestTaskWorkflowStatus.failed
        if task.error_type == "processing_error":
            retryable = task.created_by == caller.user_id or caller.can_discover_l5
            error = _safe_error("ingest_processing_failed")
            next_action = _action("retry_processing", "ingest_task_retry", enabled=retryable)
        elif task.processing_stage == "ocr_failed":
            retryable = task.created_by == caller.user_id or caller.can_discover_l5
            error = _safe_error("ocr_failed")
            next_action = _action("retry_ocr", "ingest_task_retry", enabled=retryable)
        elif task.processing_stage in {"waiting_generation_config", "content_generation_failed"}:
            retryable = bool(
                _generation_response_retryable(task)
                and (task.created_by == caller.user_id or caller.can_discover_l5)
            )
            error = _generation_error(task)
            next_action = _action("retry_generation", "ingest_task_retry", enabled=retryable)
        elif task.error_type == "extraction_empty":
            error = _safe_error("file_text_unavailable")
            next_action = _action("replace_file", "upload")
        else:
            error = _safe_error("file_parse_failed")
            next_action = _action("replace_file", "upload")
    elif task.status == IngestStatus.completed.value:
        can_retry_index = bool(asset and knowledge_service.can_retry_index(caller, asset))
        if version is None or version.index_status in {"not_indexed", "indexing"}:
            stage = (
                IngestTaskStage.indexing_queued
                if version is None or version.index_status == "not_indexed"
                else IngestTaskStage.indexing_in_progress
            )
            status = IngestTaskWorkflowStatus.processing
            next_action = _action("wait", None, enabled=False)
        elif version.weknora_parse_status == "failed" and version.weknora_doc_id is not None:
            stage = IngestTaskStage.failed
            status = IngestTaskWorkflowStatus.failed
            retryable = can_retry_index
            error = _safe_error("weknora_parse_failed")
            next_action = _action("reparse", "ingest_task_retry", enabled=retryable)
        elif version.index_status == "index_failed":
            stage = IngestTaskStage.failed
            status = IngestTaskWorkflowStatus.failed
            retryable = can_retry_index
            error = _index_error(version.index_error_code)
            next_action = _action("retry_index", "ingest_task_retry", enabled=retryable)
        elif version.index_status == "skipped":
            stage = IngestTaskStage.degraded_complete
            status = IngestTaskWorkflowStatus.degraded
            retryable = can_retry_index
            error = _safe_error("indexing_skipped")
            next_action = (
                _action("retry_index", "ingest_task_retry")
                if retryable
                else _action("view_asset", "knowledge_detail", enabled=asset is not None)
            )
        elif version.weknora_parse_status == "pending":
            stage = IngestTaskStage.indexing_queued
            status = IngestTaskWorkflowStatus.processing
            next_action = _action("wait", None, enabled=False)
        elif version.weknora_parse_status == "processing":
            stage = IngestTaskStage.indexing_in_progress
            status = IngestTaskWorkflowStatus.processing
            next_action = _action("wait", None, enabled=False)
        else:
            stage = IngestTaskStage.completed
            status = IngestTaskWorkflowStatus.completed
            next_action = _action("view_asset", "knowledge_detail", enabled=asset is not None)

    return IngestTaskStatusResponse(
        task_id=task.id,
        stage=stage,
        status=status,
        updated_at=task.updated_at,
        retryable=retryable,
        next_action=next_action,
        error=error,
        result_asset_id=task.result_asset_id,
        review_id=review.id if review else None,
    )


async def get_task_status(
    session: AsyncSession, caller: CallerContext, task_id: uuid.UUID
) -> IngestTaskStatusResponse:
    return _response(await _load_context(session, caller, task_id), caller)


async def retry_task(
    session: AsyncSession,
    caller: CallerContext,
    task_id: uuid.UUID,
    *,
    storage: LocalFileStorage,
    llm: LLMClient | NullLLMClient,
    desensitizer: DesensitizationEngine,
    weknora: WeKnoraClient | NullWeKnoraClient,
    trace_id: str,
) -> IngestTaskStatusResponse:
    ctx = await _load_context(session, caller, task_id)
    current = _response(ctx, caller)
    if not current.retryable:
        return current

    task = ctx.task
    if task.status in {IngestStatus.pending_confirmation.value, IngestStatus.failed.value} and (
        task.processing_stage in {"waiting_generation_config", "content_generation_failed"}
        or _generation_response_retryable(task)
    ):
        claim = await session.execute(
            update(IngestTask)
            .where(
                IngestTask.id == task.id,
                IngestTask.status.in_(
                    {IngestStatus.pending_confirmation.value, IngestStatus.failed.value}
                ),
            )
            .values(
                status=IngestStatus.processing.value,
                processing_stage="content_generation",
                retry_count=0,
                error_type=None,
                error_message=None,
            )
        )
        if getattr(claim, "rowcount", 0) != 1:
            await session.rollback()
            session.expire_all()
            return await get_task_status(session, caller, task_id)
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.ingest_ai_retry_requested.value,
            trace_id=trace_id,
            target_type="ingest_task",
            target_id=task.id,
            extra={"reason": "response_error", "scope": "single_task"},
            project_id=task.target_project_id,
        )
        await session.commit()
        try:
            await enqueue_ingest_processing(
                session,
                task.id,
                storage=storage,
                llm=llm,
                desensitizer=desensitizer,
                trace_id=trace_id,
            )
        except Exception as exc:
            safe_log_exception(
                _logger,
                "ingest_ai_manual_retry_failed",
                exc,
                include_summary=False,
                task_id=str(task.id),
            )
            task.status = IngestStatus.failed.value
            task.processing_stage = "content_generation_failed"
            await session.commit()
    elif task.status == IngestStatus.failed.value and task.processing_stage == "ocr_failed":
        claim = await session.execute(
            update(IngestTask)
            .where(
                IngestTask.id == task.id,
                IngestTask.status == IngestStatus.failed.value,
                IngestTask.processing_stage == "ocr_failed",
            )
            .values(
                status=IngestStatus.processing.value,
                processing_stage="ocr_queued",
                error_type=None,
                error_message=None,
                retry_count=task.retry_count + 1,
            )
        )
        await session.commit()
        if getattr(claim, "rowcount", 0) == 1:
            try:
                await enqueue_ingest_processing(
                    session,
                    task.id,
                    storage=storage,
                    llm=llm,
                    desensitizer=desensitizer,
                    trace_id=trace_id,
                )
            except Exception as exc:
                safe_log_exception(
                    _logger, "ingest_ocr_manual_retry_failed", exc, include_summary=False
                )
                await session.execute(
                    update(IngestTask)
                    .where(IngestTask.id == task.id)
                    .values(
                        status=IngestStatus.failed.value,
                        processing_stage="ocr_failed",
                        error_type="ocr_enqueue_failed",
                        error_message="OCR 重试未发起，请稍后再试。",
                    )
                )
                await session.commit()
    elif (
        task.status in {IngestStatus.failed.value, IngestStatus.processing.value}
        and task.error_type == "processing_error"
    ):
        claim = await session.execute(
            update(IngestTask)
            .where(
                IngestTask.id == task.id,
                IngestTask.status.in_({IngestStatus.failed.value, IngestStatus.processing.value}),
                IngestTask.error_type == "processing_error",
            )
            .values(
                status=IngestStatus.processing.value,
                processing_stage=(
                    "content_generation"
                    if task.canonical_markdown and task.canonical_markdown.status == "ready"
                    else "text_extraction"
                ),
                retry_count=0,
                error_type=None,
                error_message=None,
            )
        )
        await session.commit()
        if getattr(claim, "rowcount", 0) != 1:
            session.expire_all()
            return await get_task_status(session, caller, task_id)
        try:
            await enqueue_ingest_processing(
                session,
                task.id,
                storage=storage,
                llm=llm,
                desensitizer=desensitizer,
                trace_id=trace_id,
            )
        except Exception as exc:
            safe_log_exception(
                _logger,
                "ingest_manual_retry_failed",
                exc,
                include_summary=False,
                task_id=str(task.id),
            )
            task.status = IngestStatus.failed.value
            task.processing_stage = None
            task.error_type = "processing_error"
            task.error_message = "入库处理失败（详见审计）"
            await session.commit()
    elif ctx.asset is not None and ctx.version is not None:
        if ctx.version.weknora_parse_status == "failed" and ctx.version.weknora_doc_id is not None:
            try:
                from app.services.canonical_markdown import ensure_version_markdown

                markdown = await ensure_version_markdown(
                    session,
                    storage,
                    asset_id=ctx.asset.id,
                    version_id=ctx.version.id,
                )
            except Exception as exc:
                await indexing.mark_index_failed(
                    session,
                    version_id=ctx.version.id,
                    error_code=getattr(exc, "code", "canonical_markdown_unavailable"),
                )
            else:
                await indexing.reparse_asset_version(
                    session,
                    weknora,
                    asset_id=ctx.asset.id,
                    version_id=ctx.version.id,
                    scope=ctx.asset.scope,
                    owner_user_id=ctx.asset.owner_user_id,
                    project_id=ctx.asset.project_id,
                    confidentiality=ctx.asset.confidentiality_level,
                    file_bytes=markdown.content,
                    source_file_name=markdown.file_name,
                    source_file_mime=markdown.mime,
                    channel=markdown.channel,
                    trace_id=trace_id,
                )
        else:
            await knowledge_service.retry_index(
                session,
                caller,
                ctx.asset.id,
                weknora=weknora,
                storage=storage,
                trace_id=trace_id,
            )
    return await get_task_status(session, caller, task_id)


async def resume_waiting_generation_tasks(
    session: AsyncSession,
    *,
    storage: LocalFileStorage,
    llm: LLMClient | NullLLMClient,
    desensitizer: DesensitizationEngine,
    trace_id: str,
) -> int:
    """默认模型恢复后自动推进等待任务；每任务仍由作业幂等复核。"""
    if isinstance(llm, NullLLMClient):
        return 0
    task_ids = list(
        (
            await session.execute(
                select(IngestTask.id)
                .where(
                    IngestTask.status == IngestStatus.failed.value,
                    IngestTask.processing_stage == "waiting_generation_config",
                )
                .order_by(IngestTask.updated_at)
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    resumed = 0
    for task_id in task_ids:
        claim = await session.execute(
            update(IngestTask)
            .where(
                IngestTask.id == task_id,
                IngestTask.status == IngestStatus.failed.value,
                IngestTask.processing_stage == "waiting_generation_config",
            )
            .values(
                status=IngestStatus.processing.value,
                processing_stage="content_generation",
                error_type=None,
                error_message=None,
            )
        )
        await session.commit()
        if getattr(claim, "rowcount", 0) != 1:
            continue
        try:
            await enqueue_ingest_processing(
                session,
                task_id,
                storage=storage,
                llm=llm,
                desensitizer=desensitizer,
                trace_id=trace_id,
            )
        except Exception as exc:  # one task must not block the remaining recovery set
            safe_log_exception(
                _logger,
                "ingest_generation_auto_resume_failed",
                exc,
                include_summary=False,
                task_id=str(task_id),
            )
            await session.execute(
                update(IngestTask)
                .where(IngestTask.id == task_id)
                .values(
                    status=IngestStatus.failed.value,
                    processing_stage="content_generation_failed",
                    error_type="queue_unavailable",
                    error_message="内容生成恢复任务暂时无法排队。",
                )
            )
            await session.commit()
        else:
            resumed += 1
    return resumed
