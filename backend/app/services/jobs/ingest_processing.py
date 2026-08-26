"""异步入库处理作业。

把"抽取 + 内容处理 + 写 ai_result + 推进状态"从请求路径迁出。`create_upload`
只持久化字节 + 建 `ingest_tasks`（status=processing）+ 入队；本作业完成重活。

幂等与重试：
- 已处理（pending_confirmation / completed）→ 直接跳过，不重复建 ai_result、不重复
  写终态审计。
- 抽取/内容失败（empty/failed 抽取）→ 写降级 ai_result + status=failed（**内容性终态**，
  非瞬时错误，不增 retry_count）。
- 瞬时异常（读盘/未知错误）→ 递增 retry_count；未达 max_retries 回到 processing 等待
  重试，达到上限置 failed。**绝不**重复创建 ai_result 行、绝不外泄内部引用。

安全：审计/日志只记安全元数据——绝不含 source_file_ref / storage_ref / 抽取全文 /
weknora id / api_key。
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import safe_log_exception
from app.core.text_safety import (
    EXTRACTED_TEXT_MAX_CHARS,
    KEY_POINT_MAX_CHARS,
    ONE_LINER_MAX_CHARS,
    SUMMARY_MAX_CHARS,
    TAG_MAX_CHARS,
    TITLE_MAX_CHARS,
    sanitize_json,
    sanitize_text,
)
from app.db.utils import utc_now
from app.models.identity import ProjectMember, User
from app.models.ingest import IngestTask, IngestTaskAiResult
from app.schemas.enums import (
    AlertSeverity,
    AuditAction,
    AuditLogType,
    AuditRiskLevel,
    IngestStatus,
    KnowledgeScope,
)
from app.schemas.naming import NamingOptionsResponse
from app.schemas.permission import CallerContext
from app.services import audit as audit_service
from app.services import (
    canonical_markdown,
    content_processing,
    domain_events,
    llm_usage,
    naming_rules,
    ocr,
)
from app.services.desensitization import DesensitizationEngine
from app.services.extraction import ExtractionPage, ExtractionResult, extract_text
from app.services.llm_client import LLMClient, NullLLMClient
from app.services.permission import build_caller_context
from app.services.storage import LocalFileStorage
from app.worker.enqueue import enqueue_outbox_delivery

_logger = logging.getLogger(__name__)


async def _publish_ingest_failed(session: AsyncSession, task: IngestTask) -> None:
    await domain_events.publish(
        session,
        domain_events.DomainEvent(
            event_type=domain_events.INGEST_FAILED,
            aggregate_type="ingest_task",
            aggregate_id=task.id,
            payload=domain_events.safe_payload(
                task_id=task.id,
                project_id=task.target_project_id,
                status=task.status,
            ),
            idempotency_key=f"ingest-failed:{task.id}:{task.retry_count}",
        ),
    )


# 已处理终态（再次入队/重跑直接跳过，保证幂等）。
_PROCESSED_STATUSES = {IngestStatus.pending_confirmation.value, IngestStatus.completed.value}
_PAGE_MARKER_RE = re.compile(r"\{\{page:(\d+)\}\}\s*\n?")
_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"}


def _marked_page_texts(value: str | None) -> dict[int, str]:
    """Recover native PDF page text from the persisted marked extraction body."""
    if not value:
        return {}
    matches = list(_PAGE_MARKER_RE.finditer(value))
    return {
        int(match.group(1)): value[
            match.end() : matches[index + 1].start() if index + 1 < len(matches) else len(value)
        ].strip()
        for index, match in enumerate(matches)
    }


def _ocr_page_plan(extraction: ExtractionResult) -> list[dict]:
    return [
        {
            "page_number": page.page_number,
            "source_status": page.status,
            "status": "skipped_text" if page.status == "extracted" else "pending",
            "char_count": len(page.text),
            "confidence": None,
        }
        for page in extraction.pages
    ]


def _ocr_source_kind(task: IngestTask) -> str:
    mime = (task.source_file_mime_type or "").lower()
    file_name = task.source_file_name or ""
    extension = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    return "image" if mime.startswith("image/") or extension in _IMAGE_EXTENSIONS else "pdf"


async def _build_actor(session: AsyncSession, task: IngestTask) -> CallerContext:
    """以任务创建人身份构建审计 actor（作业代其完成内容处理）。"""
    if task.created_by is not None:
        user = (
            await session.execute(
                select(User)
                .where(User.id == task.created_by)
                .options(
                    selectinload(User.company_roles),
                    selectinload(User.project_members).selectinload(ProjectMember.project),
                )
            )
        ).scalar_one_or_none()
        if user is not None:
            return build_caller_context(user)
    # 兜底：无创建人（不应发生）→ 最小 system actor。
    return CallerContext(
        user_id=task.created_by or uuid.UUID(int=0),
        is_active=True,
        active_company_roles=set(),
        active_project_ids=set(),
    )


async def _find_duplicate(session: AsyncSession, content_hash: str, exclude_task_id: uuid.UUID):
    """按内容哈希查最早的既有任务（去重软提示）。返回 (task_id, result_asset_id|None)。"""
    if not content_hash:
        return None
    row = (
        await session.execute(
            select(IngestTask.id, IngestTask.result_asset_id)
            .where(IngestTask.source_file_hash == content_hash)
            .where(IngestTask.id != exclude_task_id)
            .order_by(IngestTask.created_at)
            .limit(1)
        )
    ).first()
    return (row[0], row[1]) if row is not None else None


async def _generation_category_context(
    session: AsyncSession, task: IngestTask, actor: CallerContext
) -> dict | None:
    contexts: list[tuple[KnowledgeScope, NamingOptionsResponse]] = []
    if task.target_scope in {KnowledgeScope.project.value, KnowledgeScope.company.value}:
        try:
            scope = KnowledgeScope(task.target_scope)
            contexts.append(
                (scope, await naming_rules.options(session, actor, scope, task.target_project_id))
            )
        except Exception:  # permissions/rules fail closed without breaking content generation
            return None
    else:
        if actor.active_project_ids:
            for representative in sorted(actor.active_project_ids, key=str):
                try:
                    contexts.append(
                        (
                            KnowledgeScope.project,
                            await naming_rules.options(
                                session, actor, KnowledgeScope.project, representative
                            ),
                        )
                    )
                    break
                except Exception:
                    continue
        if actor.can_discover_l5:
            try:
                contexts.append(
                    (
                        KnowledgeScope.company,
                        await naming_rules.options(session, actor, KnowledgeScope.company, None),
                    )
                )
            except Exception:
                pass
    contexts = [(scope, options) for scope, options in contexts if options.rule_version is not None]
    if not contexts:
        return None
    revisions = {options.rule_version for _scope, options in contexts}
    if len(revisions) != 1:
        return None
    pending_selection = task.target_scope not in {
        KnowledgeScope.project.value,
        KnowledgeScope.company.value,
    }
    return {
        "target_scope": "pending_selection" if pending_selection else contexts[0][0].value,
        "target_project_id": str(task.target_project_id) if task.target_project_id else None,
        "rule_revision": revisions.pop(),
        "candidates": [
            {
                "id": str(item.id),
                "scope": scope.value,
                "display_name": f"{item.primary} / {item.secondary}",
                "description": (item.description or "")[:160] or None,
            }
            for scope, options in contexts
            for item in options.categories
            if item.enabled and item.scope == scope.value
        ],
    }


async def _reusable_ai_draft(
    session: AsyncSession, *, content_hash: str, fingerprint: str, exclude_task_id: uuid.UUID
) -> dict | None:
    rows = (
        (
            await session.execute(
                select(IngestTaskAiResult)
                .join(IngestTask, IngestTask.id == IngestTaskAiResult.ingest_task_id)
                .where(IngestTask.source_file_hash == content_hash)
                .where(IngestTask.id != exclude_task_id)
                .order_by(IngestTaskAiResult.created_at)
            )
        )
        .scalars()
        .all()
    )
    excluded = {
        "id",
        "ingest_task_id",
        "created_at",
        "updated_at",
        "duplicate_of_task_id",
        "duplicate_of_asset_id",
        "human_corrected",
        "corrected_title",
        "corrected_summary",
        "corrected_tags",
    }
    for row in rows:
        fields = row.naming_parsed_fields if isinstance(row.naming_parsed_fields, dict) else {}
        if (
            fields.get("generation_cache_fingerprint") != fingerprint
            or fields.get("generation_status") != "generated"
            or not fields.get("summary_generated")
        ):
            continue
        return {
            column.name: getattr(row, column.name)
            for column in IngestTaskAiResult.__table__.columns
            if column.name not in excluded
        }
    return None


def _apply_ai_result(task: IngestTask, ai: dict, dup) -> None:
    """把内容处理草稿 upsert 到 task.ai_result（已存在则更新，**不新建第二行**）。"""
    result = task.ai_result
    if result is None:
        result = IngestTaskAiResult(ingest_task_id=task.id)
        task.ai_result = result
    safe_ai = sanitize_json(ai).value
    if not isinstance(safe_ai, dict):
        safe_ai = {}
    text_limits = {
        "suggested_title": TITLE_MAX_CHARS,
        "suggested_one_liner": ONE_LINER_MAX_CHARS,
        "suggested_summary": SUMMARY_MAX_CHARS,
        "extracted_text": EXTRACTED_TEXT_MAX_CHARS,
    }
    for key, value in safe_ai.items():
        if isinstance(value, str) and key in text_limits:
            value = sanitize_text(value, max_chars=text_limits[key]).value
        elif key == "suggested_tags" and isinstance(value, list):
            value = [
                sanitize_text(item, max_chars=TAG_MAX_CHARS).value
                for item in value
                if isinstance(item, str)
            ]
        elif key == "suggested_key_points" and isinstance(value, list):
            value = [
                sanitize_text(item, max_chars=KEY_POINT_MAX_CHARS).value
                for item in value
                if isinstance(item, str)
            ]
        setattr(result, key, value)
    if dup is not None:
        result.duplicate_of_task_id = dup[0]
        result.duplicate_of_asset_id = dup[1]


async def _terminalize_persistence_failure(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    provider: str | None,
    model: str | None,
    model_attempted: bool = False,
    failure_stage: str = "processing_state_persistence_failed",
) -> str:
    """Rollback first, then persist a safe per-file terminal state and usage evidence."""
    await session.rollback()
    await session.execute(
        update(IngestTask)
        .where(IngestTask.id == task_id)
        .values(
            status=IngestStatus.failed.value,
            processing_stage=failure_stage,
            error_type=failure_stage,
            error_message=(
                "内容生成结果保存失败，前置处理结果已保留，请重试。"
                if failure_stage == "content_result_persistence_failed"
                else "处理状态保存失败，任务已安全终止，请重试。"
            ),
            retry_count=IngestTask.retry_count + 1,
        )
    )
    if model_attempted:
        await llm_usage.record(
            session,
            scenario="content_generation",
            provider=provider,
            model=model,
            batch_size=1,
            cache_status="miss",
            outcome="persistence_failure",
        )
    await session.commit()
    return IngestStatus.failed.value


async def _process_upload_task_impl(
    session: AsyncSession,
    task_id: uuid.UUID,
    *,
    storage: LocalFileStorage,
    llm: LLMClient | NullLLMClient,
    desensitizer: DesensitizationEngine,
    trace_id: str | None,
    attempt_state: dict[str, bool],
) -> str:
    """处理一个 upload 任务（幂等、可重跑）。返回最终 status。"""
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
    if task is None:
        return "not_found"

    # 幂等：已成功处理 → 跳过（不重复建 ai_result、不重复写终态审计）。
    if task.status in _PROCESSED_STATUSES:
        return task.status
    # 失败终态 → 跳过。两类都视为已处理，避免重跑重复写 ingest.failed：
    #   (a) 内容性终态（抽取 empty/failed）：已建降级 ai_result（ai_result 不为 None）；
    #   (b) 瞬时失败重试耗尽（retry_count 已达上限）。
    # 仅"瞬时失败且仍有重试额度"会把 status 回退到 processing（不进本分支）→ 可重试。
    if task.status == IngestStatus.failed.value and (
        task.ai_result is not None or task.retry_count >= task.max_retries
    ):
        return task.status

    actor = await _build_actor(session, task)

    model_attempted = False

    # ---- 分阶段恢复：已持久化的抽取/OCR/Markdown 事实绝不重做。----
    try:
        file_bytes: bytes | None = None
        persisted = task.ai_result
        if (
            persisted is not None
            and persisted.extraction_status == "extracted"
            and persisted.extracted_text
        ):
            extraction = ExtractionResult(
                text=persisted.extracted_text,
                status="extracted",
                error_type=None,
                error_message=None,
                char_count=persisted.extracted_char_count or len(persisted.extracted_text),
            )
        elif persisted is not None and persisted.ocr_status in {"failed", "low_confidence"}:
            native_page_text = _marked_page_texts(persisted.extracted_text)
            saved_plan = [
                item for item in (persisted.ocr_page_results or []) if isinstance(item, dict)
            ]
            pages = tuple(
                ExtractionPage(
                    int(item.get("page_number", 1)),
                    native_page_text.get(int(item.get("page_number", 1)), "")
                    if item.get("source_status") == "extracted"
                    or item.get("status") == "skipped_text"
                    else "",
                    (
                        "extracted"
                        if item.get("source_status") == "extracted"
                        or item.get("status") == "skipped_text"
                        else "ocr_required"
                    ),
                )
                for item in saved_plan
            ) or (ExtractionPage(1, "", "ocr_required"),)
            extraction = ExtractionResult(
                text=persisted.extracted_text or "",
                status="ocr_required",
                error_type=None,
                error_message=None,
                char_count=persisted.extracted_char_count or 0,
                pages=pages,
                source_kind=_ocr_source_kind(task),
            )
        else:
            task.processing_stage = "text_extraction"
            await session.commit()
            file_bytes = storage.resolve_path(task.source_file_ref).read_bytes()
            extraction = extract_text(
                file_bytes, file_name=task.source_file_name, mime=task.source_file_mime_type
            )
            if task.ai_result is None:
                task.ai_result = IngestTaskAiResult(ingest_task_id=task.id)
            task.ai_result.extraction_status = extraction.status
            task.ai_result.extracted_text = extraction.text or None
            task.ai_result.extracted_char_count = extraction.char_count
            await session.commit()

        if extraction.status == "ocr_required":
            # Persist the full source page plan before OCR starts. If the local engine raises,
            # retry can still skip native-text pages and recognize exactly the original empty pages.
            ai_result = task.ai_result
            assert ai_result is not None
            ai_result.ocr_page_results = _ocr_page_plan(extraction)
            task.processing_stage = "ocr_queued"
            await session.commit()
            task.processing_stage = "ocr_in_progress"
            await session.commit()
            if file_bytes is None:
                file_bytes = storage.resolve_path(task.source_file_ref).read_bytes()
            try:
                recognized = ocr.recognize(file_bytes, extraction)
            except ocr.OCRError as exc:
                ai_result.ocr_status = "failed"
                ai_result.ocr_attempted_at = utc_now()
                task.status = IngestStatus.failed.value
                task.processing_stage = "ocr_failed"
                task.error_type = exc.code
                task.error_message = str(exc)
                await _publish_ingest_failed(session, task)
                await session.commit()
                await enqueue_outbox_delivery(session)
                return task.status
            ai_result.ocr_status = recognized.status
            ai_result.ocr_confidence = recognized.confidence
            ai_result.ocr_attempted_at = utc_now()
            ai_result.ocr_page_results = [
                {
                    "page_number": page.page_number,
                    "source_status": extraction.pages[index].status,
                    "status": page.status,
                    "char_count": len(page.text),
                    "confidence": page.confidence,
                }
                for index, page in enumerate(recognized.pages)
            ]
            ai_result.extraction_status = (
                "extracted" if recognized.status == "succeeded" else "ocr_low_confidence"
            )
            if recognized.status != "succeeded":
                task.status = IngestStatus.failed.value
                task.processing_stage = "ocr_failed"
                task.error_type = recognized.error_type
                task.error_message = recognized.error_message
                await _publish_ingest_failed(session, task)
                await session.commit()
                await enqueue_outbox_delivery(session)
                return task.status
            ai_result.extracted_text = recognized.text or None
            ai_result.extracted_char_count = len(recognized.text)
            extraction = ExtractionResult(
                text=recognized.text,
                status="extracted",
                error_type=None,
                error_message=None,
                char_count=len(recognized.text),
                safety_stats=recognized.safety_stats,
            )
            await session.commit()

        if file_bytes is None and not task.source_file_hash:
            file_bytes = storage.resolve_path(task.source_file_ref).read_bytes()
        content_hash = task.source_file_hash or hashlib.sha256(file_bytes or b"").hexdigest()
        task.source_file_hash = content_hash
        markdown_derivative = task.canonical_markdown
        if (
            extraction.status == "extracted"
            and extraction.text
            and not (markdown_derivative and markdown_derivative.status == "ready")
        ):
            task.processing_stage = "canonical_markdown_generation"
            await session.commit()
            task = (
                await session.execute(
                    select(IngestTask)
                    .where(IngestTask.id == task_id)
                    .options(
                        selectinload(IngestTask.ai_result),
                        selectinload(IngestTask.canonical_markdown),
                    )
                    .with_for_update()
                )
            ).scalar_one()
            try:
                markdown_derivative = await canonical_markdown.ensure_task_markdown(
                    session,
                    storage,
                    task=task,
                    extracted_text=extraction.text,
                )
            except Exception:
                await canonical_markdown.mark_task_markdown_failed(
                    session,
                    task,
                    code="canonical_markdown_generation_failed",
                )
                raise
        elif extraction.status != "extracted":
            await canonical_markdown.mark_task_markdown_failed(
                session,
                task,
                code="canonical_markdown_extraction_failed",
            )
        dup = await _find_duplicate(session, content_hash, task.id)
        category_context = await _generation_category_context(session, task, actor)
        target_scope = task.target_scope or "unscoped"
        target_project = str(task.target_project_id) if task.target_project_id else None
        generation_fingerprint = llm_usage.cache_fingerprint(
            content_hash=content_hash,
            scope=target_scope,
            project_id=target_project,
            rule_revision=int((category_context or {}).get("rule_revision") or 0),
            provider=getattr(llm, "provider", ""),
            model=getattr(llm, "model", ""),
        )
        task.processing_stage = "content_generation"
        await session.commit()
        ai = await _reusable_ai_draft(
            session,
            content_hash=content_hash,
            fingerprint=generation_fingerprint,
            exclude_task_id=task.id,
        )
        if ai is not None:
            content_meta = {
                "status": "llm",
                "reason": None,
                "provider": getattr(llm, "provider", None),
                "model": getattr(llm, "model", None),
                "usage": None,
                "desensitization_status": "not_applicable",
                "desensitization_counts": None,
            }
            await llm_usage.record(
                session,
                scenario="content_generation",
                provider=getattr(llm, "provider", None),
                model=getattr(llm, "model", None),
                batch_size=1,
                cache_status="hit",
                outcome="cache_hit",
            )
        else:
            model_attempted = extraction.status == "extracted" and not isinstance(
                llm, NullLLMClient
            )
            attempt_state["model_attempted"] = model_attempted
            ai, content_meta = await content_processing.process_content(
                llm,
                desensitizer,
                extraction=extraction,
                file_name=task.source_file_name,
                trace_id=trace_id,
                category_context=category_context,
                content_hash=content_hash,
                target_scope=target_scope,
                target_project_id=target_project,
            )
            if extraction.status == "extracted" and not isinstance(llm, NullLLMClient):
                usage_requests = content_meta.get("usage_requests")
                if not isinstance(usage_requests, list) or not usage_requests:
                    usage_requests = [
                        {
                            "outcome": (
                                "success" if content_meta.get("status") == "llm" else "failure"
                            ),
                            "usage": content_meta.get("usage"),
                        }
                    ]
                for usage_request in usage_requests:
                    await llm_usage.record(
                        session,
                        scenario="content_generation",
                        provider=content_meta.get("provider") or getattr(llm, "provider", None),
                        model=content_meta.get("model") or getattr(llm, "model", None),
                        batch_size=1,
                        cache_status="miss",
                        outcome=(
                            "success"
                            if isinstance(usage_request, dict)
                            and usage_request.get("outcome") == "success"
                            else "failure"
                        ),
                        usage=(
                            usage_request.get("usage") if isinstance(usage_request, dict) else None
                        ),
                    )
    except Exception as exc:  # noqa: BLE001  # 瞬时处理失败 → 可重试
        safe_log_exception(_logger, "ingest_processing_failed", exc, include_summary=False)
        if isinstance(exc, SQLAlchemyError):
            return await _terminalize_persistence_failure(
                session,
                task_id=task_id,
                provider=getattr(llm, "provider", None),
                model=getattr(llm, "model", None),
                model_attempted=model_attempted,
            )
        # Even non-database failures may leave pending ORM mutations. Always rollback before
        # writing retry state so a prior failed/partial transaction cannot poison this commit.
        await session.rollback()
        clean_task = await session.get(IngestTask, task_id)
        if clean_task is None:
            return "not_found"
        clean_task.retry_count += 1
        clean_task.error_type = "processing_error"
        clean_task.error_message = "入库处理失败（详见审计）"  # 安全文案，无内部引用
        exhausted = clean_task.retry_count >= clean_task.max_retries
        clean_task.status = (
            IngestStatus.failed.value if exhausted else IngestStatus.processing.value
        )
        await audit_service.record_event(
            session,
            caller=actor,
            log_type=AuditLogType.exception,
            action=AuditAction.ingest_failed.value,
            trace_id=trace_id,
            target_type="ingest_task",
            target_id=clean_task.id,
            severity=AlertSeverity.warning,
            risk_level=AuditRiskLevel.high.value,
            extra={
                "failure_stage": "processing",
                "error_code": getattr(exc, "code", None) or type(exc).__name__,
                "retry_count": clean_task.retry_count,
                "exhausted": exhausted,
            },
            project_id=clean_task.target_project_id,
        )
        if model_attempted:
            await llm_usage.record(
                session,
                scenario="content_generation",
                provider=getattr(llm, "provider", None),
                model=getattr(llm, "model", None),
                batch_size=1,
                cache_status="miss",
                outcome="failure",
            )
        if exhausted:
            await _publish_ingest_failed(session, clean_task)
        try:
            await session.commit()
        except SQLAlchemyError:
            return await _terminalize_persistence_failure(
                session,
                task_id=task_id,
                provider=getattr(llm, "provider", None),
                model=getattr(llm, "model", None),
                model_attempted=model_attempted,
            )
        if exhausted:
            await enqueue_outbox_delivery(session)
        return clean_task.status

    # ---- 内容性结果：写 ai_result + 推进状态 ----
    if isinstance(ai, dict):
        safety_diagnostics = extraction.safety_stats.as_dict()
        if any(safety_diagnostics.values()):
            naming_fields = ai.get("naming_parsed_fields")
            if not isinstance(naming_fields, dict):
                naming_fields = {}
                ai["naming_parsed_fields"] = naming_fields
            naming_fields["extraction_text_safety"] = safety_diagnostics
    _apply_ai_result(task, ai, dup)
    raw_fields = ai.get("naming_parsed_fields") if isinstance(ai, dict) else None
    fields = raw_fields if isinstance(raw_fields, dict) else {}
    generation_status = fields.get("generation_status")
    extraction_failed = extraction.status != "extracted" or markdown_derivative is None
    generation_failed = generation_status != "generated"
    failed = extraction_failed or generation_failed
    task.status = IngestStatus.failed.value if failed else IngestStatus.pending_confirmation.value
    task.processing_stage = (
        "waiting_generation_config"
        if generation_failed and fields.get("generation_error_category") == "configuration_error"
        else "content_generation_failed"
        if generation_failed
        else None
    )
    if failed:
        task.error_type = (
            extraction.error_type
            if extraction_failed
            else fields.get("generation_error_category") or "content_generation_failed"
        )
        task.error_message = (
            extraction.error_message
            if extraction_failed
            else content_meta.get("reason") or "内容生成未完成，已保留前置处理结果。"
        )
    else:
        task.error_type = None
        task.error_message = None
    try:
        await session.flush()
    except Exception as exc:  # database encoding/JSON/constraint failure
        safe_log_exception(_logger, "ingest_result_persistence_failed", exc, include_summary=False)
        return await _terminalize_persistence_failure(
            session,
            task_id=task.id,
            provider=content_meta.get("provider") or getattr(llm, "provider", None),
            model=content_meta.get("model") or getattr(llm, "model", None),
            model_attempted=model_attempted,
            failure_stage="content_result_persistence_failed",
        )

    if extraction.status == "extracted":
        await audit_service.record_event(
            session,
            caller=actor,
            log_type=AuditLogType.operation,
            action=AuditAction.ingest_ai_extracted.value,
            trace_id=trace_id,
            target_type="ingest_task",
            target_id=task.id,
            extra={
                "content_status": content_meta["status"],
                "degrade_reason": content_meta.get("reason"),
                "llm_provider": content_meta.get("provider"),
                "llm_model": content_meta.get("model"),
                "llm_usage": content_meta.get("usage"),
                "structured_output_mode": content_meta.get("structured_output_mode"),
                # 入库脱敏安全元数据——只记状态与类别计数，**绝不**记脱敏文本/原值。
                # 当前链路恒 not_applicable / counts=null（前置脱敏已退出，受信外部 API 处理）。
                "desensitization_status": content_meta.get("desensitization_status"),
                "desensitization_counts": content_meta.get("desensitization_counts"),
            },
            project_id=task.target_project_id,
        )
    if failed:
        await audit_service.record_event(
            session,
            caller=actor,
            log_type=AuditLogType.exception,
            action=AuditAction.ingest_failed.value,
            trace_id=trace_id,
            target_type="ingest_task",
            target_id=task.id,
            severity=AlertSeverity.warning,
            risk_level=AuditRiskLevel.high.value,
            extra={
                "failure_stage": "extraction" if extraction_failed else "content_generation",
                "extraction_status": extraction.status,
                "error_type": extraction.error_type,
                "source_file_name": task.source_file_name,
                "source_file_mime_type": task.source_file_mime_type,
            },
            project_id=task.target_project_id,
        )
        await _publish_ingest_failed(session, task)
    try:
        await session.commit()
    except Exception as exc:  # commit failures invalidate the active transaction
        safe_log_exception(_logger, "ingest_result_commit_failed", exc, include_summary=False)
        return await _terminalize_persistence_failure(
            session,
            task_id=task.id,
            provider=content_meta.get("provider") or getattr(llm, "provider", None),
            model=content_meta.get("model") or getattr(llm, "model", None),
            model_attempted=model_attempted,
            failure_stage="content_result_persistence_failed",
        )
    if failed:
        await enqueue_outbox_delivery(session)
    return task.status


async def process_upload_task(
    session: AsyncSession,
    task_id: uuid.UUID,
    *,
    storage: LocalFileStorage,
    llm: LLMClient | NullLLMClient,
    desensitizer: DesensitizationEngine,
    trace_id: str | None,
) -> str:
    """Fail-safe wrapper also covers initial task/actor database reads."""
    attempt_state = {"model_attempted": False}
    try:
        return await _process_upload_task_impl(
            session,
            task_id,
            storage=storage,
            llm=llm,
            desensitizer=desensitizer,
            trace_id=trace_id,
            attempt_state=attempt_state,
        )
    except SQLAlchemyError as exc:
        safe_log_exception(_logger, "ingest_database_operation_failed", exc, include_summary=False)
        return await _terminalize_persistence_failure(
            session,
            task_id=task_id,
            provider=getattr(llm, "provider", None),
            model=getattr(llm, "model", None),
            model_attempted=attempt_state["model_attempted"],
        )
