"""Persistent, safety-bounded indexing operations health sampling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.utils import utc_now
from app.models.indexing_job import IndexingOperationJob, IndexingOpsSnapshot, OpsRuntimeHeartbeat
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.weknora import WeknoraKbMapping
from app.schemas.enums import AssetStatus
from app.schemas.indexing_ops import (
    IndexingHealthResponse,
    IndexingHealthTrendPoint,
    QueueHealth,
    RuntimeHealth,
)
from app.services.index_recovery import INTERRUPTED_ERROR_CODE, SUBMISSION_INTERRUPTED_ERROR_CODE

HEARTBEAT_STALE_SECONDS = 180
QUEUE_DEGRADED_SECONDS = 300
MIN_TREND_BUCKETS = 2
MAX_WINDOW_HOURS = 168
_COMPONENTS = {"worker", "beat"}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _hour_start(value: datetime) -> datetime:
    value = _aware(value).astimezone(timezone.utc)
    return value.replace(minute=0, second=0, microsecond=0)


async def indexing_counts(session: AsyncSession, *, now: datetime | None = None) -> dict[str, int]:
    active = (
        KnowledgeAssetVersion.version_status == "active",
        KnowledgeAsset.asset_status != AssetStatus.deleted.value,
    )

    async def count(stmt) -> int:
        return int((await session.execute(stmt)).scalar() or 0)

    def versions(*conditions):
        return (
            select(func.count())
            .select_from(KnowledgeAssetVersion)
            .join(KnowledgeAsset, KnowledgeAssetVersion.asset_id == KnowledgeAsset.id)
            .where(*active, *conditions)
        )

    return {
        "index_failed": await count(versions(KnowledgeAssetVersion.index_status == "index_failed")),
        "indexing": await count(versions(KnowledgeAssetVersion.index_status == "indexing")),
        "submission_processing": await count(
            versions(
                KnowledgeAssetVersion.index_status == "indexing",
                or_(
                    KnowledgeAssetVersion.weknora_doc_id.is_(None),
                    KnowledgeAssetVersion.weknora_parse_status.is_(None),
                ),
            )
        ),
        "parse_in_progress": await count(
            versions(
                KnowledgeAssetVersion.weknora_doc_id.is_not(None),
                KnowledgeAssetVersion.weknora_parse_status.in_(("pending", "processing")),
            )
        ),
        "not_indexed": await count(versions(KnowledgeAssetVersion.index_status == "not_indexed")),
        "skipped": await count(versions(KnowledgeAssetVersion.index_status == "skipped")),
        "parse_pending": await count(
            versions(KnowledgeAssetVersion.weknora_parse_status == "pending")
        ),
        "parse_processing": await count(
            versions(KnowledgeAssetVersion.weknora_parse_status == "processing")
        ),
        "parse_stalled": await count(
            versions(
                KnowledgeAssetVersion.index_status == "index_failed",
                KnowledgeAssetVersion.index_error_code == INTERRUPTED_ERROR_CODE,
            )
        ),
        "submission_interrupted": await count(
            versions(
                KnowledgeAssetVersion.index_status == "index_failed",
                KnowledgeAssetVersion.index_error_code == SUBMISSION_INTERRUPTED_ERROR_CODE,
            )
        ),
        "parse_failed": await count(
            versions(KnowledgeAssetVersion.weknora_parse_status == "failed")
        ),
        "kb_init_failed": await count(
            select(func.count())
            .select_from(WeknoraKbMapping)
            .where(WeknoraKbMapping.status == "init_failed")
        ),
    }


async def queue_metrics(
    session: AsyncSession, *, now: datetime | None = None
) -> tuple[int, int | None]:
    now = _aware(now or utc_now())
    queued_count, oldest = (
        await session.execute(
            select(func.count(), func.min(IndexingOperationJob.requested_at)).where(
                IndexingOperationJob.status == "queued"
            )
        )
    ).one()
    oldest_seconds = None
    if oldest is not None:
        oldest_seconds = max(0, int((now - _aware(oldest)).total_seconds()))
    return int(queued_count or 0), oldest_seconds


async def capture_snapshot(
    session: AsyncSession, *, observed_at: datetime | None = None
) -> IndexingOpsSnapshot:
    """Upsert the current UTC hour. Repeated beat delivery is idempotent."""
    now = _aware(observed_at or utc_now())
    bucket = _hour_start(now)
    end = bucket + timedelta(hours=1)
    counts = await indexing_counts(session)
    queued_jobs, oldest_queued_seconds = await queue_metrics(session, now=now)
    completed_jobs = int(
        (
            await session.execute(
                select(func.count()).where(
                    IndexingOperationJob.finished_at >= bucket,
                    IndexingOperationJob.finished_at < end,
                    IndexingOperationJob.status == "completed",
                )
            )
        ).scalar()
        or 0
    )
    failed_jobs = int(
        (
            await session.execute(
                select(func.count()).where(
                    IndexingOperationJob.finished_at >= bucket,
                    IndexingOperationJob.finished_at < end,
                    IndexingOperationJob.status.in_(("failed", "completed_with_errors")),
                )
            )
        ).scalar()
        or 0
    )
    snapshot = (
        await session.execute(
            select(IndexingOpsSnapshot).where(IndexingOpsSnapshot.bucket_started_at == bucket)
        )
    ).scalar_one_or_none()
    if snapshot is None:
        snapshot = IndexingOpsSnapshot(bucket_started_at=bucket)
        session.add(snapshot)
    for field, value in counts.items():
        setattr(snapshot, field, value)
    snapshot.completed_jobs = completed_jobs
    snapshot.failed_jobs = failed_jobs
    snapshot.queued_jobs = queued_jobs
    snapshot.oldest_queued_seconds = oldest_queued_seconds
    await session.commit()
    await session.refresh(snapshot)
    return snapshot


async def record_heartbeat(
    session: AsyncSession, component: str, *, observed_at: datetime | None = None
) -> None:
    if component not in _COMPONENTS:
        raise ValueError("unsupported heartbeat component")
    now = _aware(observed_at or utc_now())
    heartbeat = await session.get(OpsRuntimeHeartbeat, component)
    if heartbeat is None:
        session.add(OpsRuntimeHeartbeat(component=component, last_seen_at=now))
    else:
        heartbeat.last_seen_at = now
    await session.commit()


def _runtime_health(
    component: str,
    heartbeat: OpsRuntimeHeartbeat | None,
    *,
    now: datetime,
    eager: bool,
) -> RuntimeHealth:
    if eager:
        return RuntimeHealth(
            status="unknown",
            last_heartbeat_at=None,
            message="本地同步模式不代表独立运行进程在线。",
        )
    if heartbeat is None:
        return RuntimeHealth(
            status="unknown", last_heartbeat_at=None, message="尚未收到真实运行心跳。"
        )
    seen = _aware(heartbeat.last_seen_at)
    if (now - seen).total_seconds() > HEARTBEAT_STALE_SECONDS:
        return RuntimeHealth(
            status="stale", last_heartbeat_at=seen, message="最近心跳已过期，请检查运行服务。"
        )
    label = "任务执行进程" if component == "worker" else "定时调度进程"
    return RuntimeHealth(status="healthy", last_heartbeat_at=seen, message=f"{label}心跳正常。")


async def get_health(
    session: AsyncSession, *, window_hours: int = 24, now: datetime | None = None
) -> IndexingHealthResponse:
    now = _aware(now or utc_now())
    hours = max(1, min(int(window_hours), MAX_WINDOW_HOURS))
    start = now - timedelta(hours=hours)
    snapshots = list(
        (
            await session.execute(
                select(IndexingOpsSnapshot)
                .where(IndexingOpsSnapshot.bucket_started_at >= start)
                .order_by(IndexingOpsSnapshot.bucket_started_at.asc())
            )
        )
        .scalars()
        .all()
    )
    heartbeats = {
        item.component: item
        for item in (
            await session.execute(
                select(OpsRuntimeHeartbeat).where(
                    OpsRuntimeHeartbeat.component.in_(("worker", "beat"))
                )
            )
        )
        .scalars()
        .all()
    }
    queued_count, oldest_queued_seconds = await queue_metrics(session, now=now)
    queue_status = (
        "degraded"
        if oldest_queued_seconds is not None and oldest_queued_seconds > QUEUE_DEGRADED_SECONDS
        else "healthy"
    )
    queue_message = (
        "存在等待时间较长的索引作业。" if queue_status == "degraded" else "索引作业队列运行正常。"
    )
    insufficient = len(snapshots) < MIN_TREND_BUCKETS
    return IndexingHealthResponse(
        generated_at=now,
        window_hours=hours,
        insufficient_data=insufficient,
        message="正在积累运维数据" if insufficient else "最近运行趋势已更新",
        queue=QueueHealth(
            status=queue_status,
            queued_count=queued_count,
            oldest_queued_seconds=oldest_queued_seconds,
            message=queue_message,
        ),
        worker=_runtime_health(
            "worker",
            heartbeats.get("worker"),
            now=now,
            eager=get_settings().celery_task_always_eager,
        ),
        beat=_runtime_health(
            "beat",
            heartbeats.get("beat"),
            now=now,
            eager=get_settings().celery_task_always_eager,
        ),
        trend_points=[
            IndexingHealthTrendPoint(
                observed_at=item.bucket_started_at,
                index_failed=item.index_failed,
                indexing=item.indexing,
                not_indexed=item.not_indexed,
                skipped=item.skipped,
                parse_pending=getattr(item, "parse_pending", 0),
                parse_processing=getattr(item, "parse_processing", 0),
                parse_failed=getattr(item, "parse_failed", 0),
                parse_stalled=getattr(item, "parse_stalled", 0),
                submission_interrupted=getattr(item, "submission_interrupted", 0),
                kb_init_failed=item.kb_init_failed,
                completed_jobs=item.completed_jobs,
                failed_jobs=item.failed_jobs,
                queued_jobs=item.queued_jobs,
                oldest_queued_seconds=item.oldest_queued_seconds,
            )
            for item in snapshots
        ],
    )
