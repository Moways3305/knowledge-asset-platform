"""Recipient-scoped business notification inbox and delivery.

Notifications are hints, never authorization. Every read and external delivery resolves the
target through its owning service again. Rows that have become stale or unauthorized are
silently omitted so they cannot reveal that a project or asset exists.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.utils import utc_now
from app.models.identity import ProjectMember, User, UserCompanyRole
from app.models.ingest import IngestTask
from app.models.notification import BusinessNotification
from app.models.original_access import OriginalAccessRequest
from app.models.review import ReviewTask
from app.schemas.enums import (
    AccessRequestStatus,
    AuditAction,
    AuditLogType,
    CompanyRole,
    MemberStatus,
    NotificationChannel,
    NotificationStatus,
    ProjectRole,
    ReviewTaskStatus,
    ReviewType,
    RoleStatus,
)
from app.schemas.notification import (
    BusinessNotificationListResponse,
    BusinessNotificationOut,
    MarkReadBatchResponse,
    NotificationTarget,
    UnreadCountResponse,
)
from app.schemas.permission import CallerContext
from app.services import audit as audit_service
from app.services.permission import build_caller_context
from app.services.wecom_client import WeComError

MAX_DELIVERY_ATTEMPTS = 3
_ACTIONABLE_REVIEW_STATUSES = {
    ReviewTaskStatus.pending_reviewer.value,
    ReviewTaskStatus.approval_failed.value,
}
_EVENT_COPY = {
    "review.project_pending": ("review", "项目事项待确认", "有一项项目事项等待你确认。"),
    "review.company_confirmation_pending": (
        "review",
        "公司资产待确认",
        "有一项公司资产确认等待处理。",
    ),
    "original_access.pending": (
        "original_access",
        "原文访问申请待审批",
        "有一项原文访问申请等待处理。",
    ),
    "ingest.failed": ("ingest", "入库处理未完成", "你提交的一项入库任务需要处理。"),
    "ops.parse_stalled": (
        "ops",
        "运维告警：解析停滞",
        "有文档解析长期停留在处理中，请到索引维护查看并处理。",
    ),
    "ops.index_failed": (
        "ops",
        "运维告警：索引失败堆积",
        "存在索引失败存量，请到索引维护重试索引。",
    ),
}
_TARGET_ROUTES = {
    "review": "reviews",
    "original_access_request": "original_access",
    "ingest_task": "upload",
    "ops_index": "admin_ingest",
}

# 运维告警信号 → 业务通知事件类型（仅治理角色可见的业务信号，不包含登录风控）。
_OPS_SIGNAL_EVENTS = {
    "index_failed_backlog": "ops.index_failed",
    "parse_stalled_backlog": "ops.parse_stalled",
}


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"denied_reason": "notification_not_found", "message": "通知不存在或不可见"},
    )


async def _active_project_user_ids(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    roles: set[str] | None = None,
) -> list[uuid.UUID]:
    stmt = (
        select(ProjectMember.user_id)
        .join(User, User.id == ProjectMember.user_id)
        .where(
            ProjectMember.project_id == project_id,
            ProjectMember.status == MemberStatus.active.value,
            User.status == "active",
        )
    )
    if roles:
        stmt = stmt.where(ProjectMember.project_role.in_(roles))
    return list((await session.execute(stmt)).scalars().all())


async def _active_company_user_ids(session: AsyncSession, roles: set[str]) -> list[uuid.UUID]:
    return list(
        (
            await session.execute(
                select(UserCompanyRole.user_id)
                .join(User, User.id == UserCompanyRole.user_id)
                .where(
                    UserCompanyRole.company_role.in_(roles),
                    UserCompanyRole.status == RoleStatus.active.value,
                    User.status == "active",
                )
                .distinct()
            )
        )
        .scalars()
        .all()
    )


async def _record(
    session: AsyncSession,
    *,
    recipients: Iterable[uuid.UUID],
    event_type: str,
    target_kind: str,
    target_id: uuid.UUID,
    project_id: uuid.UUID | None,
    dedup_key: str | None = None,
) -> None:
    """Add deduplicated server-authored notifications to the caller's transaction."""
    if event_type not in _EVENT_COPY or target_kind not in _TARGET_ROUTES:
        raise ValueError("unsupported business notification event")
    category, title, summary = _EVENT_COPY[event_type]
    from app.services.wecom_notification import default_notification_channel

    channel = default_notification_channel()
    effective_dedup_key = dedup_key or f"{event_type}:{target_id}"
    recipient_ids = set(recipients)
    if not recipient_ids:
        return
    existing = set(
        (
            await session.execute(
                select(BusinessNotification.recipient_user_id).where(
                    BusinessNotification.recipient_user_id.in_(recipient_ids),
                    BusinessNotification.dedup_key == effective_dedup_key,
                )
            )
        )
        .scalars()
        .all()
    )
    for recipient_id in recipient_ids - existing:
        session.add(
            BusinessNotification(
                recipient_user_id=recipient_id,
                event_type=event_type,
                category=category,
                title=title,
                summary=summary,
                target_kind=target_kind,
                target_id=target_id,
                project_id=project_id,
                dedup_key=effective_dedup_key,
                channel=channel,
                delivery_status=NotificationStatus.pending.value,
            )
        )


async def notify_ops_signal(
    session: AsyncSession,
    *,
    signal: str,
    count: int,
) -> None:
    """运维告警信号 → 治理角色业务通知（铃铛）。

    与 admin 运维通知（notification_records）并行：管理员看运维通知记录，治理角色在
    个人铃铛收到业务提示。去重按「信号 + 小时桶」，由 ops_alerts 的冷却期控制发送频率。
    通知读取时经 `_validated_target` 校验治理身份，不构成业务内容旁路。
    """
    event_type = _OPS_SIGNAL_EVENTS.get(signal)
    if event_type is None:
        return
    recipients = await _active_company_user_ids(
        session, {CompanyRole.boss.value, CompanyRole.consulting_director.value}
    )
    if not recipients:
        return
    target_id = uuid.uuid5(uuid.NAMESPACE_URL, f"kap:ops:{signal}")
    now = utc_now()
    dedup_key = f"{event_type}:{target_id}:{now.strftime('%Y%m%d%H')}"
    await _record(
        session,
        recipients=recipients,
        event_type=event_type,
        target_kind="ops_index",
        target_id=target_id,
        project_id=None,
        dedup_key=dedup_key,
    )


async def notify_review_pending(session: AsyncSession, task: ReviewTask) -> None:
    """Map a review fact to the least-privileged current recipient set."""
    if task.status not in _ACTIONABLE_REVIEW_STATUSES:
        return
    if task.review_type == ReviewType.project_to_company.value:
        recipients = await _active_company_user_ids(
            session, {CompanyRole.boss.value, CompanyRole.consulting_director.value}
        )
        event_type = "review.company_confirmation_pending"
    elif task.target_project_id is not None:
        # Project notifications never fan out from company roles. Even an assigned reviewer
        # must still be an active manager of this project at delivery/read time.
        active_managers = set(
            await _active_project_user_ids(
                session,
                task.target_project_id,
                roles={ProjectRole.project_manager.value},
            )
        )
        recipients = (
            [task.reviewer_user_id]
            if task.reviewer_user_id is not None and task.reviewer_user_id in active_managers
            else list(active_managers)
        )
        event_type = "review.project_pending"
    else:
        return
    await _record(
        session,
        recipients=recipients,
        event_type=event_type,
        target_kind="review",
        target_id=task.id,
        project_id=task.target_project_id,
    )


async def notify_original_access_pending(
    session: AsyncSession, request: OriginalAccessRequest
) -> None:
    if request.status != AccessRequestStatus.pending.value:
        return
    if request.project_id is not None:
        recipients = await _active_project_user_ids(
            session,
            request.project_id,
            roles={ProjectRole.project_manager.value, ProjectRole.coach.value},
        )
    else:
        recipients = await _active_company_user_ids(
            session, {CompanyRole.boss.value, CompanyRole.consulting_director.value}
        )
    await _record(
        session,
        recipients=recipients,
        event_type="original_access.pending",
        target_kind="original_access_request",
        target_id=request.id,
        project_id=request.project_id,
    )


async def notify_ingest_failed(session: AsyncSession, task: IngestTask) -> None:
    """Notify only the active submitter; project membership is mandatory when scoped."""
    if task.created_by is None or task.status != "failed":
        return
    recipients: list[uuid.UUID] = []
    user = await session.get(User, task.created_by)
    if user is not None and user.status == "active":
        if task.target_project_id is None:
            recipients = [user.id]
        else:
            active = await _active_project_user_ids(session, task.target_project_id)
            if user.id in active:
                recipients = [user.id]
    await _record(
        session,
        recipients=recipients,
        event_type="ingest.failed",
        target_kind="ingest_task",
        target_id=task.id,
        project_id=task.target_project_id,
    )


async def _validated_target(
    session: AsyncSession, caller: CallerContext, row: BusinessNotification
) -> NotificationTarget | None:
    if not caller.is_business_user or not caller.is_active:
        return None
    if row.project_id is not None and row.event_type != "review.company_confirmation_pending":
        if row.project_id not in caller.active_project_ids:
            return None
    try:
        if row.target_kind == "review":
            from app.services import review as review_service

            item = await review_service.get_review(session, caller, row.target_id)
            if not item.can_decide or item.status not in _ACTIONABLE_REVIEW_STATUSES:
                return None
        elif row.target_kind == "original_access_request":
            from app.services import original_access as original_access_service

            inbox = await original_access_service.list_requests(
                session, caller, box="inbox", status=AccessRequestStatus.pending.value
            )
            if not any(item.request_id == row.target_id for item in inbox.items):
                return None
        elif row.target_kind == "ingest_task":
            from app.services import ingest_status as ingest_status_service

            status = await ingest_status_service.get_task_status(session, caller, row.target_id)
            if getattr(status.status, "value", status.status) != "failed":
                return None
        elif row.target_kind == "ops_index":
            if not caller.can_discover_l5:
                return None
        else:
            return None
    except HTTPException:
        return None
    return NotificationTarget(route_key=_TARGET_ROUTES[row.target_kind], resource_id=row.target_id)


def _out(row: BusinessNotification, target: NotificationTarget) -> BusinessNotificationOut:
    return BusinessNotificationOut(
        id=row.id,
        event_type=row.event_type,
        category=row.category,
        title=row.title,
        summary=row.summary,
        created_at=row.created_at,
        is_read=row.read_at is not None,
        read_at=row.read_at,
        target=target,
    )


async def _visible_rows(
    session: AsyncSession,
    caller: CallerContext,
    *,
    category: str | None = None,
    unread_only: bool = False,
) -> list[tuple[BusinessNotification, NotificationTarget]]:
    if not caller.is_business_user:
        return []
    stmt = select(BusinessNotification).where(
        BusinessNotification.recipient_user_id == caller.user_id
    )
    if category:
        stmt = stmt.where(BusinessNotification.category == category)
    if unread_only:
        stmt = stmt.where(BusinessNotification.read_at.is_(None))
    rows = list(
        (
            await session.execute(
                stmt.order_by(
                    BusinessNotification.created_at.desc(), BusinessNotification.id.desc()
                )
            )
        )
        .scalars()
        .all()
    )
    visible: list[tuple[BusinessNotification, NotificationTarget]] = []
    for row in rows:
        target = await _validated_target(session, caller, row)
        if target is not None:
            visible.append((row, target))
    return visible


async def list_notifications(
    session: AsyncSession,
    caller: CallerContext,
    *,
    page: int,
    page_size: int,
    category: str | None,
    unread_only: bool,
) -> BusinessNotificationListResponse:
    visible = await _visible_rows(session, caller, category=category, unread_only=unread_only)
    start = (page - 1) * page_size
    selected = visible[start : start + page_size]
    return BusinessNotificationListResponse(
        items=[_out(row, target) for row, target in selected],
        total=len(visible),
        page=page,
        page_size=page_size,
    )


async def unread_count(session: AsyncSession, caller: CallerContext) -> UnreadCountResponse:
    visible = await _visible_rows(session, caller, unread_only=True)
    return UnreadCountResponse(unread_count=len(visible))


async def _owned_visible(
    session: AsyncSession, caller: CallerContext, notification_id: uuid.UUID
) -> tuple[BusinessNotification, NotificationTarget]:
    row = (
        await session.execute(
            select(BusinessNotification).where(
                BusinessNotification.id == notification_id,
                BusinessNotification.recipient_user_id == caller.user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise _not_found()
    target = await _validated_target(session, caller, row)
    if target is None:
        raise _not_found()
    return row, target


async def mark_read(
    session: AsyncSession,
    caller: CallerContext,
    notification_id: uuid.UUID,
    trace_id: str,
) -> BusinessNotificationOut:
    row, target = await _owned_visible(session, caller, notification_id)
    transitioned = False
    if row.read_at is None:
        read_at = utc_now()
        claim = await session.execute(
            update(BusinessNotification)
            .where(
                BusinessNotification.id == row.id,
                BusinessNotification.recipient_user_id == caller.user_id,
                BusinessNotification.read_at.is_(None),
            )
            .values(read_at=read_at)
            .execution_options(synchronize_session=False)
        )
        transitioned = getattr(claim, "rowcount", 0) == 1
    if transitioned:
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action="notification.read",
            trace_id=trace_id,
            target_type="business_notification",
            target_id=row.id,
            extra={"event_type": row.event_type, "category": row.category},
            project_id=row.project_id,
        )
    await session.commit()
    await session.refresh(row)
    return _out(row, target)


async def mark_read_batch(
    session: AsyncSession,
    caller: CallerContext,
    notification_ids: list[uuid.UUID],
    trace_id: str,
) -> MarkReadBatchResponse:
    unique_ids = list(dict.fromkeys(notification_ids))
    marked = already = 0
    for notification_id in unique_ids:
        try:
            row, _ = await _owned_visible(session, caller, notification_id)
        except HTTPException:
            continue
        if row.read_at is None:
            claim = await session.execute(
                update(BusinessNotification)
                .where(
                    BusinessNotification.id == row.id,
                    BusinessNotification.recipient_user_id == caller.user_id,
                    BusinessNotification.read_at.is_(None),
                )
                .values(read_at=utc_now())
                .execution_options(synchronize_session=False)
            )
            if getattr(claim, "rowcount", 0) == 1:
                marked += 1
            else:
                already += 1
        else:
            already += 1
    if marked:
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action="notification.batch_read",
            trace_id=trace_id,
            target_type="business_notification_batch",
            extra={"requested_count": len(unique_ids), "marked_count": marked},
        )
        await session.commit()
    return MarkReadBatchResponse(
        requested_count=len(unique_ids), marked_count=marked, already_read_count=already
    )


async def dispatch_pending(
    session: AsyncSession, *, sender, trace_id: str | None = None, limit: int = 100
) -> dict[str, int]:
    """Retry safe external delivery after revalidating the recipient and target."""
    rows = list(
        (
            await session.execute(
                select(BusinessNotification)
                .where(
                    BusinessNotification.channel == NotificationChannel.wecom.value,
                    or_(
                        BusinessNotification.delivery_status == NotificationStatus.pending.value,
                        (BusinessNotification.delivery_status == NotificationStatus.failed.value)
                        & (BusinessNotification.delivery_attempts < MAX_DELIVERY_ATTEMPTS),
                    ),
                )
                .order_by(BusinessNotification.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    sent = failed = expired = 0
    for row in rows:
        row.delivery_attempts += 1
        user = (
            await session.execute(
                select(User)
                .where(User.id == row.recipient_user_id)
                .options(
                    selectinload(User.company_roles),
                    selectinload(User.project_members).selectinload(ProjectMember.project),
                )
            )
        ).scalar_one_or_none()
        if user is None or user.status != "active":
            row.delivery_status = NotificationStatus.failed.value
            row.failure_code = "recipient_unavailable"
            failed += 1
            await _audit_delivery(session, row, failed=True, trace_id=trace_id)
            continue
        caller = build_caller_context(user)
        if await _validated_target(session, caller, row) is None:
            row.delivery_status = NotificationStatus.failed.value
            row.failure_code = "target_unavailable"
            row.delivery_attempts = MAX_DELIVERY_ATTEMPTS
            expired += 1
            await _audit_delivery(session, row, failed=True, trace_id=trace_id)
            continue
        try:
            if not user.wecom_user_id:
                raise WeComError("recipient_unavailable", "recipient unavailable")
            await sender.send(
                wecom_user_id=user.wecom_user_id,
                title=row.title,
                content=row.summary,
                trace_id=trace_id,
            )
        except WeComError as exc:
            row.delivery_status = NotificationStatus.failed.value
            row.failure_code = (
                exc.code
                if exc.code
                in {
                    "recipient_unavailable",
                    "wecom_network_error",
                    "wecom_token_failed",
                    "wecom_no_agent_id",
                }
                else "delivery_failed"
            )
            failed += 1
            delivery_failed = True
        else:
            row.delivery_status = NotificationStatus.sent.value
            row.failure_code = None
            row.delivered_at = utc_now()
            sent += 1
            delivery_failed = False
        await _audit_delivery(session, row, failed=delivery_failed, trace_id=trace_id)
    await session.commit()
    return {"processed": len(rows), "sent": sent, "failed": failed, "expired": expired}


async def _audit_delivery(
    session: AsyncSession,
    row: BusinessNotification,
    *,
    failed: bool,
    trace_id: str | None,
) -> None:
    await audit_service.record_system_event(
        session,
        log_type=AuditLogType.operation,
        action=(
            AuditAction.notification_business_delivery_failed.value
            if failed
            else AuditAction.notification_business_delivered.value
        ),
        trace_id=trace_id or "",
        target_type="business_notification",
        target_id=row.id,
        extra={
            "event_type": row.event_type,
            "category": row.category,
            "channel": row.channel,
            "delivery_attempts": row.delivery_attempts,
            "failure_code": row.failure_code,
        },
    )
