"""Notification projections driven only by persisted business events."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.identity import User, UserCompanyRole
from app.models.indexing_job import IndexingOperationJob
from app.models.ingest import IngestTask
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.lifecycle import AssetLifecycleEvent
from app.models.original_access import OriginalAccessRequest
from app.models.outbox import DomainEventOutbox
from app.models.review import ReviewTask
from app.schemas.enums import CompanyRole
from app.services import alert as alert_service
from app.services import domain_events, notifications
from app.services.wecom_notification import default_notification_channel


async def _consume_local_notification(
    session: AsyncSession,
    *,
    notice_type: str,
    recipient_id: uuid.UUID,
    asset_id: uuid.UUID,
    audit_event_id: uuid.UUID,
) -> None:
    """Build safe local-notification text from persisted domain facts."""
    asset = await session.get(KnowledgeAsset, asset_id)
    audit_event = await session.get(AuditEvent, audit_event_id)
    if asset is None or audit_event is None:
        raise LookupError("local_notification_source_missing")
    extra = audit_event.extra or {}

    if notice_type in {"lifecycle_archived", "lifecycle_reenabled"}:
        lifecycle_event_id = extra.get("lifecycle_event_id")
        if not lifecycle_event_id:
            raise ValueError("local_notification_lifecycle_event_missing")
        lifecycle_event = await session.get(AssetLifecycleEvent, uuid.UUID(str(lifecycle_event_id)))
        if lifecycle_event is None:
            raise LookupError("local_notification_lifecycle_event_missing")
        if notice_type == "lifecycle_archived":
            title = f"知识资产已归档：{asset.title}"
            content = (
                f"资产「{asset.title}」（{asset.scope}/{asset.confidentiality_level}）"
                f"已由 {lifecycle_event.old_status} 归档。原因：{lifecycle_event.reason}。"
            )
        else:
            title = f"知识资产已重新启用：{asset.title}"
            content = (
                f"资产「{asset.title}」已重新启用为 {lifecycle_event.new_status}（曾归档，"
                f"归档记录保留用于追溯）。原因：{lifecycle_event.reason}。"
            )
    elif notice_type in {"lifecycle_archive_warning", "lifecycle_archive_candidate"}:
        inactive_days = int(extra.get("inactive_days", 0))
        label = "候选" if notice_type == "lifecycle_archive_candidate" else "预警"
        title = f"归档{label}：{asset.title}"
        content = (
            f"资产「{asset.title}」（{asset.scope}）长期未调用（{inactive_days} 天），"
            "请评估是否归档。"
        )
    elif notice_type == "reuse_upgrade":
        project_count = int(extra.get("reuse_project_count", 0))
        call_count = int(extra.get("reuse_call_count", 0))
        title = f"升格推荐：{asset.title}"
        content = (
            f"项目资产「{asset.title}」被 {project_count} 个项目、共 {call_count} 次复用，"
            "建议评估升格为公司知识资产（需总经理 / 咨询总监审核，系统不自动升格）。"
        )
    else:
        raise ValueError("unsupported_local_notification_type")

    await alert_service.record_local_notification(
        session,
        recipient_user_id=recipient_id,
        title=title,
        content=content,
        audit_event_id=audit_event_id,
        channel=default_notification_channel(),
    )


async def _consume_ops_admin_alert(
    session: AsyncSession,
    *,
    signal: str,
    audit_event_id: uuid.UUID,
    alert_rule_id: uuid.UUID,
) -> None:
    audit_event = await session.get(AuditEvent, audit_event_id)
    if audit_event is None:
        raise LookupError("ops_alert_audit_event_missing")
    extra = audit_event.extra or {}
    count = int(extra.get("count", 0))
    threshold = int(extra.get("threshold", 0))
    if signal == "index_failed_backlog":
        title = "运维告警：索引失败堆积"
        codes = extra.get("error_codes") or {}
        codes_text = "、".join(f"{code}×{number}" for code, number in codes.items()) or "unknown"
        content = (
            f"活跃版本中索引失败 {count} 个，达到阈值 {threshold}。"
            f"失败码分布：{codes_text}。请在运维面板重试索引或排查底座配置。"
        )
    elif signal == "parse_stalled_backlog":
        title = "运维告警：解析停滞堆积"
        content = (
            f"有 {count} 个活跃版本经连续对账确认索引处理中断，达到阈值 {threshold}。"
            "请在索引恢复控制台确认底座可用后发起恢复。"
        )
    elif signal == "login_guard_backlog":
        title = "运维告警：登录安全异常"
        window = int(extra.get("window_minutes", 0))
        content = (
            f"最近 {window} 分钟内发生登录锁定/限流事件 {count} 起，"
            f"达到阈值 {threshold}。请关注登录安全运维面板，必要时收紧风控参数。"
        )
    else:
        raise ValueError("unsupported_ops_signal")
    admin_ids = list(
        (
            await session.execute(
                select(User.id)
                .join(UserCompanyRole, UserCompanyRole.user_id == User.id)
                .where(
                    User.status == "active",
                    UserCompanyRole.company_role == CompanyRole.admin.value,
                    UserCompanyRole.status == "active",
                )
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    channel = default_notification_channel()
    for admin_id in admin_ids:
        await alert_service.record_local_notification(
            session,
            recipient_user_id=admin_id,
            title=title,
            content=content,
            audit_event_id=audit_event_id,
            channel=channel,
            alert_rule_id=alert_rule_id,
        )


async def consume_notification_event(session: AsyncSession, event: DomainEventOutbox) -> None:
    """Create recipient-scoped hints; never advances another domain's state.

    Every event advertised in ``NOTIFICATION_EVENT_TYPES`` has an explicit
    branch. A missing aggregate or unknown type fails delivery so the outbox
    remains observable and retryable instead of silently completing the row.
    """
    if event.event_type == domain_events.REVIEW_ACTION_REQUIRED:
        review_task = await session.get(ReviewTask, event.aggregate_id)
        if review_task is None:
            raise LookupError("review_event_aggregate_missing")
        await notifications.notify_review_pending(session, review_task)
    elif event.event_type == domain_events.REVIEW_DECIDED:
        review_task = await session.get(ReviewTask, event.aggregate_id)
        if review_task is None:
            raise LookupError("review_event_aggregate_missing")
        await notifications.notify_review_decided(
            session, review_task, dedup_key=event.idempotency_key
        )
    elif event.event_type == domain_events.ORIGINAL_ACCESS_REQUESTED:
        request = await session.get(OriginalAccessRequest, event.aggregate_id)
        if request is None:
            raise LookupError("original_access_event_aggregate_missing")
        await notifications.notify_original_access_pending(session, request)
    elif event.event_type == domain_events.ORIGINAL_ACCESS_DECIDED:
        request = await session.get(OriginalAccessRequest, event.aggregate_id)
        if request is None:
            raise LookupError("original_access_event_aggregate_missing")
        await notifications.notify_original_access_decided(
            session, request, dedup_key=event.idempotency_key
        )
    elif event.event_type == domain_events.INGEST_FAILED:
        ingest_task = await session.get(IngestTask, event.aggregate_id)
        if ingest_task is None:
            raise LookupError("ingest_event_aggregate_missing")
        await notifications.notify_ingest_failed(session, ingest_task)
    elif event.event_type == domain_events.INGEST_CONFIRMED:
        ingest_task = await session.get(IngestTask, event.aggregate_id)
        if ingest_task is None:
            raise LookupError("ingest_event_aggregate_missing")
        await notifications.notify_ingest_confirmed(
            session, ingest_task, dedup_key=event.idempotency_key
        )
    elif event.event_type == domain_events.INDEX_STATUS_CHANGED:
        version = await session.get(KnowledgeAssetVersion, event.aggregate_id)
        if version is None:
            raise LookupError("index_event_aggregate_missing")
        await notifications.notify_index_status_changed(
            session,
            version,
            status=event.payload.get("status"),
            dedup_key=event.idempotency_key,
        )
    elif event.event_type == domain_events.OPERATION_JOB_FINISHED:
        job = await session.get(IndexingOperationJob, event.aggregate_id)
        if job is None:
            raise LookupError("operation_job_event_aggregate_missing")
        await notifications.notify_operation_job_finished(session, job)
    elif event.event_type == domain_events.OPS_SIGNAL_RAISED:
        signal = event.payload.get("signal")
        count = event.payload.get("count")
        audit_event_id = event.payload.get("audit_event_id")
        alert_rule_id = event.payload.get("alert_rule_id")
        if signal is None or count is None or audit_event_id is None or alert_rule_id is None:
            raise ValueError("ops_signal_event_payload_invalid")
        await _consume_ops_admin_alert(
            session,
            signal=signal,
            audit_event_id=uuid.UUID(audit_event_id),
            alert_rule_id=uuid.UUID(alert_rule_id),
        )
        await notifications.notify_ops_signal(session, signal=signal, count=int(count))
    elif event.event_type == domain_events.LOCAL_NOTIFICATION_REQUESTED:
        notice_type = event.payload.get("notice_type")
        recipient_id = event.payload.get("recipient_id")
        asset_id = event.payload.get("asset_id")
        audit_event_id = event.payload.get("audit_event_id")
        if not all((notice_type, recipient_id, asset_id, audit_event_id)):
            raise ValueError("local_notification_event_payload_invalid")
        await _consume_local_notification(
            session,
            notice_type=str(notice_type),
            recipient_id=uuid.UUID(str(recipient_id)),
            asset_id=uuid.UUID(str(asset_id)),
            audit_event_id=uuid.UUID(str(audit_event_id)),
        )
    else:
        raise ValueError("unsupported_notification_event_type")


NOTIFICATION_EVENT_TYPES = frozenset(
    {
        domain_events.REVIEW_ACTION_REQUIRED,
        domain_events.REVIEW_DECIDED,
        domain_events.INGEST_CONFIRMED,
        domain_events.INGEST_FAILED,
        domain_events.ORIGINAL_ACCESS_REQUESTED,
        domain_events.ORIGINAL_ACCESS_DECIDED,
        domain_events.INDEX_STATUS_CHANGED,
        domain_events.OPERATION_JOB_FINISHED,
        domain_events.OPS_SIGNAL_RAISED,
        domain_events.LOCAL_NOTIFICATION_REQUESTED,
    }
)
