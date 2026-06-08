"""索引批量运维服务：批量 retry-index / 显式 reparse 作业的创建、入队与查询。

权限沿用 ops viewer 边界：系统 admin 或业务治理角色（boss / 咨询总监）可发起。
纯 admin 可做底座运维但**绝不**因此获得业务原文 / 标题读取权——作业只读 server-side 字节
用于重传，响应 / 审计 / 前端只回安全统计与安全筛选条件，绝不含原文 / 内部 ref / WeKnora id。
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import User
from app.models.indexing_job import IndexingOperationJob
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
from app.services.storage import LocalFileStorage
from app.worker.enqueue import enqueue_indexing_operation

_SCOPES = {"personal", "project", "company", "all"}
_RECENT_JOBS_LIMIT = 20


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"denied_reason": reason, "message": message})


def _require_ops_viewer(caller: CallerContext) -> None:
    """索引运维：admin（系统运维）或业务治理角色（boss / 咨询总监）可发起。"""
    if CompanyRole.admin.value in caller.active_company_roles or caller.can_discover_l5:
        return
    raise _denied(403, "ops_viewer_required", "无权发起索引运维作业")


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
) -> IndexingJobSummary:
    """建 job（queued）+ 写发起审计 + 入队（eager 内联跑完）+ 回安全摘要。"""
    job = IndexingOperationJob(
        operation_type=operation_type,
        status="queued",
        scope_filter=scope_filter,
        requested_by_user_id=caller.user_id,
        trace_id=trace_id,
    )
    session.add(job)
    await session.flush()  # 取 job.id 供审计 / 入队
    job_id = job.id

    await audit_service.record_event(
        session, caller=caller, log_type=AuditLogType.operation,
        action=requested_action.value, trace_id=trace_id,
        target_type="indexing_operation_job", target_id=job_id,
        extra={"job_id": str(job_id), "operation_type": operation_type, "filters": scope_filter},
    )
    await session.commit()

    # 入队：eager（默认/本地/测试）内联同步执行并返回最终 status；非 eager 排队返回 queued。
    await enqueue_indexing_operation(
        session, job_id, weknora=weknora, storage=storage, trace_id=trace_id
    )
    # 重新载入 job 拿最终（或 queued）状态构建安全摘要。
    job = (
        await session.execute(
            select(IndexingOperationJob).where(IndexingOperationJob.id == job_id)
        )
    ).scalar_one()
    name = await _requester_name(session, job.requested_by_user_id)
    return _job_summary(job, name)


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
        session, caller,
        operation_type="retry_index", scope_filter=scope_filter,
        requested_action=AuditAction.knowledge_index_batch_retry_requested,
        weknora=weknora, storage=storage, trace_id=trace_id,
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
    parse_statuses = [
        s for s in req.parse_statuses if s in REPARSABLE_PARSE_STATUSES
    ] or ["failed", "pending"]
    scope_filter = {
        "scope": scope,
        "project_id": str(project_id) if project_id else None,
        "parse_statuses": parse_statuses,
        "limit": _clamp_limit(req.limit),
    }
    return await _create_and_run(
        session, caller,
        operation_type="reparse", scope_filter=scope_filter,
        requested_action=AuditAction.knowledge_index_reparse_requested,
        weknora=weknora, storage=storage, trace_id=trace_id,
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
        ).scalars().all()
    )
    ids = {j.requested_by_user_id for j in jobs if j.requested_by_user_id}
    names: dict[uuid.UUID, str] = {}
    if ids:
        for uid, uname in (
            await session.execute(select(User.id, User.name).where(User.id.in_(ids)))
        ).all():
            names[uid] = uname
    items = [_job_summary(j, names.get(j.requested_by_user_id)) for j in jobs]
    return IndexingJobListResponse(items=items, total=len(items))


async def _requester_name(session: AsyncSession, user_id: uuid.UUID | None) -> str | None:
    if user_id is None:
        return None
    return (
        await session.execute(select(User.name).where(User.id == user_id))
    ).scalar_one_or_none()


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

