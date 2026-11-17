"""Authorized notification projections shared by the legacy API and grouped inbox.

This module cannot create domain notifications; producers still use the Outbox.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import BusinessNotification
from app.schemas.enums import CompanyRole
from app.schemas.notification import BusinessNotificationOut
from app.schemas.permission import CallerContext
from app.services.notification_targets import VisibleNotificationTarget, preload_targets
from app.services.notification_targets import resolve as resolve_notification_target
from app.services.storage import LocalFileStorage


def _is_ops_viewer(caller: CallerContext) -> bool:
    """运维面板可见性（与 ops.py `_require_ops_viewer` 同口径）。"""
    return CompanyRole.admin.value in caller.active_company_roles or caller.can_discover_l5


def _task_projection(
    row: BusinessNotification, status: str, action_required: bool
) -> tuple[str, str, str]:
    if action_required:
        group = "my_tasks"
        label = "前往处理"
    elif status in {"submitted", "processing"}:
        group = "running_jobs"
        label = "查看进度"
    elif status in {"failed", "partial"}:
        group = "attention_items"
        label = "查看结果"
    else:
        group = "recent_completed"
        label = "查看记录"
    return status, group, label


def _out(
    row: BusinessNotification,
    visible: VisibleNotificationTarget,
    project_name: str | None = None,
) -> BusinessNotificationOut:
    task_status, task_group, next_action_label = _task_projection(
        row, visible.status, visible.action_required
    )
    return BusinessNotificationOut(
        id=row.id,
        event_type=row.event_type,
        category=row.category,
        title=row.title,
        summary=row.summary,
        created_at=row.created_at,
        is_read=row.read_at is not None,
        read_at=row.read_at,
        project_name=project_name,
        object_name=row.title,
        task_status=task_status,
        task_group=task_group,
        action_required=visible.action_required,
        next_action_label=visible.next_action_label or next_action_label,
        failure_reason=(
            visible.failure_reason
            or (row.summary if task_status in {"failed", "partial"} else None)
        ),
        recovery_suggestion=(
            visible.recovery_suggestion
            or (
                "打开目标查看安全失败摘要并按提示恢复。"
                if task_status in {"failed", "partial"}
                else None
            )
        ),
        target=visible.target,
    )


async def _visible_chunks(
    session: AsyncSession,
    caller: CallerContext,
    *,
    category: str | None = None,
    unread_only: bool = False,
    storage: LocalFileStorage | None = None,
    include_hidden: bool = False,
    snapshot_at=None,
    inbox_view: str | None = None,
):
    if not caller.is_business_user and not _is_ops_viewer(caller):
        return
    stmt = select(BusinessNotification).where(
        BusinessNotification.recipient_user_id == caller.user_id,
        BusinessNotification.target_kind != "notification_digest",
        BusinessNotification.in_app_enabled.is_(True),
    )
    if not include_hidden:
        stmt = stmt.where(
            BusinessNotification.deleted_at.is_(None), BusinessNotification.archived_at.is_(None)
        )
    if snapshot_at is not None:
        stmt = stmt.where(BusinessNotification.created_at <= snapshot_at)
    if inbox_view in {"inbox", "unread"}:
        stmt = stmt.where(
            BusinessNotification.deleted_at.is_(None), BusinessNotification.archived_at.is_(None)
        )
    elif inbox_view == "archived":
        stmt = stmt.where(BusinessNotification.deleted_at.is_(None))
    elif inbox_view == "trash":
        stmt = stmt.where(
            BusinessNotification.deleted_at.is_not(None)
            | BusinessNotification.archived_at.is_(None)
        )
    if category:
        stmt = stmt.where(BusinessNotification.category == category)
    if unread_only:
        stmt = stmt.where(BusinessNotification.read_at.is_(None))
    cursor = None
    while True:
        page_stmt = stmt
        if cursor is not None:
            created, row_id = cursor
            page_stmt = page_stmt.where(
                (BusinessNotification.created_at < created)
                | (
                    (BusinessNotification.created_at == created)
                    & (BusinessNotification.id < row_id)
                )
            )
        rows = list(
            (
                await session.scalars(
                    page_stmt.order_by(
                        BusinessNotification.created_at.desc(), BusinessNotification.id.desc()
                    ).limit(200)
                )
            ).all()
        )
        if not rows:
            return
        facts = await preload_targets(session, rows)
        visible = []
        for row in rows:
            target = await resolve_notification_target(
                session, caller, row, storage=storage, facts=facts
            )
            if target is not None:
                visible.append((row, target))
        yield visible
        cursor = (rows[-1].created_at, rows[-1].id)
        if len(rows) < 200:
            return
