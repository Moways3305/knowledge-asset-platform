"""索引批量运维后台作业。

执行运维发起的**批量 retry-index** / **显式 reparse** 作业：按 job 的安全筛选条件选出
active 资产版本，逐条复用 `indexing.index_asset_version` /
`indexing.reparse_asset_version` 推进底座，单条失败不终止整个 job，最后写安全统计 + 完成审计。

安全：作业可读取 server-side 原始文件用于重传，但**绝不**把原文 / 文件名 / storage ref /
WeKnora kb·doc id / 上游原始 message 写入 job 行 / 审计 / 响应。错误一律经
`error_catalog.safe_code()` 归一。job 级异常 → status=failed + 安全 code/message。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import safe_log_exception
from app.db.utils import utc_now
from app.models.identity import ProjectMember, User
from app.models.indexing_job import IndexingOperationJob
from app.models.ingest import IngestTask
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.schemas.enums import (
    AssetStatus,
    AuditAction,
    AuditLogType,
    KnowledgeScope,
)
from app.schemas.permission import CallerContext
from app.services import audit as audit_service
from app.services import error_catalog, indexing
from app.services.permission import build_caller_context
from app.services.storage import LocalFileStorage
from app.services.weknora_client import (
    NullWeKnoraClient,
    WeKnoraClient,
    weknora_enabled,
)

_logger = logging.getLogger(__name__)

_DELETED = AssetStatus.deleted.value
# 已处理终态（再次入队/重跑直接跳过，保证幂等）。
_DONE_STATUSES = {"completed", "completed_with_errors", "failed"}


def _scope_conditions(scope: str | None, project_id):
    """把安全 scope_filter 转为查询条件（scope=all / 缺省 → 无 scope 约束）。"""
    conds = []
    if scope and scope != "all":
        conds.append(KnowledgeAsset.scope == scope)
    if scope == KnowledgeScope.project.value and project_id is not None:
        conds.append(KnowledgeAsset.project_id == uuid.UUID(str(project_id)))
    return conds


@dataclass
class _Target:
    """单条待处理资产的安全字段快照（纯标量；避免 ORM 对象在循环内被 rollback 过期）。"""

    asset_id: uuid.UUID
    version_id: uuid.UUID
    scope: str
    owner_user_id: uuid.UUID | None
    project_id: uuid.UUID | None
    confidentiality: str


async def _select_targets(session: AsyncSession, job: IndexingOperationJob) -> list[_Target]:
    """按 job 安全筛选条件选出待处理资产的标量快照。仅 active 非删除资产。

    返回纯标量（非 ORM 对象）——`mark_index_failed` 会在循环内 `rollback`，过期所有 ORM 实例；
    用快照可避免下一条访问已过期对象时触发隐式 IO 失败。
    """
    sf = job.scope_filter or {}
    scope = sf.get("scope")
    project_id = sf.get("project_id")
    limit = int(sf.get("limit") or 100)

    base_conds = [
        KnowledgeAssetVersion.version_status == "active",
        KnowledgeAsset.asset_status != _DELETED,
        *_scope_conditions(scope, project_id),
    ]
    if job.target_asset_id is not None:
        base_conds.append(KnowledgeAsset.id == job.target_asset_id)
    if job.operation_type == "reparse":
        parse_statuses = list(sf.get("parse_statuses") or [])
        base_conds.append(KnowledgeAssetVersion.index_status == "indexed")
        base_conds.append(KnowledgeAssetVersion.weknora_doc_id.is_not(None))
        if parse_statuses:
            base_conds.append(KnowledgeAssetVersion.weknora_parse_status.in_(parse_statuses))
    else:  # retry_index
        statuses = list(sf.get("statuses") or ["index_failed"])
        base_conds.append(KnowledgeAssetVersion.index_status.in_(statuses))

    rows = (
        await session.execute(
            select(
                KnowledgeAsset.id,
                KnowledgeAssetVersion.id,
                KnowledgeAsset.scope,
                KnowledgeAsset.owner_user_id,
                KnowledgeAsset.project_id,
                KnowledgeAsset.confidentiality_level,
            )
            .join(KnowledgeAssetVersion, KnowledgeAssetVersion.asset_id == KnowledgeAsset.id)
            .where(*base_conds)
            .order_by(KnowledgeAsset.updated_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        _Target(aid, vid, scope_, owner, pid, conf) for aid, vid, scope_, owner, pid, conf in rows
    ]


async def _build_actor(session: AsyncSession, job: IndexingOperationJob) -> CallerContext:
    """以发起人身份构建审计 actor（作业代其完成底座运维）。"""
    from sqlalchemy.orm import selectinload

    if job.requested_by_user_id is not None:
        user = (
            await session.execute(
                select(User)
                .where(User.id == job.requested_by_user_id)
                .options(
                    selectinload(User.company_roles),
                    selectinload(User.project_members).selectinload(ProjectMember.project),
                )
            )
        ).scalar_one_or_none()
        if user is not None:
            return build_caller_context(user)
    return CallerContext(
        user_id=job.requested_by_user_id or uuid.UUID(int=0),
        is_active=True,
        active_company_roles=set(),
        active_project_ids=set(),
    )


async def _source_for_asset(session: AsyncSession, asset_id: uuid.UUID) -> IngestTask | None:
    return (
        (
            await session.execute(
                select(IngestTask)
                .where(IngestTask.result_asset_id == asset_id)
                .order_by(IngestTask.created_at.desc())
            )
        )
        .scalars()
        .first()
    )


async def _process_one(
    session: AsyncSession,
    weknora: WeKnoraClient | NullWeKnoraClient,
    storage: LocalFileStorage,
    *,
    operation_type: str,
    target: _Target,
    trace_id: str | None,
) -> str:
    """处理单条资产：返回 'indexed' | 'skipped' | 'failed'（安全状态，不外泄内部 id）。"""
    asset_id = target.asset_id
    version_id = target.version_id
    scope = target.scope
    owner_user_id = target.owner_user_id
    confidentiality = target.confidentiality
    project_id = target.project_id

    # 底座未启用：retry 标 skipped（清理上一轮失败残留）；reparse 无底座可刷新 → skipped。
    if not weknora_enabled():
        v = (
            await session.execute(
                select(KnowledgeAssetVersion).where(KnowledgeAssetVersion.id == version_id)
            )
        ).scalar_one_or_none()
        if v is not None and operation_type == "retry_index":
            v.index_status = "skipped"
            v.index_error_code = None
            v.index_error_message = None
            v.weknora_parse_status = None
        await session.commit()
        return "skipped"

    task = await _source_for_asset(session, asset_id)
    if task is None or not task.source_file_ref:
        outcome = await indexing.mark_index_failed(
            session, version_id=version_id, error_code="source_file_unreadable"
        )
        return "failed" if outcome.index_status == "index_failed" else outcome.index_status

    try:
        file_bytes = storage.resolve_path(task.source_file_ref).read_bytes()
    except OSError:
        outcome = await indexing.mark_index_failed(
            session, version_id=version_id, error_code="source_file_unreadable"
        )
        return "failed"

    if operation_type == "reparse":
        outcome = await indexing.reparse_asset_version(
            session,
            weknora,
            asset_id=asset_id,
            version_id=version_id,
            scope=scope,
            owner_user_id=owner_user_id,
            project_id=project_id,
            confidentiality=confidentiality,
            file_bytes=file_bytes,
            source_file_name=task.source_file_name,
            source_file_mime=task.source_file_mime_type,
            channel=task.source,
            trace_id=trace_id,
        )
    else:
        outcome = await indexing.index_asset_version(
            session,
            weknora,
            asset_id=asset_id,
            version_id=version_id,
            scope=scope,
            owner_user_id=owner_user_id,
            project_id=project_id,
            confidentiality=confidentiality,
            file_bytes=file_bytes,
            source_file_name=task.source_file_name,
            source_file_mime=task.source_file_mime_type,
            channel=task.source,
            trace_id=trace_id,
        )
    if outcome.index_status == "indexed":
        return "indexed"
    if outcome.index_status == "skipped":
        return "skipped"
    return "failed"


async def run_operation_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    weknora: WeKnoraClient | NullWeKnoraClient,
    storage: LocalFileStorage,
    trace_id: str | None = None,
) -> str:
    """执行一个索引运维作业（幂等、可重跑）。返回最终 status。

    单条失败不终止整个 job；job 级异常 → failed + 安全 code/message。完成写安全统计 + 审计。
    """
    job = (
        await session.execute(select(IndexingOperationJob).where(IndexingOperationJob.id == job_id))
    ).scalar_one_or_none()
    if job is None:
        return "not_found"
    if job.status in _DONE_STATUSES:
        return job.status  # 幂等：已处理终态不重跑。

    actor = await _build_actor(session, job)
    # 捕获 job 标量字段到局部：循环内单条失败会 `rollback()` 过期所有 ORM 对象（含 job），
    # 之后再访问 `job.*` 会触发隐式 IO（MissingGreenlet）。用局部值规避。
    job_trace = trace_id or job.trace_id
    operation_type = job.operation_type
    targeted_retry = job.target_asset_id is not None

    job.status = "running"
    job.started_at = utc_now()
    await session.commit()

    success = failed = skipped = 0
    try:
        targets = await _select_targets(session, job)
        total = len(targets)
        for target in targets:
            try:
                result = await _process_one(
                    session,
                    weknora,
                    storage,
                    operation_type=operation_type,
                    target=target,
                    trace_id=job_trace,
                )
            except Exception as exc:  # noqa: BLE001  # 单条异常不终止整个 job
                safe_log_exception(
                    _logger,
                    "indexing_item_failed",
                    exc,
                    include_summary=False,
                    level=logging.WARNING,
                )
                await session.rollback()
                result = "failed"
            if result == "indexed":
                success += 1
            elif result == "skipped":
                skipped += 1
            else:
                failed += 1
    except Exception as exc:  # noqa: BLE001  # job 级异常 → failed + 安全 code/message
        safe_log_exception(_logger, "indexing_job_failed", exc, include_summary=False)
        await session.rollback()
        code = error_catalog.safe_code(getattr(exc, "code", None) or type(exc).__name__)
        job = (
            await session.execute(
                select(IndexingOperationJob).where(IndexingOperationJob.id == job_id)
            )
        ).scalar_one_or_none()
        if job is not None:
            job.status = "failed"
            job.error_code = code
            job.error_message = error_catalog.user_message(code)
            job.finished_at = utc_now()
            await session.commit()
        return "failed"

    # 重新载入 job（循环内多次 commit/rollback 后以最新状态回写统计）。
    job = (
        await session.execute(select(IndexingOperationJob).where(IndexingOperationJob.id == job_id))
    ).scalar_one_or_none()
    if job is None:
        return "not_found"
    job.total_count = total
    job.success_count = success
    job.failed_count = failed
    job.skipped_count = skipped
    job.status = "completed" if failed == 0 else "completed_with_errors"
    job.finished_at = utc_now()
    await session.commit()

    completed_action = (
        AuditAction.knowledge_index_target_retry_completed
        if targeted_retry
        else (
            AuditAction.knowledge_index_reparse_completed
            if job.operation_type == "reparse"
            else AuditAction.knowledge_index_batch_retry_completed
        )
    )
    await audit_service.record_event(
        session,
        caller=actor,
        log_type=AuditLogType.operation,
        action=completed_action.value,
        trace_id=job_trace,
        target_type="indexing_operation_job",
        target_id=job.id,
        extra={
            "job_id": str(job.id),
            "operation_type": job.operation_type,
            "filters": job.scope_filter,
            "total": total,
            "success": success,
            "failed": failed,
            "skipped": skipped,
            "status": job.status,
        },
    )
    await session.commit()
    return job.status
