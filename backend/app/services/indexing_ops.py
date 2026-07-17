"""索引批量运维服务：批量 retry-index / 显式 reparse 作业的创建、入队与查询。

权限沿用 ops viewer 边界：系统 admin 或业务治理角色（boss / 咨询总监）可发起。
纯 admin 可做底座运维但**绝不**因此获得业务原文 / 标题读取权——作业只读 server-side 字节
用于重传，响应 / 审计 / 前端只回安全统计与安全筛选条件，绝不含原文 / 内部 ref / WeKnora id。
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from typing import NoReturn

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.identity import User
from app.models.indexing_job import IndexingOperationJob
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.weknora import WeknoraKbMapping
from app.schemas.enums import AuditAction, AuditLogType, CompanyRole, KnowledgeScope
from app.schemas.indexing_ops import (
    MAX_LIMIT,
    REPARSABLE_PARSE_STATUSES,
    RETRYABLE_STATUSES,
    IndexingJobListResponse,
    IndexingJobSummary,
    IndexingReparseRequest,
    IndexingRetryRequest,
)
from app.schemas.permission import CallerContext
from app.services import audit as audit_service
from app.services import error_catalog, weknora_defaults
from app.services.storage import LocalFileStorage
from app.services.weknora_client import weknora_enabled
from app.worker.enqueue import enqueue_indexing_operation

_SCOPES = {"personal", "project", "company", "all"}
_RECENT_JOBS_LIMIT = 20
_TARGET_TOKEN_TTL_SECONDS = 15 * 60
_TARGET_TOKEN_DOMAIN = b"kap:indexing-target-retry:v1:"


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"denied_reason": reason, "message": message}
    )


def _require_ops_viewer(caller: CallerContext) -> None:
    """索引运维：admin（系统运维）或业务治理角色（boss / 咨询总监）可发起。"""
    if CompanyRole.admin.value in caller.active_company_roles or caller.can_discover_l5:
        return
    raise _denied(403, "ops_viewer_required", "无权发起索引运维作业")


def _target_token_cipher() -> Fernet:
    settings = get_settings()
    secret = (settings.csrf_token_secret or "").strip()
    if not secret:
        if settings.app_env == "prod":
            raise RuntimeError("indexing_operation_token_secret_missing")
        secret = "kap-local-indexing-operation-target"
    key = base64.urlsafe_b64encode(hashlib.sha256(_TARGET_TOKEN_DOMAIN + secret.encode()).digest())
    return Fernet(key)


def issue_targeted_retry_token(asset_id: uuid.UUID) -> str:
    """Return an opaque, short-lived browser operation target, never a raw asset identifier."""
    return _target_token_cipher().encrypt(asset_id.hex.encode("ascii")).decode("ascii")


def _resolve_targeted_retry_token(operation_target: str) -> uuid.UUID:
    try:
        payload = _target_token_cipher().decrypt(
            operation_target.encode("ascii"), ttl=_TARGET_TOKEN_TTL_SECONDS
        )
        return uuid.UUID(hex=payload.decode("ascii"))
    except (InvalidToken, UnicodeError, ValueError):
        raise _denied(404, "target_not_actionable", "目标不存在或不可操作") from None


def _clamp_limit(limit) -> int:
    try:
        n = int(limit)
    except (TypeError, ValueError):
        return 100
    return max(1, min(n, MAX_LIMIT))


def _safe_scope(scope) -> str:
    return scope if scope in _SCOPES else "all"


def _resolve_project_id(scope: str, project_id: uuid.UUID | None) -> uuid.UUID | None:
    if scope == KnowledgeScope.project.value and project_id is None:
        raise _denied(422, "project_id_required", "按项目范围运维必须指定 project_id")
    # 非 project 范围忽略传入的 project_id（避免无意义过滤）。
    return project_id if scope == KnowledgeScope.project.value else None


async def _create_and_run(
    session: AsyncSession,
    caller: CallerContext,
    *,
    operation_type: str,
    scope_filter: dict,
    requested_action: AuditAction,
    weknora,
    storage: LocalFileStorage,
    trace_id: str,
    target_asset_id: uuid.UUID | None = None,
) -> IndexingJobSummary:
    """建 job（queued）+ 写发起审计 + 入队（eager 内联跑完）+ 回安全摘要。"""
    job = IndexingOperationJob(
        operation_type=operation_type,
        status="queued",
        scope_filter=scope_filter,
        requested_by_user_id=caller.user_id,
        trace_id=trace_id,
        target_asset_id=target_asset_id,
    )
    session.add(job)
    try:
        await session.flush()  # unique partial index atomically claims a targeted retry
    except IntegrityError:
        await session.rollback()
        if target_asset_id is None:
            raise
        await audit_service.record_denied(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.knowledge_index_target_retry_denied.value,
            trace_id=trace_id,
            target_type="indexing_failure",
            target_id=None,
            extra={"denied_reason": "target_retry_in_progress", "diagnostic_category": "platform"},
        )
        raise _denied(409, "target_retry_in_progress", "该任务正在执行，请勿重复提交") from None
    job_id = job.id

    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=requested_action.value,
        trace_id=trace_id,
        target_type="indexing_operation_job",
        target_id=job_id,
        extra={"job_id": str(job_id), "operation_type": operation_type, "filters": scope_filter},
    )
    await session.commit()

    # 入队：eager（默认/本地/测试）内联同步执行并返回最终 status；非 eager 排队返回 queued。
    await enqueue_indexing_operation(
        session, job_id, weknora=weknora, storage=storage, trace_id=trace_id
    )
    # 重新载入 job 拿最终（或 queued）状态构建安全摘要。
    job = (
        await session.execute(select(IndexingOperationJob).where(IndexingOperationJob.id == job_id))
    ).scalar_one()
    name = await _requester_name(session, job.requested_by_user_id)
    return _job_summary(job, name)


async def _deny_target(
    session: AsyncSession,
    caller: CallerContext,
    *,
    status_code: int,
    reason: str,
    message: str,
    category: str,
    trace_id: str,
) -> NoReturn:
    await audit_service.record_denied(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.knowledge_index_target_retry_denied.value,
        trace_id=trace_id,
        target_type="indexing_failure",
        target_id=None,
        extra={"denied_reason": reason, "diagnostic_category": category},
    )
    raise _denied(status_code, reason, message)


async def _target_configuration_ready(session: AsyncSession, asset: KnowledgeAsset) -> bool:
    if not weknora_enabled():
        return False
    mapping_condition = WeknoraKbMapping.scope == asset.scope
    if asset.scope == KnowledgeScope.personal.value:
        mapping_condition = and_(
            mapping_condition, WeknoraKbMapping.owner_user_id == asset.owner_user_id
        )
    elif asset.scope == KnowledgeScope.project.value:
        mapping_condition = and_(mapping_condition, WeknoraKbMapping.project_id == asset.project_id)
    else:
        mapping_condition = and_(
            mapping_condition,
            WeknoraKbMapping.owner_user_id.is_(None),
            WeknoraKbMapping.project_id.is_(None),
        )
    mapping = (
        await session.execute(
            select(WeknoraKbMapping.id).where(
                mapping_condition, WeknoraKbMapping.status == "active"
            )
        )
    ).scalar_one_or_none()
    if mapping is not None:
        return True
    defaults = await weknora_defaults.get_defaults(session)
    return bool(defaults and defaults.default_embedding_model_id and defaults.default_chat_model_id)


async def create_targeted_retry_job(
    session: AsyncSession,
    caller: CallerContext,
    asset_id: uuid.UUID,
    *,
    weknora,
    storage: LocalFileStorage,
    trace_id: str,
) -> IndexingJobSummary:
    """Atomically claim one still-failed active asset and reuse the existing worker chain."""
    _require_ops_viewer(caller)
    row = (
        await session.execute(
            select(KnowledgeAsset, KnowledgeAssetVersion)
            .join(KnowledgeAssetVersion, KnowledgeAssetVersion.asset_id == KnowledgeAsset.id)
            .where(
                KnowledgeAsset.id == asset_id,
                KnowledgeAsset.asset_status != "deleted",
                KnowledgeAssetVersion.version_status == "active",
            )
        )
    ).one_or_none()
    if row is None:
        await _deny_target(
            session,
            caller,
            status_code=404,
            reason="target_not_actionable",
            message="目标不存在或不可操作",
            category="unknown",
            trace_id=trace_id,
        )
    asset, version = row
    if version.index_status != "index_failed":
        await _deny_target(
            session,
            caller,
            status_code=409,
            reason="target_already_recovered",
            message="索引状态已恢复，无需重试",
            category="platform",
            trace_id=trace_id,
        )
    category, _label = error_catalog.diagnostic(version.index_error_code)
    if not error_catalog.targeted_retry_eligible(version.index_error_code):
        await _deny_target(
            session,
            caller,
            status_code=409,
            reason="target_not_retryable",
            message="当前失败原因不支持单条重试",
            category=category,
            trace_id=trace_id,
        )
    if not await _target_configuration_ready(session, asset):
        await _deny_target(
            session,
            caller,
            status_code=409,
            reason="index_configuration_incomplete",
            message="知识底座配置未完成，暂不能重试",
            category="configuration",
            trace_id=trace_id,
        )
    return await _create_and_run(
        session,
        caller,
        operation_type="retry_index",
        scope_filter={"scope": asset.scope, "statuses": ["index_failed"], "limit": 1},
        requested_action=AuditAction.knowledge_index_target_retry_requested,
        weknora=weknora,
        storage=storage,
        trace_id=trace_id,
        target_asset_id=asset.id,
    )


async def create_targeted_retry_from_operation_target(
    session: AsyncSession,
    caller: CallerContext,
    operation_target: str,
    *,
    weknora,
    storage: LocalFileStorage,
    trace_id: str,
) -> IndexingJobSummary:
    """Resolve an opaque browser target, then apply every server-side retry guard."""
    _require_ops_viewer(caller)
    try:
        asset_id = _resolve_targeted_retry_token(operation_target)
    except HTTPException:
        await _deny_target(
            session,
            caller,
            status_code=404,
            reason="target_not_actionable",
            message="目标不存在或不可操作",
            category="unknown",
            trace_id=trace_id,
        )
    return await create_targeted_retry_job(
        session,
        caller,
        asset_id,
        weknora=weknora,
        storage=storage,
        trace_id=trace_id,
    )


async def create_retry_job(
    session: AsyncSession,
    caller: CallerContext,
    req: IndexingRetryRequest,
    *,
    weknora,
    storage: LocalFileStorage,
    trace_id: str,
) -> IndexingJobSummary:
    """批量 retry-index：对筛选出的 index_failed / skipped / not_indexed 资产入队重试。"""
    _require_ops_viewer(caller)
    scope = _safe_scope(req.scope)
    project_id = _resolve_project_id(scope, req.project_id)
    # 状态白名单过滤（绝不重试 indexed）；空 → 默认 index_failed。
    statuses = [s for s in req.statuses if s in RETRYABLE_STATUSES] or ["index_failed"]
    scope_filter = {
        "scope": scope,
        "project_id": str(project_id) if project_id else None,
        "statuses": statuses,
        "limit": _clamp_limit(req.limit),
    }
    return await _create_and_run(
        session,
        caller,
        operation_type="retry_index",
        scope_filter=scope_filter,
        requested_action=AuditAction.knowledge_index_batch_retry_requested,
        weknora=weknora,
        storage=storage,
        trace_id=trace_id,
    )


async def create_reparse_job(
    session: AsyncSession,
    caller: CallerContext,
    req: IndexingReparseRequest,
    *,
    weknora,
    storage: LocalFileStorage,
    trace_id: str,
) -> IndexingJobSummary:
    """显式 reparse：对已进底座但解析异常（failed / pending / processing）的资产入队重新解析。"""
    _require_ops_viewer(caller)
    scope = _safe_scope(req.scope)
    project_id = _resolve_project_id(scope, req.project_id)
    parse_statuses = [s for s in req.parse_statuses if s in REPARSABLE_PARSE_STATUSES] or [
        "failed",
        "pending",
    ]
    scope_filter = {
        "scope": scope,
        "project_id": str(project_id) if project_id else None,
        "parse_statuses": parse_statuses,
        "limit": _clamp_limit(req.limit),
    }
    return await _create_and_run(
        session,
        caller,
        operation_type="reparse",
        scope_filter=scope_filter,
        requested_action=AuditAction.knowledge_index_reparse_requested,
        weknora=weknora,
        storage=storage,
        trace_id=trace_id,
    )


async def list_jobs(session: AsyncSession, caller: CallerContext) -> IndexingJobListResponse:
    """最近 N 个索引运维作业（安全摘要；无标题 / 原文 / WeKnora id / 存储 ref）。"""
    _require_ops_viewer(caller)
    jobs = list(
        (
            await session.execute(
                select(IndexingOperationJob)
                .order_by(IndexingOperationJob.requested_at.desc())
                .limit(_RECENT_JOBS_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    ids = {j.requested_by_user_id for j in jobs if j.requested_by_user_id}
    names: dict[uuid.UUID, str] = {}
    if ids:
        for uid, uname in (
            await session.execute(select(User.id, User.name).where(User.id.in_(ids)))
        ).all():
            names[uid] = uname
    items = [
        _job_summary(j, names.get(j.requested_by_user_id) if j.requested_by_user_id else None)
        for j in jobs
    ]
    return IndexingJobListResponse(items=items, total=len(items))


async def _requester_name(session: AsyncSession, user_id: uuid.UUID | None) -> str | None:
    if user_id is None:
        return None
    return (await session.execute(select(User.name).where(User.id == user_id))).scalar_one_or_none()


def _job_summary(job: IndexingOperationJob, name: str | None) -> IndexingJobSummary:
    return IndexingJobSummary(
        job_id=job.id,
        operation_type=job.operation_type,
        status=job.status,
        scope_filter=job.scope_filter,
        requested_by_name=name,
        requested_at=job.requested_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        total_count=job.total_count,
        success_count=job.success_count,
        failed_count=job.failed_count,
        skipped_count=job.skipped_count,
        error_code=job.error_code,
        error_message=job.error_message,
        trace_id=job.trace_id,
    )
