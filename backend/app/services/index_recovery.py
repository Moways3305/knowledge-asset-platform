"""索引中断判定与安全恢复文案的单一口径。

解析中断与提交中断是两条独立证据链：前者要求已有底座文档并积累连续
对账失败；后者要求本地 ``indexing`` 长时间没有形成文档/解析状态绑定，且
没有新鲜的同资产索引作业。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.utils import utc_now
from app.models.indexing_job import IndexingOperationJob
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.schemas.enums import AssetStatus, AuditAction, AuditLogType, VersionStatus
from app.services import audit as audit_service
from app.services import error_catalog

INTERRUPTED_ERROR_CODE = "index_interrupted"
SUBMISSION_INTERRUPTED_ERROR_CODE = "index_submission_interrupted"
_logger = logging.getLogger(__name__)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def minimum_age_minutes() -> int:
    return max(1, int(get_settings().index_interrupted_min_age_minutes))


def required_failure_count() -> int:
    return max(2, int(get_settings().index_interrupted_reconcile_failures))


def is_old_enough(version: KnowledgeAssetVersion, *, now: datetime) -> bool:
    started_at = version.activated_at or version.created_at
    return _aware(started_at) <= _aware(now) - timedelta(minutes=minimum_age_minutes())


def submission_is_incomplete(version: KnowledgeAssetVersion) -> bool:
    return version.weknora_doc_id is None or version.weknora_parse_status is None


def should_mark_submission_interrupted(version: KnowledgeAssetVersion, *, now: datetime) -> bool:
    """Pure predicate used by the scanner and focused state-machine tests."""
    return (
        version.version_status == VersionStatus.active.value
        and version.index_status == "indexing"
        and submission_is_incomplete(version)
        and is_old_enough(version, now=now)
    )


def should_mark_interrupted(version: KnowledgeAssetVersion, *, now: datetime) -> bool:
    return (
        version.index_status == "indexing"
        and version.weknora_parse_status in {"pending", "processing"}
        and is_old_enough(version, now=now)
        and version.index_reconcile_failure_count >= required_failure_count()
    )


def recovery_state(index_status: str, error_code: str | None) -> str:
    if index_status == "index_failed" and error_code == SUBMISSION_INTERRUPTED_ERROR_CODE:
        return "submission_interrupted"
    if index_status == "index_failed" and error_code == INTERRUPTED_ERROR_CODE:
        return "parse_interrupted"
    if index_status == "index_failed":
        return "failed"
    if index_status == "not_indexed":
        return "waiting"
    if index_status == "skipped":
        return "skipped"
    if index_status == "indexing":
        return "processing"
    return "searchable" if index_status == "indexed" else "unknown"


async def detect_submission_interruptions(
    session: AsyncSession,
    *,
    trace_id: str | None = None,
    limit: int = 200,
    now: datetime | None = None,
) -> dict[str, int]:
    """Atomically identify stale, unbound index submissions.

    The query intentionally excludes versions with a complete doc+parse binding. Those
    remain exclusively in ``parse_reconcile`` and require consecutive upstream failures.
    Returned/logged values are safe aggregate counts only.
    """
    observed_at = _aware(now or utc_now())
    cutoff = observed_at - timedelta(minutes=minimum_age_minutes())
    rows = list(
        (
            await session.execute(
                select(KnowledgeAsset, KnowledgeAssetVersion)
                .join(KnowledgeAssetVersion, KnowledgeAssetVersion.asset_id == KnowledgeAsset.id)
                .where(
                    # Mutation boundary is intentionally stricter than ops reporting:
                    # archived/deprecated/needs_update assets must not be moved back into
                    # a recovery workflow merely because an old active version remains.
                    KnowledgeAsset.asset_status == AssetStatus.active.value,
                    KnowledgeAssetVersion.version_status == VersionStatus.active.value,
                    KnowledgeAssetVersion.index_status == "indexing",
                    or_(
                        KnowledgeAssetVersion.weknora_doc_id.is_(None),
                        KnowledgeAssetVersion.weknora_parse_status.is_(None),
                    ),
                    or_(
                        KnowledgeAssetVersion.activated_at <= cutoff,
                        KnowledgeAssetVersion.activated_at.is_(None),
                    ),
                    KnowledgeAssetVersion.created_at <= cutoff,
                )
                .with_for_update(skip_locked=True)
                .limit(max(1, min(int(limit), 1000)))
            )
        ).all()
    )
    scanned = len(rows)
    if not rows:
        result = {"scanned": 0, "identified": 0, "skipped_fresh_jobs": 0, "exceptions": 0}
        _logger.info("index_submission_interruption_scan", extra=result)
        return result

    asset_ids = {asset.id for asset, _version in rows}
    fresh_job_asset_ids = set(
        (
            await session.execute(
                select(IndexingOperationJob.target_asset_id).where(
                    IndexingOperationJob.target_asset_id.in_(asset_ids),
                    IndexingOperationJob.operation_type == "retry_index",
                    IndexingOperationJob.status.in_(("queued", "running")),
                    or_(
                        IndexingOperationJob.updated_at >= cutoff,
                        IndexingOperationJob.requested_at >= cutoff,
                    ),
                )
            )
        ).scalars()
    )

    identified = skipped_fresh_jobs = exceptions = 0
    for asset, version in rows:
        if asset.id in fresh_job_asset_ids:
            skipped_fresh_jobs += 1
            continue
        try:
            async with session.begin_nested():
                # Re-check after the locking query so repeated scans remain idempotent.
                if not should_mark_submission_interrupted(version, now=observed_at):
                    continue
                version.index_status = "index_failed"
                version.index_error_code = SUBMISSION_INTERRUPTED_ERROR_CODE
                version.index_error_message = error_catalog.user_message(
                    SUBMISSION_INTERRUPTED_ERROR_CODE
                )
                await audit_service.record_system_event(
                    session,
                    log_type=AuditLogType.operation,
                    action=AuditAction.knowledge_index_submission_interrupted_detected.value,
                    trace_id=trace_id or "",
                    target_type="knowledge_asset_version",
                    target_id=version.id,
                    before={"index_status": "indexing"},
                    after={
                        "index_status": "index_failed",
                        "reason_code": SUBMISSION_INTERRUPTED_ERROR_CODE,
                    },
                    extra={"count": 1, "scope": asset.scope},
                )
            identified += 1
        except Exception:
            exceptions += 1

    await session.commit()
    result = {
        "scanned": scanned,
        "identified": identified,
        "skipped_fresh_jobs": skipped_fresh_jobs,
        "exceptions": exceptions,
    }
    _logger.info("index_submission_interruption_scan", extra=result)
    return result
