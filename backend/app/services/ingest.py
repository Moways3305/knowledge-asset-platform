"""入库流水线服务（IMPLEMENT-05，Path B 最小闭环）。

create_upload → 确定性 AI 建议占位 → get_ai_result（按权限裁剪）→ confirm（人工确认
后写入 KnowledgeAsset 全套）。不调用真实 AI / 文件存储 / WeCom / Dify / 审核流 / 审计表。
"""

from __future__ import annotations

import hashlib
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingest import IngestTask, IngestTaskAiResult
from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetSummary,
    KnowledgeAssetTag,
    KnowledgeAssetVersion,
)
from app.schemas.enums import (
    AlertSeverity,
    AuditAction,
    AuditLogType,
    AuditRiskLevel,
    ConfidentialityLevel,
    IngestSource,
    IngestStatus,
    KnowledgeScope,
)
from app.schemas.ingest import (
    AdminIngestItem,
    IngestAiResultResponse,
    IngestConfirmRequest,
    IngestConfirmResponse,
    IngestUploadResponse,
    PendingIngestItem,
)
from app.schemas.permission import CallerContext
from app.services import audit as audit_service
from app.services.desensitization import DesensitizationEngine
from app.services.llm_client import LLMClient, NullLLMClient
from app.worker.enqueue import enqueue_ingest_processing
from app.services.storage import LocalFileStorage, StorageError
from app.services.weknora_client import (
    NullWeKnoraClient,
    WeKnoraClient,
    WeKnoraDuplicateError,
    WeKnoraError,
    weknora_enabled,
)
from app.services.weknora_kb import resolve_or_create_kb

_REDACTED_LEVELS = {ConfidentialityLevel.L3.value, ConfidentialityLevel.L4.value}


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
    llm: "LLMClient | NullLLMClient",
    desensitizer: "DesensitizationEngine",
    trace_id: str,
) -> IngestUploadResponse:
    """创建 Path B 上传任务：把文件字节写入受控存储 + 生成 AI 建议占位。仅业务用户可创建。

    安全：仅在业务用户校验通过后才落盘（被拒调用不持久化任何字节）；存储引用是
    server-only 内部标识，只写入模型 `source_file_ref` 列，不进入任何响应。
    """
    if not caller.is_business_user:
        # 纯 admin / 非业务用户发起入库被拒（强审计）。不落盘任何字节。
        await audit_service.record_denied(
            session, caller=caller, log_type=AuditLogType.exception,
            action=AuditAction.admin_business_denied.value, trace_id=trace_id,
            target_type="ingest_task",
            severity=AlertSeverity.warning, risk_level=AuditRiskLevel.high.value,
            extra={"denied_reason": "admin_business_permission_denied", "attempted": "ingest.upload"},
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

    # R5：请求路径只持久化字节 + 建任务（status=processing），重活（抽取 / R2 内容处理 /
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
        target_scope=target_scope,
        target_project_id=target_project_id,
        created_by=caller.user_id,
    )
    session.add(task)
    await session.flush()  # 取得 task.id 供审计 target_id

    await audit_service.record_event(
        session, caller=caller, log_type=AuditLogType.operation,
        action=AuditAction.ingest_task_created.value, trace_id=trace_id,
        target_type="ingest_task", target_id=task.id,
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


async def _load_task(session: AsyncSession, task_id: uuid.UUID) -> IngestTask:
    from sqlalchemy.orm import selectinload

    task = (
        await session.execute(
            select(IngestTask)
            .where(IngestTask.id == task_id)
            .options(selectinload(IngestTask.ai_result))
        )
    ).scalar_one_or_none()
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

    base = IngestAiResultResponse(
        ingest_task_id=task.id,
        status=task.status,
        suggested_asset_type=ai.suggested_asset_type if ai else None,
        suggested_confidentiality_level=ai.suggested_confidentiality_level if ai else None,
        suggested_ai_access_level=ai.suggested_ai_access_level if ai else None,
        suggested_phase_key=ai.suggested_phase_key if ai else None,
        confidence=ai.confidence if ai else None,
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
        # R2 运营元数据（两视图均可见；provider/model 非密钥）。
        llm_provider=ai.llm_provider if ai else None,
        llm_model=ai.llm_model if ai else None,
        # R5：异步处理中（job 未完成）安全地表示为 processing；完成后按 llm/降级。
        content_processing_status=(
            "processing" if task.status == IngestStatus.processing.value
            else ("llm" if (ai and ai.llm_provider) else "degraded") if ai else None
        ),
    )
    if is_full and ai is not None:
        # 完整视图（创建人 / 治理角色）：补充业务建议正文（三层摘要）+ 抽取全文截断预览。
        base.suggested_title = ai.suggested_title
        base.suggested_one_liner = ai.suggested_one_liner
        base.suggested_summary = ai.suggested_summary
        base.suggested_key_points = ai.suggested_key_points
        base.suggested_tags = ai.suggested_tags
        if ai.extracted_text:
            base.extracted_text_preview = ai.extracted_text[:500]
    # admin 视图：business 字段（含三层摘要正文）与抽取全文预览保持 None。
    return base


def _build_summaries(
    level: str, *, one_liner: str | None, detailed: str, key_points: list[str],
) -> list[KnowledgeAssetSummary]:
    """构建三层摘要行（R2）：one_liner + detailed + key_points（+ L3/L4 脱敏摘要）。

    人工确认值——独立存储于 knowledge_asset_summaries，与 ai_result.suggested_* 分离
    （AI 推荐不被人工确认覆盖，系统设计 §181）。
    """
    one = (one_liner or detailed)[:200]
    rows = [
        KnowledgeAssetSummary(summary_type="one_liner", content=one),
        KnowledgeAssetSummary(summary_type="detailed", content=detailed),
    ]
    pts = [p.strip() for p in key_points if p and p.strip()]
    if pts:
        # key_points 每条一行存于同一 summary 行（读侧按行拆分，沿用既有口径）。
        rows.append(
            KnowledgeAssetSummary(summary_type="key_points", content="\n".join(pts))
        )
    if level in _REDACTED_LEVELS:
        rows.append(
            KnowledgeAssetSummary(
                summary_type="redacted_summary", content="（脱敏）" + detailed[:200],
            )
        )
    return rows


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
    """人工确认入库：创建 KnowledgeAsset 全套 + 把原文推进 WeKnora 底座并回写 doc id。

    WeKnora 写入失败 → **整事务回滚**（不留悬挂资产）+ 标记任务 failed + 审计 + 502。
    未配置 WeKnora（dev）→ 跳过索引，asset 正常创建（接口先行不破坏既有流程）。
    """
    if not caller.is_business_user:
        await audit_service.record_denied(
            session, caller=caller, log_type=AuditLogType.exception,
            action=AuditAction.admin_business_denied.value, trace_id=trace_id,
            target_type="ingest_task", target_id=task_id,
            severity=AlertSeverity.warning, risk_level=AuditRiskLevel.high.value,
            extra={"denied_reason": "admin_business_permission_denied", "attempted": "ingest.confirm"},
        )
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可确认入库")

    task = await _load_task(session, task_id)

    # 归属权限：只有任务创建人或业务治理角色（boss/咨询总监）可确认；
    # 其他业务用户不得确认他人的入库任务。
    if not (task.created_by == caller.user_id or _is_governance(caller)):
        raise _denied(403, "ingest_confirm_forbidden", "只有任务创建人或业务治理角色可确认入库")

    # 幂等：已完成的任务不重复创建资产。
    if task.result_asset_id is not None or task.status == IngestStatus.completed.value:
        raise _denied(409, "ingest_already_confirmed", "该入库任务已确认，不可重复确认")

    # R8_FIX：异步处理未完成（仍 processing）不允许确认——避免把空 AI 结果当人工确认提交。
    if task.status == IngestStatus.processing.value:
        raise _denied(409, "ingest_processing_not_ready", "后台仍在处理该上传，请稍后再确认")

    # R8_FIX：必填字段前置校验——标题 + 至少一个非空摘要（详细或一句话）。
    # 即使 AI 处理失败（status=failed），只要人工补全了这些字段也可确认；否则拒绝空摘要。
    if not (req.title or "").strip():
        raise _denied(422, "ingest_title_required", "标题不能为空")
    _detailed = (req.summary or "").strip()
    _one_liner = (req.one_liner or "").strip()
    if not _detailed and not _one_liner:
        raise _denied(422, "ingest_summary_required", "至少需填写详细摘要或一句话摘要")

    # 枚举字段已由 Pydantic 校验，写入时统一取 .value（DB 仍 String 存储）。
    scope = req.target_scope.value
    # scope 级权限校验。
    if scope == KnowledgeScope.personal.value:
        owner_id = caller.user_id
        project_id = None
    elif scope == KnowledgeScope.project.value:
        if req.target_project_id is None:
            raise _denied(422, "target_project_required", "项目入库必须指定目标项目")
        if req.target_project_id not in caller.active_project_ids:
            raise _denied(403, "project_membership_required", "需为目标项目的有效成员")
        owner_id = caller.user_id
        project_id = req.target_project_id
    elif scope == KnowledgeScope.company.value:
        # 本阶段无审核流：仅 boss / consulting_director 可直接确认公司资产；
        # consultant 直接确认公司资产被拒（不假装完成公司级审核）。
        if not _is_governance(caller):
            raise _denied(
                403,
                "company_confirmation_requires_governance",
                "公司知识需 Boss / 咨询总监确认（审核流待后续任务）",
            )
        owner_id = caller.user_id
        project_id = None
    else:
        raise _denied(422, "invalid_target_scope", "非法的 target_scope")

    # WeKnora KB 懒创建（在建 asset 之前；映射行独立提交，不随 asset 回滚）。
    use_weknora = weknora_enabled()
    kb_id: str | None = None
    if use_weknora:
        from app.core.config import get_settings

        kb_id = await resolve_or_create_kb(
            session, weknora,
            scope=scope, owner_user_id=owner_id if scope == KnowledgeScope.personal.value else None,
            project_id=project_id,
            embedding_model_id=get_settings().weknora_embedding_model_id,
            trace_id=trace_id,
        )

    # 已前置校验 detailed/one_liner 至少一非空：detailed 取详细摘要，缺则回退一句话摘要
    # （绝不再静默写入"（无摘要）"占位）。
    summary_text = (req.summary or "").strip() or (req.one_liner or "").strip()
    confidentiality = req.confidentiality_level.value
    asset = KnowledgeAsset(
        title=req.title,
        scope=scope,
        zone=req.target_zone.value,  # 入库默认 material
        asset_type=req.asset_type.value,
        owner_user_id=owner_id,
        maintainer_user_id=caller.user_id,
        project_id=project_id,
        visibility=req.visibility.value,
        confidentiality_level=confidentiality,
        ai_access_level=req.ai_access_level.value,
        asset_status="active",
        lifecycle_phase_key=req.lifecycle_phase_key,
    )
    version = KnowledgeAssetVersion(
        version_no="v1", version_status="active", created_by=caller.user_id
    )
    asset.versions.append(version)
    for s in _build_summaries(
        confidentiality,
        one_liner=req.one_liner, detailed=summary_text, key_points=req.key_points,
    ):
        s.version = version
        asset.summaries.append(s)
    for tag in req.tags:
        asset.tags.append(KnowledgeAssetTag(tag_name=tag))
    session.add(asset)
    await session.flush()  # 取得 asset.id / version.id

    asset.current_version_id = version.id
    task.result_asset_id = asset.id
    task.status = IngestStatus.completed.value
    task.target_scope = scope
    task.target_project_id = project_id
    task.target_zone = asset.zone
    if task.ai_result is not None:
        task.ai_result.human_corrected = True
        task.ai_result.corrected_title = req.title
        task.ai_result.corrected_summary = req.summary
        task.ai_result.corrected_tags = req.tags

    # ---- 推原文进 WeKnora 底座并回写 doc id（R1）----
    parse_status: str | None = None
    weknora_pushed = False
    weknora_duplicate = False
    if use_weknora and kb_id is not None:
        try:
            file_bytes = storage.resolve_path(task.source_file_ref).read_bytes()
            data = await weknora.upload_file(
                kb_id=kb_id, content=file_bytes,
                file_name=task.source_file_name, mime=task.source_file_mime_type,
                metadata={
                    "asset_id": str(asset.id), "version_id": str(version.id),
                    "scope": scope, "confidentiality_level": confidentiality,
                },
                channel=task.source, trace_id=trace_id,
            )
            version.weknora_kb_id = kb_id
            version.weknora_doc_id = str(data.get("id") or "") or None
            parse_status = str(data.get("parse_status") or "processing")
            version.weknora_parse_status = parse_status
            weknora_pushed = True
        except WeKnoraDuplicateError as dup:
            # 内容已在底座（file_hash 409）：复用既有 doc，不重复入库、不算失败。
            version.weknora_kb_id = kb_id
            version.weknora_doc_id = dup.existing_knowledge_id
            parse_status = "duplicate"
            version.weknora_parse_status = parse_status
            weknora_pushed = True
            weknora_duplicate = True
        except (WeKnoraError, OSError) as exc:
            # 底座写入失败：整事务回滚（不留悬挂资产）→ 标记任务 failed + 审计 + 502。
            await session.rollback()
            await _mark_weknora_failed(session, caller, task_id, exc, trace_id, project_id)
            raise _denied(502, "weknora_upload_failed", "知识底座写入失败，入库已回滚")

    # 入库确认审计：安全元数据，不含原文 / source_file_ref / kb_id / doc_id。
    await audit_service.record_event(
        session, caller=caller, log_type=AuditLogType.operation,
        action=AuditAction.ingest_confirmed.value, trace_id=trace_id,
        target_type="knowledge_asset", target_id=asset.id,
        after={
            "scope": asset.scope,
            "zone": asset.zone,
            "confidentiality_level": asset.confidentiality_level,
            "ai_access_level": asset.ai_access_level,
            "ingest_task_id": str(task.id),
        },
        project_id=project_id,
    )
    if weknora_pushed:
        # 索引埋点：只放安全业务状态，绝不含 kb_id / doc_id。
        await audit_service.record_event(
            session, caller=caller, log_type=AuditLogType.operation,
            action=AuditAction.ingest_weknora_indexed.value, trace_id=trace_id,
            target_type="knowledge_asset", target_id=asset.id,
            extra={
                "parse_status": parse_status,
                "is_duplicate": weknora_duplicate,
                "scope": asset.scope,
            },
            project_id=project_id,
        )
    await session.commit()
    return IngestConfirmResponse(
        task_id=task.id, status=task.status, result_asset_id=asset.id,
        parse_status=parse_status,
    )


async def _mark_weknora_failed(
    session: AsyncSession, caller: CallerContext, task_id: uuid.UUID,
    exc: Exception, trace_id: str, project_id: uuid.UUID | None,
) -> None:
    """WeKnora 写入失败后（事务已回滚）：把任务标记 failed 并写 ingest.failed 审计。

    审计 extra 只放安全元数据——绝不含 kb_id / doc_id / api_key / 原文 / storage_ref。
    """
    task = (
        await session.execute(select(IngestTask).where(IngestTask.id == task_id))
    ).scalar_one_or_none()
    if task is not None:
        task.status = IngestStatus.failed.value
        task.error_type = "weknora_upload_failed"
        task.error_message = "知识底座写入失败，入库已回滚（详见审计）"
    code = getattr(exc, "code", None) or "weknora_upload_failed"
    await audit_service.record_event(
        session, caller=caller, log_type=AuditLogType.exception,
        action=AuditAction.ingest_failed.value, trace_id=trace_id,
        target_type="ingest_task", target_id=task_id,
        severity=AlertSeverity.warning, risk_level=AuditRiskLevel.high.value,
        extra={
            "failure_stage": "weknora_upload",
            "error_code": str(code),
        },
        project_id=project_id,
    )
    await session.commit()


async def refresh_parse(
    session: AsyncSession,
    caller: CallerContext,
    task_id: uuid.UUID,
    *,
    weknora: WeKnoraClient | NullWeKnoraClient,
) -> "IngestParseRefreshResponse":
    """解析状态对账（R1 按需刷新，不引 Celery）。

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


async def list_pending(
    session: AsyncSession,
    caller: CallerContext,
    *,
    source: str | None = None,
) -> list[PendingIngestItem]:
    """业务侧待确认任务列表（PBC-07）。

    用于 `/upload` Path A 面板：拉取尚未入库（result_asset_id 为空）的入库任务。
    与 confirm 的归属规则**完全一致**——只返回调用人确实有权确认的任务：
    任务创建人本人，或业务治理角色（boss / 咨询总监）。无权任务直接从列表过滤，
    不泄露其存在。纯 admin 不是业务用户 → 403（不因系统身份获得业务确认 / 查看权）。

    响应只含安全元数据，绝不含 source_file_ref / storage_ref / WeCom file_id /
    下载 URL / token / WeKnora id / 抽取全文。
    """
    if not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可查看待确认入库任务")

    from sqlalchemy.orm import defer, selectinload

    stmt = (
        select(IngestTask)
        # 待确认 = 尚未生成资产（已 confirm 的任务有 result_asset_id，不再属待确认）。
        .where(IngestTask.result_asset_id.is_(None))
        .options(
            # 列表不返回抽取全文：defer extracted_text 避免查询放大与内容外泄。
            selectinload(IngestTask.ai_result).options(
                defer(IngestTaskAiResult.extracted_text)
            )
        )
        .order_by(IngestTask.created_at.desc())
    )
    if source is not None:
        stmt = stmt.where(IngestTask.source == source)

    tasks = list((await session.execute(stmt)).scalars().all())
    is_gov = _is_governance(caller)
    items: list[PendingIngestItem] = []
    for t in tasks:
        # 归属过滤：仅创建人本人或治理角色可见，与 confirm 放行条件一致。
        if not (is_gov or t.created_by == caller.user_id):
            continue
        ai = t.ai_result
        items.append(
            PendingIngestItem(
                id=t.id,
                source=t.source,
                status=t.status,
                source_file_name=t.source_file_name,
                target_scope=t.target_scope,
                target_project_id=t.target_project_id,
                extraction_status=ai.extraction_status if ai else None,
                error_type=t.error_type,
                error_message=t.error_message,
                suggested_title=ai.suggested_title if ai else None,
                suggested_one_liner=ai.suggested_one_liner if ai else None,
                naming_parsed_fields=ai.naming_parsed_fields if ai else None,
                confidence=ai.confidence if ai else None,
                result_asset_id=t.result_asset_id,
                created_at=t.created_at,
                updated_at=t.updated_at,
            )
        )
    return items


async def list_admin_ingest(
    session: AsyncSession, caller: CallerContext
) -> list[AdminIngestItem]:
    """运营只读列表：admin 或治理角色可看运营元数据（无业务原文 / 内部引用）。"""
    if not (_is_admin(caller) or _is_governance(caller)):
        raise _denied(403, "ingest_admin_forbidden", "无权查看入库运营列表")

    from sqlalchemy.orm import defer, selectinload

    tasks = list(
        (
            await session.execute(
                select(IngestTask).options(
                    # 列表不返回抽取全文：defer extracted_text 避免查询放大。
                    selectinload(IngestTask.ai_result).defer(
                        IngestTaskAiResult.extracted_text
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    items: list[AdminIngestItem] = []
    for t in tasks:
        ai = t.ai_result
        items.append(
            AdminIngestItem(
                id=t.id,
                source=t.source,
                source_file_name=t.source_file_name,
                status=t.status,
                target_scope=t.target_scope,
                confidentiality_level=ai.suggested_confidentiality_level if ai else None,
                ai_access_level=ai.suggested_ai_access_level if ai else None,
                confidence=ai.confidence if ai else None,
                naming_compliant=ai.naming_compliant if ai else None,
                extraction_status=ai.extraction_status if ai else None,
                error_type=t.error_type,
                error_message=t.error_message,
                result_asset_id=t.result_asset_id,
                created_at=t.created_at,
            )
        )
    return items
