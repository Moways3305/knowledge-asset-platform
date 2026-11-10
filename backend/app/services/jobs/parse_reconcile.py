"""WeKnora 解析状态对账作业。

扫描 active 版本中 weknora_parse_status 仍处于 pending/processing 的文档，调
`WeKnoraClient.get_knowledge` 回写**安全业务解析状态**。

要求：
- 只更新安全业务字段 `weknora_parse_status`；**绝不**暴露/审计 weknora kb/doc id。
- 单条失败不影响整批（逐条 try/except，continue）。
- 幂等、可重跑：只动 pending/processing 的版本，终态（completed/failed/duplicate）不再碰。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.utils import utc_now
from app.models.indexing_job import OpsReconcileHeartbeat
from app.models.knowledge import KnowledgeAssetVersion
from app.schemas.enums import AuditAction, AuditLogType, VersionStatus
from app.services import audit as audit_service
from app.services import error_catalog, index_recovery
from app.services.weknora_client import (
    NullWeKnoraClient,
    WeKnoraClient,
    WeKnoraError,
    weknora_enabled,
)
from app.services.weknora_parse_state import PENDING_PARSE_STATUSES, TERMINAL_PARSE_STATUSES

# 仍需对账的解析状态（未达终态）。
_PENDING_STATUSES = PENDING_PARSE_STATUSES
_TERMINAL = TERMINAL_PARSE_STATUSES
# 心跳保留上限（避免表无限增长；运维页只读最近一条）。
_HEARTBEAT_KEEP = 500
_LEASE_SECONDS = 120
# A status lookup should not monopolize the shared default worker queue. The
# batch deadline also bounds a run containing many independently slow documents.
_REQUEST_TIMEOUT_SECONDS = 10
_BATCH_TIMEOUT_SECONDS = 20
_MAX_BATCH = 200
_IDLE_RELEASE_DELAY_SECONDS = 0.1


async def _get_knowledge(
    weknora: WeKnoraClient | NullWeKnoraClient,
    document_id: str,
    *,
    trace_id: str | None,
    release_idle: Callable[[], Awaitable[None]] | None,
) -> dict:
    # Only a task-owned engine may provide this callback. Fast status queries
    # reuse its idle connection; a slow query gives it back to PostgreSQL. There
    # are no business transactions or concurrent DB operations during this wait.
    request = asyncio.create_task(weknora.get_knowledge(document_id, trace_id=trace_id))
    try:
        if release_idle is not None:
            done, _ = await asyncio.wait({request}, timeout=_IDLE_RELEASE_DELAY_SECONDS)
            if not done:
                await release_idle()
        return await request
    finally:
        if not request.done():
            request.cancel()
        await asyncio.gather(request, return_exceptions=True)


@asynccontextmanager
async def _claim(session, snapshot):
    """CAS claim survives commits without holding a connection during network I/O."""
    token = str(uuid.uuid4())
    now = utc_now()
    claimed = await session.scalar(
        update(KnowledgeAssetVersion)
        .where(
            KnowledgeAssetVersion.id == snapshot.id,
            KnowledgeAssetVersion.version_status == VersionStatus.active.value,
            or_(
                KnowledgeAssetVersion.parse_reconcile_until.is_(None),
                KnowledgeAssetVersion.parse_reconcile_until <= now,
            ),
            *[
                getattr(KnowledgeAssetVersion, key).is_not_distinct_from(value)
                for key, value in snapshot._mapping.items()
            ],
        )
        .values(
            parse_reconcile_token=token,
            parse_reconcile_until=now + timedelta(seconds=_LEASE_SECONDS),
        )
        .returning(KnowledgeAssetVersion.id)
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    if claimed is None:
        yield None
        return
    try:
        yield token
    finally:
        await session.rollback()
        # Never release another worker's reclaimed lease. Keep the timestamp as a
        # generation marker so an already-selected stale snapshot cannot claim again.
        await session.execute(
            update(KnowledgeAssetVersion)
            .where(
                KnowledgeAssetVersion.id == snapshot.id,
                KnowledgeAssetVersion.parse_reconcile_token == token,
            )
            .values(parse_reconcile_token=None, parse_reconcile_until=utc_now())
            .execution_options(synchronize_session=False)
        )
        await session.commit()


async def reconcile_parse_statuses(
    session: AsyncSession,
    weknora: WeKnoraClient | NullWeKnoraClient,
    *,
    trace_id: str | None = None,
    limit: int = 200,
    release_idle: Callable[[], Awaitable[None]] | None = None,
) -> dict:
    """对账一批 pending/processing 版本的解析状态。返回安全计数（无 kb/doc id）。"""
    started = time.perf_counter()
    deadline = started + _BATCH_TIMEOUT_SECONDS
    batch_limit = max(0, min(int(limit), _MAX_BATCH))
    submission = (
        await index_recovery.detect_submission_interruptions(
            session, trace_id=trace_id, limit=batch_limit
        )
        if batch_limit
        else {"scanned": 0, "identified": 0, "skipped_fresh_jobs": 0, "exceptions": 0}
    )
    if not weknora_enabled():
        # 未配置底座：无可对账项，安全空跑。
        await _record_heartbeat(
            session,
            processed=0,
            updated=0,
            failed=0,
            duration_ms=0,
            submission=submission,
        )
        await session.commit()
        return {
            "processed": 0,
            "updated": 0,
            "failed": 0,
            "skipped": "weknora_not_configured",
            **{f"submission_{key}": value for key, value in submission.items()},
        }

    rows = list(
        (
            await session.execute(
                select(
                    KnowledgeAssetVersion.id,
                    KnowledgeAssetVersion.weknora_doc_id,
                    KnowledgeAssetVersion.weknora_kb_id,
                    KnowledgeAssetVersion.weknora_parse_status,
                    KnowledgeAssetVersion.index_status,
                    KnowledgeAssetVersion.index_error_code,
                    KnowledgeAssetVersion.index_reconcile_failure_count,
                    KnowledgeAssetVersion.index_last_reconcile_failed_at,
                    KnowledgeAssetVersion.parse_reconcile_until,
                )
                .where(KnowledgeAssetVersion.version_status == VersionStatus.active.value)
                .where(KnowledgeAssetVersion.weknora_doc_id.is_not(None))
                .where(KnowledgeAssetVersion.weknora_parse_status.in_(_PENDING_STATUSES))
                .where(
                    or_(
                        KnowledgeAssetVersion.parse_reconcile_until.is_(None),
                        KnowledgeAssetVersion.parse_reconcile_until <= utc_now(),
                    )
                )
                # Released leases retain their last-attempt timestamp. Oldest
                # unobserved work goes first, including an expired owner. Using
                # created_at for new rows avoids starving old work when new
                # documents continuously arrive; ID is only a stable tie-break.
                .order_by(
                    func.coalesce(
                        KnowledgeAssetVersion.parse_reconcile_until,
                        KnowledgeAssetVersion.created_at,
                    ),
                    KnowledgeAssetVersion.id,
                )
                .limit(batch_limit)
            )
        ).all()
    )
    # Release the read transaction/connection before any upstream network wait.
    await session.commit()

    processed = updated = failed = interrupted = interrupted_recovered = 0
    budget_exhausted = False
    for snapshot in rows:
        if time.perf_counter() >= deadline:
            budget_exhausted = True
            break
        async with _claim(session, snapshot) as token:
            if token is None:
                continue
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                budget_exhausted = True
                break
            request_budget = min(_REQUEST_TIMEOUT_SECONDS, remaining)
            upstream_failed = False
            try:
                data = await asyncio.wait_for(
                    _get_knowledge(
                        weknora,
                        snapshot.weknora_doc_id,
                        trace_id=trace_id,
                        release_idle=release_idle,
                    ),
                    timeout=request_budget,
                )
            except asyncio.TimeoutError:
                if request_budget < _REQUEST_TIMEOUT_SECONDS:
                    # Our batch budget is not evidence that provider parsing
                    # failed. Release/rotate the claim without adding failures.
                    budget_exhausted = True
                    break
                upstream_failed = True
                data = {}
            except (WeKnoraError, httpx.RequestError):
                upstream_failed = True
                data = {}
            # Re-read under a short lock. Discard responses if retry, archive or another
            # reconciler changed the binding/status/evidence while the request was running.
            v = await session.scalar(
                select(KnowledgeAssetVersion)
                .where(
                    KnowledgeAssetVersion.id == snapshot.id,
                    KnowledgeAssetVersion.version_status == VersionStatus.active.value,
                    KnowledgeAssetVersion.parse_reconcile_token == token,
                    KnowledgeAssetVersion.parse_reconcile_until > utc_now(),
                    *[
                        getattr(KnowledgeAssetVersion, key).is_not_distinct_from(value)
                        for key, value in snapshot._mapping.items()
                        if key not in {"id", "parse_reconcile_until"}
                    ],
                )
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
            if v is None:
                await session.commit()
                continue
            if upstream_failed:
                # 单条失败不中断整批。
                failed += 1
                v.index_reconcile_failure_count = (v.index_reconcile_failure_count or 0) + 1
                v.index_last_reconcile_failed_at = utc_now()
                if index_recovery.should_mark_interrupted(v, now=utc_now()):
                    v.index_status = "index_failed"
                    v.index_error_code = index_recovery.INTERRUPTED_ERROR_CODE
                    v.index_error_message = error_catalog.user_message(
                        index_recovery.INTERRUPTED_ERROR_CODE
                    )
                    interrupted += 1
                    updated += 1
                    await audit_service.record_system_event(
                        session,
                        log_type=AuditLogType.operation,
                        action=AuditAction.knowledge_index_interrupted_detected.value,
                        trace_id=trace_id or "",
                        target_type="knowledge_asset_version",
                        target_id=v.id,
                        before={"index_status": "indexing"},
                        after={
                            "index_status": "index_failed",
                            "reason_code": index_recovery.INTERRUPTED_ERROR_CODE,
                        },
                        extra={"reconcile_failure_count": v.index_reconcile_failure_count},
                    )
                await session.commit()
                continue
            processed += 1
            v.index_reconcile_failure_count = 0
            v.index_last_reconcile_failed_at = None
            new_status = str(data.get("parse_status") or v.weknora_parse_status)
            recovered_interruption = False
            if (
                new_status in _PENDING_STATUSES
                and v.index_status == "index_failed"
                and v.index_error_code == index_recovery.INTERRUPTED_ERROR_CODE
            ):
                v.index_status = "indexing"
                v.index_error_code = None
                v.index_error_message = None
                recovered_interruption = True
                interrupted_recovered += 1
                await audit_service.record_system_event(
                    session,
                    log_type=AuditLogType.operation,
                    action=AuditAction.knowledge_index_interrupted_recovered.value,
                    trace_id=trace_id or "",
                    target_type="knowledge_asset_version",
                    target_id=v.id,
                    before={
                        "index_status": "index_failed",
                        "reason_code": index_recovery.INTERRUPTED_ERROR_CODE,
                    },
                    after={
                        "index_status": "indexing",
                        "parse_status": new_status,
                    },
                )
            if new_status != v.weknora_parse_status and new_status in (
                _TERMINAL | _PENDING_STATUSES
            ):
                from app.services.indexing import _apply_parse_state

                _apply_parse_state(v, new_status)
                updated += 1
            elif recovered_interruption:
                updated += 1
            await session.commit()
    await _record_heartbeat(
        session,
        processed=processed,
        updated=updated,
        failed=failed,
        duration_ms=int((time.perf_counter() - started) * 1000),
        submission=submission,
    )
    await session.commit()
    return {
        "processed": processed,
        "updated": updated,
        "failed": failed,
        "interrupted": interrupted,
        "interrupted_recovered": interrupted_recovered,
        "budget_exhausted": budget_exhausted,
        **{f"submission_{key}": value for key, value in submission.items()},
    }


async def _record_heartbeat(
    session: AsyncSession,
    *,
    processed: int,
    updated: int,
    failed: int,
    duration_ms: int,
    submission: dict[str, int] | None = None,
) -> None:
    """写入对账心跳并裁剪旧行（同一事务，随 commit 生效）。"""
    submission = submission or {}
    session.add(
        OpsReconcileHeartbeat(
            observed_at=utc_now(),
            processed=processed,
            updated=updated,
            failed=failed,
            submission_scanned=submission.get("scanned", 0),
            submission_interrupted=submission.get("identified", 0),
            submission_fresh_job_skipped=submission.get("skipped_fresh_jobs", 0),
            submission_exceptions=submission.get("exceptions", 0),
            duration_ms=duration_ms,
        )
    )
    keep = (
        select(OpsReconcileHeartbeat.id)
        .order_by(OpsReconcileHeartbeat.observed_at.desc(), OpsReconcileHeartbeat.id.desc())
        .limit(_HEARTBEAT_KEEP)
    )
    await session.execute(
        delete(OpsReconcileHeartbeat).where(OpsReconcileHeartbeat.id.not_in(keep))
    )
