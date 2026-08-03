"""入库流水线服务。

create_upload → 确定性 AI 建议占位 → get_ai_result（按权限裁剪）→ confirm（人工确认
后写入 KnowledgeAsset 全套）。不调用真实 AI / 文件存储 / WeCom / Dify / 审核流 / 审计表。
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingest import IngestTask, IngestTaskAiResult, UploadSession, UploadSessionItem
from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetTag,
    KnowledgeAssetVersion,
)
from app.models.review import (
    CompanyAssetReviewDecision,
    PersonalKnowledgeSubmission,
    ReviewTask,
    ReviewTaskEvidence,
)
from app.schemas.enums import (
    AlertSeverity,
    AuditAction,
    AuditLogType,
    AuditRiskLevel,
    IngestSource,
    IngestStatus,
    KnowledgeScope,
    ReviewTaskStatus,
    ReviewType,
)
from app.schemas.ingest import (
    AdminIngestItem,
    IngestAiResultResponse,
    IngestConfirmRequest,
    IngestConfirmResponse,
    IngestUploadResponse,
    PendingIngestItem,
)
from app.schemas.naming import NamingPreviewRequest
from app.schemas.permission import CallerContext
from app.schemas.review import ReviewActionResponse
from app.services import audit as audit_service
from app.services import ingest_confirmation, ingest_indexing, ingest_persistence
from app.services.desensitization import DesensitizationEngine
from app.services.generation_models import generation_model_ref
from app.services.llm_client import LLMClient, NullLLMClient
from app.services.naming_advice import safe_naming_advice
from app.services.storage import LocalFileStorage, StorageError
from app.services.suggested_subject import suggested_subject
from app.services.weknora_client import (
    NullWeKnoraClient,
    WeKnoraClient,
    WeKnoraError,
    weknora_enabled,
)
from app.worker.enqueue import enqueue_ingest_processing

if TYPE_CHECKING:
    # 运行时延迟到函数体内导入（避免与 schemas.ingest 的环依赖），此处仅供类型标注。
    from app.schemas.ingest import IngestParseRefreshResponse

_logger = logging.getLogger(__name__)

# 入库前置脱敏状态 → 人读安全文案。当前口径：入库建议由受信外部 API 处理，未启用前置脱敏
# （not_applicable）。规则脱敏引擎保留为备用。applied/unchanged/skipped/failed 仅为兼容历史
# 数据行的旧状态，新任务不再产生。
_DESENSITIZATION_MESSAGES = {
    "not_applicable": "当前入库建议由受信外部 API 处理，未启用前置脱敏",
    # 以下为历史状态文案（向后兼容旧数据，新链路不再产生）。
    "applied": "历史记录：内容处理前曾对抽取文本做规则实体脱敏",
    "unchanged": "历史记录：曾运行规则脱敏，未命中可脱敏敏感实体",
    "skipped": "历史记录：未抽取到文本，未做文本级前置脱敏",
    "failed": "历史记录：规则脱敏失败，内容建议曾降级",
}


def _summary_status(task: IngestTask, ai: IngestTaskAiResult | None) -> str | None:
    if task.status == IngestStatus.processing.value:
        return "processing"
    if ai is None:
        return None
    fields = ai.naming_parsed_fields if isinstance(ai.naming_parsed_fields, dict) else {}
    persisted = fields.get("generation_status")
    if persisted in {"generated", "failed", "pending_model_config"}:
        return str(persisted)
    if _has_generated_summary(ai):
        return "generated"
    return "pending_model_config"


def _has_generated_summary(ai: IngestTaskAiResult | None) -> bool:
    if ai is None or not ai.llm_provider:
        return False
    fields = ai.naming_parsed_fields if isinstance(ai.naming_parsed_fields, dict) else {}
    return fields.get("summary_generated") is True


def _suggestion_generation_state(
    task: IngestTask, ai: IngestTaskAiResult | None
) -> tuple[str, str]:
    """Derive an explainable status from persisted processing facts only."""
    extraction_status = ai.extraction_status if ai else None
    if task.status == IngestStatus.failed.value or extraction_status in {
        "failed",
        "empty",
        "unsupported",
    }:
        if extraction_status == "unsupported":
            return "needs_manual_completion", "文件格式暂不支持内容提取，请手工补全"
        if extraction_status == "empty":
            return "needs_manual_completion", "未提取到有效文件内容，请手工补全"
        return "needs_manual_completion", "未能完成文件内容处理，请手工补全"
    if task.status == IngestStatus.processing.value:
        return "needs_correction", "建议仍在生成，请稍后核对"
    if ai is None:
        return "needs_correction", "历史任务信息不足，请人工核对"
    if not _has_generated_summary(ai) or not ai.suggested_title or not ai.suggested_summary:
        return "needs_correction", "摘要或建议字段未完整生成，请核对"
    return "generated", "已提取正文并生成建议，请人工核对"


def _desensitization_message(status: str | None) -> str | None:
    if status is None:
        return None
    return _DESENSITIZATION_MESSAGES.get(status)


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"denied_reason": reason, "message": message}
    )


def _is_admin(caller: CallerContext) -> bool:
    return "admin" in caller.active_company_roles


def _is_governance(caller: CallerContext) -> bool:
    # 业务治理角色 = boss / consulting_director（与可发现 L5 一致）。
    return caller.can_discover_l5


async def create_upload(
    session: AsyncSession,
    caller: CallerContext,
    *,
    content: bytes,
    file_name: str,
    file_mime_type: str | None,
    target_scope: str | None,
    target_project_id: uuid.UUID | None,
    storage: LocalFileStorage,
    llm: LLMClient | NullLLMClient,
    desensitizer: DesensitizationEngine,
    trace_id: str,
) -> IngestUploadResponse:
    """创建 Path B 上传任务：把文件字节写入受控存储 + 生成 AI 建议占位。仅业务用户可创建。

    安全：仅在业务用户校验通过后才落盘（被拒调用不持久化任何字节）；存储引用是
    server-only 内部标识，只写入模型 `source_file_ref` 列，不进入任何响应。
    """
    if not caller.is_business_user:
        # 纯 admin / 非业务用户发起入库被拒（强审计）。不落盘任何字节。
        await audit_service.record_denied(
            session,
            caller=caller,
            log_type=AuditLogType.exception,
            action=AuditAction.admin_business_denied.value,
            trace_id=trace_id,
            target_type="ingest_task",
            severity=AlertSeverity.warning,
            risk_level=AuditRiskLevel.high.value,
            extra={
                "denied_reason": "admin_business_permission_denied",
                "attempted": "ingest.upload",
            },
        )
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可发起入库")

    if not content:
        raise _denied(422, "empty_file", "上传文件为空")

    # 保留**原始文件名**作来源追溯与命名规范化输入（顾问文件名常含中文 / 【】，
    # 不应被清洗破坏）。它只是展示标签 / 命名信号，**绝不**用于拼接存储路径——
    # 真实存储 key 由 storage.save 内部 safe_filename + 随机段独立生成（防穿越）。
    try:
        storage_ref = storage.save(content, original_name=file_name)
    except StorageError as exc:
        if str(exc) == "file_too_large":
            raise _denied(413, "file_too_large", "文件超出大小上限") from exc
        raise _denied(422, "invalid_file", "文件无法存储") from exc

    # 内容哈希（去重软提示，存任务上，作业按它做 dup 检测）。
    content_hash = hashlib.sha256(content).hexdigest()

    # 请求路径只持久化字节 + 建任务（status=processing），重活（抽取 / 内容处理 /
    # 写 ai_result / 推进状态 / ai_extracted·failed 审计）迁到异步作业。
    task = IngestTask(
        source=IngestSource.path_b_upload.value,
        # server-only 内部存储引用，不外泄前端。
        source_file_ref=storage_ref,
        source_file_name=file_name,
        source_file_mime_type=file_mime_type,
        source_file_size=len(content),
        source_file_hash=content_hash,
        status=IngestStatus.processing.value,
        processing_stage="upload_saved",
        target_scope=target_scope,
        target_project_id=target_project_id,
        created_by=caller.user_id,
    )
    session.add(task)
    await session.flush()  # 取得 task.id 供审计 target_id

    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.ingest_task_created.value,
        trace_id=trace_id,
        target_type="ingest_task",
        target_id=task.id,
        after={"status": task.status, "source": task.source, "target_scope": task.target_scope},
        project_id=target_project_id,
    )
    await session.commit()

    # 入队异步处理：eager（默认/本地/测试）内联同步执行并返回最终 status；非 eager 排队
    # 到 broker、立即返回 processing（无 worker 时保持 processing/pending）。
    status = await enqueue_ingest_processing(
        session, task.id, storage=storage, llm=llm, desensitizer=desensitizer, trace_id=trace_id
    )
    return IngestUploadResponse(ingest_task_id=task.id, status=status, upload_url=None)


async def _load_task(
    session: AsyncSession, task_id: uuid.UUID, *, lock: bool = False
) -> IngestTask:
    from sqlalchemy.orm import selectinload

    stmt = (
        select(IngestTask)
        .where(IngestTask.id == task_id)
        .options(selectinload(IngestTask.ai_result))
    )
    if lock:
        stmt = stmt.with_for_update()
    task = (await session.execute(stmt)).scalar_one_or_none()
    if task is None:
        raise _denied(404, "ingest_task_not_found", "入库任务不存在")
    return task


async def get_ai_result(
    session: AsyncSession, caller: CallerContext, task_id: uuid.UUID
) -> IngestAiResultResponse:
    """获取 AI 建议结果。创建人/治理角色看完整建议；admin 仅看运营元数据；其余 403。"""
    task = await _load_task(session, task_id)
    ai = task.ai_result
    is_creator = task.created_by == caller.user_id
    is_full = is_creator or _is_governance(caller)

    if not is_full and not _is_admin(caller):
        raise _denied(403, "ingest_result_forbidden", "无权查看该入库任务的 AI 建议")

    advice = safe_naming_advice(ai)
    base = IngestAiResultResponse(
        ingest_task_id=task.id,
        status=task.status,
        suggested_asset_type=ai.suggested_asset_type if ai else None,
        **advice,
        suggested_ai_access_level=ai.suggested_ai_access_level if ai else None,
        suggested_phase_key=ai.suggested_phase_key if ai else None,
        confidence=ai.confidence if ai else None,
        suggestion_generation_status=_suggestion_generation_state(task, ai)[0],
        suggestion_generation_reason=_suggestion_generation_state(task, ai)[1],
        naming_compliant=ai.naming_compliant if ai else None,
        naming_parsed_fields=ai.naming_parsed_fields if ai else None,
        naming_anomalies=ai.naming_anomalies if ai else None,
        # 运营元数据（两视图均可见）：抽取状态 / 字符数 / 错误 / 去重软提示。
        extraction_status=ai.extraction_status if ai else None,
        extracted_char_count=ai.extracted_char_count if ai else None,
        error_type=task.error_type,
        error_message=task.error_message,
        is_possible_duplicate=bool(ai and ai.duplicate_of_task_id is not None),
        duplicate_of_task_id=ai.duplicate_of_task_id if ai else None,
        duplicate_of_asset_id=ai.duplicate_of_asset_id if ai else None,
        # 运营元数据（两视图均可见；provider/model 非密钥）。
        llm_provider=ai.llm_provider if ai else None,
        llm_model=ai.llm_model if ai else None,
        # 异步处理中（job 未完成）安全地表示为 processing；完成后按 llm/降级。
        content_processing_status=(
            "processing"
            if task.status == IngestStatus.processing.value
            else ("llm" if (ai and ai.llm_provider) else "degraded")
            if ai
            else None
        ),
        summary_status=_summary_status(task, ai),
        generation_model_ref=(
            generation_model_ref(ai.llm_provider, ai.llm_model or "")
            if ai and ai.llm_provider and ai.llm_model
            else None
        ),
        generation_error_category=(
            ai.naming_parsed_fields.get("generation_error_category")
            if ai and isinstance(ai.naming_parsed_fields, dict)
            else None
        ),
        generation_recovery_hint=(
            ai.naming_parsed_fields.get("generation_recovery_hint")
            if ai and isinstance(ai.naming_parsed_fields, dict)
            else None
        ),
        # 入库脱敏安全元数据（状态 + 类别计数 + 人读文案，两视图均可见）。
        # 新任务为 not_applicable / counts=null；旧数据行保留历史状态。
        desensitization_status=ai.desensitization_status if ai else None,
        desensitization_counts=(ai.desensitization_counts if ai else None) or None,
        desensitization_message=_desensitization_message(ai.desensitization_status if ai else None),
    )
    if is_full and ai is not None:
        # 完整视图（创建人 / 治理角色）：补充业务建议正文（三层摘要）+ 抽取全文截断预览。
        base.suggested_title = suggested_subject(
            ai.naming_parsed_fields if isinstance(ai.naming_parsed_fields, dict) else None,
            ai.suggested_title,
            task.source_file_name,
        )
        base.suggested_one_liner = ai.suggested_one_liner
        base.suggested_summary = ai.suggested_summary
        base.summary = ai.suggested_summary if _has_generated_summary(ai) else None
        base.suggested_key_points = ai.suggested_key_points
        base.suggested_tags = ai.suggested_tags
        if ai.extracted_text:
            base.extracted_text_preview = ai.extracted_text[:500]
    # admin 视图：business 字段（含三层摘要正文）与抽取全文预览保持 None。
    return base


async def confirm(
    session: AsyncSession,
    caller: CallerContext,
    task_id: uuid.UUID,
    req: IngestConfirmRequest,
    trace_id: str,
    *,
    storage: LocalFileStorage,
    weknora: WeKnoraClient | NullWeKnoraClient,
) -> IngestConfirmResponse:
    """Validate, persist, and index one human-confirmed ingest task."""
    route = await ingest_confirmation.validate_and_route_confirmation(
        session,
        caller,
        task_id,
        req,
        trace_id,
    )
    if isinstance(route, IngestConfirmResponse):
        return route

    context = await ingest_confirmation.apply_confirmation_extensions(route)
    persisted = await ingest_persistence.persist_confirmation(
        session,
        context,
        use_indexing=weknora_enabled(),
    )

    # Index failure handling may roll back and expire ORM objects. Capture the
    # response identifiers at the persistence boundary before that can happen.
    response_task_id = persisted.task.id
    response_status = persisted.task.status
    result_asset_id = persisted.asset.id
    canonical_name = persisted.asset.canonical_name
    parse_status: str | None = None
    index_status = "indexing" if persisted.use_indexing else "skipped"
    if persisted.use_indexing:
        index_status, parse_status = await ingest_indexing.index_confirmed_asset(
            session,
            caller,
            persisted.task,
            persisted.asset,
            persisted.version,
            scope=context.scope,
            owner_id=context.owner_id,
            project_id=context.project_id,
            confidentiality=context.request.confidentiality_level.value,
            weknora=weknora,
            storage=storage,
            trace_id=trace_id,
            embedding_model_ref=context.request.embedding_model_ref,
            rerank_model_ref=context.request.rerank_model_ref,
        )

    _logger.info(
        "ingest_confirmed",
        extra={
            "asset_id": str(result_asset_id),
            "index_status": index_status,
        },
    )
    return IngestConfirmResponse(
        task_id=response_task_id,
        status=response_status,
        result_asset_id=result_asset_id,
        parse_status=parse_status,
        index_status=index_status,
        canonical_name=canonical_name,
    )


async def approve_project_ingest_review(
    session: AsyncSession,
    caller: CallerContext,
    review: ReviewTask,
    comment: str | None,
    trace_id: str,
    *,
    storage: LocalFileStorage,
    weknora: WeKnoraClient | NullWeKnoraClient,
) -> ReviewActionResponse:
    """Materialize an approved project submission without exposing partial assets."""
    if review.source_ingest_task_id is None or review.confirmation_snapshot is None:
        raise _denied(409, "project_ingest_snapshot_missing", "项目提交确认快照不可用")
    req = IngestConfirmRequest.model_validate(review.confirmation_snapshot)
    if req.target_project_id is None or review.target_project_id != req.target_project_id:
        raise _denied(409, "project_ingest_snapshot_invalid", "项目提交目标不一致")
    submitter_id = review.submitted_by
    if submitter_id is None:
        raise _denied(409, "project_ingest_submitter_missing", "项目提交人不可用")

    task = (
        await session.execute(
            select(IngestTask)
            .where(IngestTask.id == review.source_ingest_task_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if task is None:
        raise _denied(409, "project_ingest_task_missing", "项目提交来源不可用")

    from app.services import naming_rules

    naming_result = await naming_rules.render(
        session,
        caller,
        task,
        NamingPreviewRequest(
            target_scope=req.target_scope,
            target_project_id=req.target_project_id,
            confidentiality_level=req.confidentiality_level,
            naming=req.naming,
        ),
    )
    # Re-normalize snapshots at approval time as well so reviews created before
    # this protection cannot retain a historical customer-bearing subject.
    req = ingest_confirmation.apply_authoritative_project_subject(req, naming_result)

    asset: KnowledgeAsset
    version: KnowledgeAssetVersion
    if review.target_asset_id is None:
        summary_text = (req.summary or "").strip() or (req.one_liner or "").strip()
        confidentiality = req.confidentiality_level.value
        review_context = ingest_confirmation.ValidatedConfirmationContext(
            task=task,
            request=req,
            scope=KnowledgeScope.project.value,
            owner_id=submitter_id,
            project_id=req.target_project_id,
            caller=caller,
            trace_id=trace_id,
            session=session,
            naming_result=naming_result,
        )
        asset_type, visibility = ingest_persistence.derived_confirmation_properties(review_context)
        asset = KnowledgeAsset(
            title=req.title,
            scope=KnowledgeScope.project.value,
            zone=req.target_zone.value,
            asset_type=asset_type,
            owner_user_id=submitter_id,
            maintainer_user_id=submitter_id,
            project_id=req.target_project_id,
            visibility=visibility,
            confidentiality_level=confidentiality,
            ai_access_level="A1",
            asset_status="processing",
            lifecycle_phase_key=None,
            canonical_name=naming_result.canonical_name if naming_result is not None else None,
        )
        version = KnowledgeAssetVersion(
            version_no="v1",
            version_status="active",
            created_by=submitter_id,
            file_hash=task.source_file_hash,
            source_hash=task.source_file_hash,
            naming_metadata=naming_result.metadata if naming_result is not None else None,
            naming_rule_version=naming_result.rule_version if naming_result is not None else None,
        )
        asset.versions.append(version)
        for summary in ingest_persistence.build_summaries(
            confidentiality,
            one_liner=req.one_liner,
            detailed=summary_text,
            key_points=req.key_points,
        ):
            summary.version = version
            asset.summaries.append(summary)
        for tag in req.tags:
            asset.tags.append(KnowledgeAssetTag(tag_name=tag))
        session.add(asset)
        await session.flush()
        asset.current_version_id = version.id
        review.target_asset_id = asset.id
        task.result_asset_id = asset.id
        task.result_version_id = version.id
        version.index_status = "indexing" if weknora_enabled() else "skipped"
    else:
        asset = (
            await session.execute(
                select(KnowledgeAsset).where(KnowledgeAsset.id == review.target_asset_id)
            )
        ).scalar_one()
        version = (
            await session.execute(
                select(KnowledgeAssetVersion).where(
                    KnowledgeAssetVersion.id == asset.current_version_id
                )
            )
        ).scalar_one()

    # The review service atomically claimed this task before materialization.
    review.status = ReviewTaskStatus.approving.value
    review.review_comment = comment
    review.reviewed_at = None
    await session.commit()
    review_id = review.id
    asset_id = asset.id
    ingest_task_id = task.id

    index_status = "skipped"
    parse_status: str | None = None
    if weknora_enabled():
        try:
            index_status, parse_status = await ingest_indexing.index_confirmed_asset(
                session,
                caller,
                task,
                asset,
                version,
                scope=KnowledgeScope.project.value,
                owner_id=submitter_id,
                project_id=req.target_project_id,
                confidentiality=req.confidentiality_level.value,
                weknora=weknora,
                storage=storage,
                trace_id=trace_id,
                embedding_model_ref=req.embedding_model_ref,
                rerank_model_ref=req.rerank_model_ref,
            )
        except Exception:
            _logger.warning(
                "project_ingest_approval_index_failed",
                extra={"stage": "index"},
                exc_info=True,
            )
            await session.rollback()
            index_status = "index_failed"

    loaded_review = await session.get(ReviewTask, review_id)
    loaded_asset = await session.get(KnowledgeAsset, asset_id)
    loaded_task = await session.get(IngestTask, ingest_task_id)
    if loaded_review is None or loaded_asset is None or loaded_task is None:
        raise RuntimeError(
            "review/asset/task missing after approval: "
            f"review={loaded_review is not None}, "
            f"asset={loaded_asset is not None}, "
            f"task={loaded_task is not None}"
        )
    review, asset, task = loaded_review, loaded_asset, loaded_task
    if index_status not in {"indexed", "skipped"}:
        review.status = ReviewTaskStatus.approval_failed.value
        task.status = IngestStatus.waiting_review.value
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.exception,
            action=AuditAction.review_approval_failed.value,
            trace_id=trace_id,
            target_type="review_task",
            target_id=review.id,
            after={"status": review.status, "index_status": index_status},
            project_id=req.target_project_id,
        )
        await session.commit()
        return ReviewActionResponse(
            review_id=review.id,
            status=review.status,
            target_asset_id=asset.id,
            asset_zone=None,
            index_status=index_status,
        )

    asset.asset_status = "active"
    task.status = IngestStatus.completed.value
    task.target_scope = KnowledgeScope.project.value
    task.target_project_id = req.target_project_id
    task.target_zone = asset.zone
    review.status = ReviewTaskStatus.approved.value
    review.reviewed_at = datetime.now(timezone.utc)
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.review_approved.value,
        trace_id=trace_id,
        target_type="review_task",
        target_id=review.id,
        after={"status": review.status, "review_type": review.review_type},
        project_id=req.target_project_id,
    )
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.ingest_confirmed.value,
        trace_id=trace_id,
        target_type="knowledge_asset",
        target_id=asset.id,
        after={
            "scope": asset.scope,
            "zone": asset.zone,
            "confidentiality_level": asset.confidentiality_level,
            "ai_access_level": asset.ai_access_level,
            "approval": "project_manager",
        },
        project_id=req.target_project_id,
    )
    await session.commit()
    return ReviewActionResponse(
        review_id=review.id,
        status=review.status,
        target_asset_id=asset.id,
        asset_zone=asset.zone,
        index_status=index_status,
    )


async def refresh_parse(
    session: AsyncSession,
    caller: CallerContext,
    task_id: uuid.UUID,
    *,
    weknora: WeKnoraClient | NullWeKnoraClient,
) -> IngestParseRefreshResponse:
    """解析状态对账（按需刷新，不引 Celery）。

    可见性沿用 get_ai_result：创建人 / 治理角色 / admin 可触发。读 WeKnora
    `get_knowledge(doc_id)` 的 `parse_status` 回写 version，只返回安全业务状态。
    """
    from app.schemas.ingest import IngestParseRefreshResponse

    task = await _load_task(session, task_id)
    is_full = task.created_by == caller.user_id or _is_governance(caller)
    if not is_full and not _is_admin(caller):
        raise _denied(403, "ingest_result_forbidden", "无权刷新该入库任务解析状态")

    version: KnowledgeAssetVersion | None = None
    if task.result_asset_id is not None:
        version = (
            await session.execute(
                select(KnowledgeAssetVersion)
                .where(KnowledgeAssetVersion.asset_id == task.result_asset_id)
                .where(KnowledgeAssetVersion.version_status == "active")
            )
        ).scalar_one_or_none()

    parse_status = version.weknora_parse_status if version is not None else None
    if (
        weknora_enabled()
        and version is not None
        and version.weknora_doc_id
        and version.weknora_parse_status not in {"completed", "failed", "duplicate"}
    ):
        try:
            data = await weknora.get_knowledge(version.weknora_doc_id, trace_id=None)
            parse_status = str(data.get("parse_status") or version.weknora_parse_status)
            version.weknora_parse_status = parse_status
            await session.commit()
        except WeKnoraError:
            # 对账失败不改既有状态、不抛（前端可重试）。
            await session.rollback()

    return IngestParseRefreshResponse(
        task_id=task.id, result_asset_id=task.result_asset_id, parse_status=parse_status
    )


_BATCH_CONFIRMABLE_PENDING_STATUSES: set[str] = {
    IngestStatus.pending_confirmation.value,
    IngestStatus.pending.value,
    IngestStatus.rejected.value,
}

# Keep this aligned with delete_pending_task: these rows may be permanently
# rejected even when they are not eligible for confirmation.
_DELETABLE_PENDING_STATUSES: set[str] = {
    IngestStatus.pending_confirmation.value,
    IngestStatus.failed.value,
    IngestStatus.rejected.value,
    IngestStatus.waiting_review.value,
}


async def list_pending(
    session: AsyncSession,
    caller: CallerContext,
    *,
    source: str | None = None,
    statuses: set[str] | None = None,
) -> list[PendingIngestItem]:
    """业务侧待确认任务列表。

    用于 `/upload` Path A 面板：拉取尚未入库（result_asset_id 为空）的入库任务。
    只返回调用人本人创建的待确认任务。权限由 SQL WHERE 子句直接过滤，杜绝任何
    跨用户数据泄露。纯 admin 不是业务用户 → 403（不因系统身份获得业务确认 / 查看权）。

    响应只含安全元数据，绝不含 source_file_ref / storage_ref / WeCom file_id /
    下载 URL / token / WeKnora id / 抽取全文。

    ``statuses`` 可选地按状态过滤；为 ``None`` 时保持原有行为（返回所有待确认任务，
    状态覆盖 pending_confirmation / failed / rejected）。
    """
    if not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可查看待确认入库任务")

    from sqlalchemy.orm import defer, selectinload

    stmt = (
        select(IngestTask)
        # 仅返回当前用户的待确认任务：result_asset_id 为空 且 created_by 匹配。
        .where(IngestTask.result_asset_id.is_(None), IngestTask.created_by == caller.user_id)
        .options(
            # 列表不返回抽取全文：defer extracted_text 避免查询放大与内容外泄。
            selectinload(IngestTask.ai_result).options(defer(IngestTaskAiResult.extracted_text))
        )
        .order_by(IngestTask.created_at.desc())
    )
    if source is not None:
        stmt = stmt.where(IngestTask.source == source)
    if statuses is not None:
        stmt = stmt.where(IngestTask.status.in_(statuses))

    tasks = list((await session.execute(stmt)).scalars().all())
    items: list[PendingIngestItem] = []
    for t in tasks:
        ai = t.ai_result
        advice = safe_naming_advice(ai)
        suggestion_state = _suggestion_generation_state(t, ai)
        display_subject = (
            suggested_subject(
                ai.naming_parsed_fields
                if ai and isinstance(ai.naming_parsed_fields, dict)
                else None,
                ai.suggested_title if ai else None,
                t.source_file_name,
            )
            if ai
            else None
        )
        can_batch_confirm = (
            t.status in _BATCH_CONFIRMABLE_PENDING_STATUSES
            and ai is not None
            # Confirmation validates the editable title and summary fields below;
            # legacy extraction/generation diagnostics are display-only metadata.
            and bool(display_subject)
            and bool((ai.suggested_summary or ai.suggested_one_liner or "").strip())
        )
        items.append(
            PendingIngestItem(
                id=t.id,
                source=t.source,
                status=t.status,
                source_file_name=t.source_file_name,
                target_scope=t.target_scope,
                target_project_id=t.target_project_id,
                can_batch_confirm=can_batch_confirm,
                can_batch_reject=t.status in _DELETABLE_PENDING_STATUSES,
                extraction_status=ai.extraction_status if ai else None,
                error_type=t.error_type,
                error_message=t.error_message,
                suggested_title=display_subject,
                suggested_one_liner=ai.suggested_one_liner if ai else None,
                **advice,
                naming_parsed_fields=ai.naming_parsed_fields if ai else None,
                confidence=ai.confidence if ai else None,
                suggestion_generation_status=suggestion_state[0],
                suggestion_generation_reason=suggestion_state[1],
                result_asset_id=t.result_asset_id,
                created_at=t.created_at,
                updated_at=t.updated_at,
            )
        )
    return items


async def delete_pending_task(
    session: AsyncSession, caller: CallerContext, task_id: uuid.UUID, trace_id: str = ""
) -> None:
    """Delete an eligible pre-asset ingest task with stable database-failure semantics."""
    try:
        await _delete_pending_task(session, caller, task_id, trace_id)
    except (DBAPIError, SQLAlchemyTimeoutError):
        # Lock waits, pool timeouts and broken connections can occur before the
        # narrower dependency-cleanup handlers run. Never expose driver details.
        try:
            await session.rollback()
        except (DBAPIError, SQLAlchemyTimeoutError):
            pass
        _logger.warning(
            "ingest_delete_database_temporarily_unavailable",
            extra={"result_category": "database_temporarily_unavailable"},
        )
        raise _denied(
            503,
            "ingest_delete_temporarily_unavailable",
            "任务关联清理暂时不可用，请稍后重试",
        ) from None


async def _delete_pending_task(
    session: AsyncSession, caller: CallerContext, task_id: uuid.UUID, trace_id: str = ""
) -> None:
    """删除/取消待确认入库任务。

    规则：
    - 仅创建人本人可删除（治理角色也不能代删他人任务）。
    - 仅未确认（result_asset_id IS NULL）且状态可中断的任务可删；
      processing / pending 状态的任务不在此列——可能在流水线中途。
    - 删除数据库记录（级联删除 ai_result 关联）并清理存储文件。
    - 审计写入 ingest.task_deleted。
    """
    task = await _load_task(session, task_id, lock=True)

    # 仅创建人本人
    if task.created_by != caller.user_id:
        raise _denied(403, "ingest_delete_forbidden", "仅创建人可删除自己的待确认任务")

    if task.result_asset_id is not None:
        raise _denied(409, "ingest_already_confirmed", "已确认入库的任务不可删除")

    if task.status not in _DELETABLE_PENDING_STATUSES:
        raise _denied(
            409,
            "ingest_delete_not_allowed",
            f"当前状态 {task.status} 不允许删除（仅在确认前/失败/驳回状态可删）",
        )

    # 同步上传队列里的 item 状态：避免 ON DELETE SET NULL 把 ingest_task_id 清空后，
    # upload_session_items 仍卡在 awaiting_confirmation，造成和会话统计/待确认入库列表不同步。
    linked_items = (
        (
            await session.execute(
                select(UploadSessionItem).where(UploadSessionItem.ingest_task_id == task_id)
            )
        )
        .scalars()
        .all()
    )
    for linked_item in linked_items:
        linked_item.ingest_task_id = None
        linked_item.status = "cancelled"
        linked_item.safe_error_code = None
        linked_item.safe_error_message = None

    linked_session_ids = {item.session_id for item in linked_items}
    if linked_session_ids:
        from sqlalchemy.orm import selectinload

        upload_sessions = (
            (
                await session.execute(
                    select(UploadSession)
                    .where(UploadSession.id.in_(linked_session_ids))
                    .options(selectinload(UploadSession.items))
                )
            )
            .scalars()
            .all()
        )
        terminal_item_states = {"awaiting_confirmation", "completed", "failed", "cancelled"}
        for upload_session in upload_sessions:
            upload_session.status = (
                "completed"
                if all(item.status in terminal_item_states for item in upload_session.items)
                else "active"
            )

    # 项目入库审批在资产形成前以 source_ingest_task_id 关联任务。永久删除错误上传时，
    # 仅允许清理这一类专用审核及其从属记录，未知业务关联一律 fail-closed。
    linked_reviews = (
        (
            await session.execute(
                select(ReviewTask)
                .where(ReviewTask.source_ingest_task_id == task_id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    if any(
        review.review_type != ReviewType.project_ingest_approval.value
        or review.target_asset_id is not None
        for review in linked_reviews
    ):
        await session.rollback()
        raise _denied(
            409,
            "ingest_review_cleanup_conflict",
            "任务存在无法安全清理的审核关联，请刷新后联系管理员",
        )

    review_ids = [review.id for review in linked_reviews]
    if review_ids:
        personal_submission_exists = (
            await session.execute(
                select(PersonalKnowledgeSubmission.id)
                .where(PersonalKnowledgeSubmission.review_task_id.in_(review_ids))
                .limit(1)
            )
        ).scalar_one_or_none()
        if personal_submission_exists is not None:
            await session.rollback()
            raise _denied(
                409,
                "ingest_review_cleanup_conflict",
                "任务存在无法安全清理的审核关联，请刷新后联系管理员",
            )
        try:
            await session.execute(
                delete(CompanyAssetReviewDecision).where(
                    CompanyAssetReviewDecision.review_task_id.in_(review_ids)
                )
            )
            await session.execute(
                delete(ReviewTaskEvidence).where(ReviewTaskEvidence.review_task_id.in_(review_ids))
            )
            await session.execute(delete(ReviewTask).where(ReviewTask.id.in_(review_ids)))
        except IntegrityError:
            await session.rollback()
            _logger.warning(
                "ingest_review_cleanup_failed",
                extra={"result_category": "dependency_cleanup_temporarily_unavailable"},
            )
            raise _denied(
                503,
                "ingest_delete_temporarily_unavailable",
                "任务关联清理暂时不可用，请稍后重试",
            ) from None

    # ---- 永存区：持久化删除 + 审计 ----
    source_file_ref = task.source_file_ref
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.ingest_task_deleted.value,
        trace_id=trace_id,
        target_type="ingest_task",
        target_id=task_id,
        after={"result_category": "permanently_deleted"},
    )

    # 级联删除 ai_result（ORM relationship cascade="all, delete-orphan"）。
    await session.delete(task)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        _logger.warning(
            "ingest_delete_transaction_failed",
            extra={"result_category": "dependency_cleanup_temporarily_unavailable"},
        )
        raise _denied(
            503,
            "ingest_delete_temporarily_unavailable",
            "任务关联清理暂时不可用，请稍后重试",
        ) from None

    # 文件系统无法参与数据库事务。数据库成功后再 best-effort 清理，避免清理依赖失败时
    # 先删除仍被任务引用的源文件；缺失文件或供应商错误均不改变删除结果。
    from app.services.storage import get_storage

    try:
        if source_file_ref:
            get_storage().delete(source_file_ref)
    except Exception:
        _logger.warning(
            "ingest_delete_file_cleanup_failed",
            extra={"result_category": "controlled_file_cleanup_failed"},
        )


async def list_admin_ingest(
    session: AsyncSession,
    caller: CallerContext,
    *,
    trace_id: str = "admin-ingest",
) -> list[AdminIngestItem]:
    """运营只读列表：admin 或治理角色可看运营元数据（无业务原文 / 内部引用）。"""
    if not (_is_admin(caller) or _is_governance(caller)):
        raise _denied(403, "ingest_admin_forbidden", "无权查看入库运营列表")

    from app.services import upload_sessions

    await upload_sessions.expire_stale_tasks(
        session,
        caller,
        trace_id=trace_id,
        all_owners=True,
    )

    from sqlalchemy.orm import selectinload

    tasks = list(
        (
            await session.execute(
                select(IngestTask).options(
                    # 列表不返回抽取全文：defer extracted_text 避免查询放大。
                    selectinload(IngestTask.ai_result).defer(IngestTaskAiResult.extracted_text)
                )
            )
        )
        .scalars()
        .all()
    )
    items: list[AdminIngestItem] = []
    for t in tasks:
        ai = t.ai_result
        safe_file_name = (t.source_file_name or "file").replace("\\", "/").rsplit("/", 1)[-1]
        items.append(
            AdminIngestItem(
                id=t.id,
                source=t.source,
                source_file_name=safe_file_name,
                status=t.status,
                target_scope=t.target_scope,
                confidentiality_level=ai.suggested_confidentiality_level if ai else None,
                ai_access_level=ai.suggested_ai_access_level if ai else None,
                confidence=ai.confidence if ai else None,
                suggestion_generation_status=_suggestion_generation_state(t, ai)[0],
                suggestion_generation_reason=_suggestion_generation_state(t, ai)[1],
                naming_compliant=ai.naming_compliant if ai else None,
                extraction_status=ai.extraction_status if ai else None,
                error_type=t.error_type,
                error_message=(
                    "文件处理超过安全时限且近期无活动"
                    if t.error_type == "processing_timeout"
                    else "文件内容无法完成处理"
                    if t.status == IngestStatus.failed.value
                    else None
                ),
                result_asset_id=t.result_asset_id,
                created_at=t.created_at,
            )
        )
    return items
