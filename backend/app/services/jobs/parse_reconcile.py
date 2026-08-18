"""WeKnora 解析状态对账作业。

扫描 active 版本中 weknora_parse_status 仍处于 pending/processing 的文档，调
`WeKnoraClient.get_knowledge` 回写**安全业务解析状态**。

要求：
- 只更新安全业务字段 `weknora_parse_status`；**绝不**暴露/审计 weknora kb/doc id。
- 单条失败不影响整批（逐条 try/except，continue）。
- 幂等、可重跑：只动 pending/processing 的版本，终态（completed/failed/duplicate）不再碰。
"""

from __future__ import annotations

import time

from sqlalchemy import delete, select
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

# 仍需对账的解析状态（未达终态）。
_PENDING_STATUSES = {"pending", "processing"}
_TERMINAL = {"completed", "failed", "duplicate"}
# 心跳保留上限（避免表无限增长；运维页只读最近一条）。
_HEARTBEAT_KEEP = 500


async def reconcile_parse_statuses(
    session: AsyncSession,
    weknora: WeKnoraClient | NullWeKnoraClient,
    *,
    trace_id: str | None = None,
    limit: int = 200,
) -> dict:
    """对账一批 pending/processing 版本的解析状态。返回安全计数（无 kb/doc id）。"""
    submission = await index_recovery.detect_submission_interruptions(
        session, trace_id=trace_id, limit=limit
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

    started = time.perf_counter()
    rows = list(
        (
            await session.execute(
                select(KnowledgeAssetVersion)
                .where(KnowledgeAssetVersion.version_status == VersionStatus.active.value)
                .where(KnowledgeAssetVersion.weknora_doc_id.is_not(None))
                .where(KnowledgeAssetVersion.weknora_parse_status.in_(_PENDING_STATUSES))
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )

    processed = updated = failed = interrupted = interrupted_recovered = 0
    for v in rows:
        # 查询已过滤 weknora_doc_id IS NOT NULL（见上方 where），此处必非 None。
        if v.weknora_doc_id is None:
            continue
        try:
            data = await weknora.get_knowledge(v.weknora_doc_id, trace_id=trace_id)
        except WeKnoraError:
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
        if new_status != v.weknora_parse_status and new_status in (_TERMINAL | _PENDING_STATUSES):
            from app.services.indexing import _apply_parse_state

            _apply_parse_state(v, new_status)
            updated += 1
        elif recovered_interruption:
            updated += 1
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
