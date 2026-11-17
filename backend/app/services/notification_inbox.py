"""An inbox is personal presentation state, never the business task state.

Aggregation always follows target authorization. Bulk scope is pinned to the
server snapshot from the list, so new arrivals cannot be swallowed by cleanup.
"""

from collections import defaultdict
from datetime import timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select, update

from app.db.utils import utc_now
from app.models.identity import Project
from app.models.ingest import UploadSessionItem
from app.models.notification import BusinessNotification as N
from app.models.notification import NotificationPreference
from app.schemas.enums import AuditLogType
from app.schemas.notification_inbox import InboxGroup, InboxPreferences, InboxResponse
from app.services import audit, notification_reader


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


async def preferences(session, user_id):
    row = await session.get(NotificationPreference, user_id)
    return (
        InboxPreferences(categories=row.categories, auto_archive_days=row.auto_archive_days)
        if row
        else InboxPreferences()
    )


async def save_preferences(session, caller, body, trace_id):
    # Serialize creation and updates with the recipient row (also on PostgreSQL).
    from app.models.identity import User

    await session.scalar(select(User.id).where(User.id == caller.user_id).with_for_update())
    row = await session.get(NotificationPreference, caller.user_id)
    if row is None:
        row = NotificationPreference(user_id=caller.user_id)
        session.add(row)
    row.categories = {k: v.model_dump() for k, v in body.categories.items()}
    row.auto_archive_days = body.auto_archive_days
    await audit.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action="notification.preferences",
        trace_id=trace_id,
        target_type="notification_inbox",
        target_id=caller.user_id,
        extra={"auto_archive_days": body.auto_archive_days},
    )
    await session.commit()
    return body


async def group_keys(session, rows):
    task_ids = [row.target_id for row in rows if row.target_kind == "ingest_task"]
    batches = {}
    for start in range(0, len(task_ids), 200):
        batches.update(
            (
                await session.execute(
                    select(UploadSessionItem.ingest_task_id, UploadSessionItem.session_id).where(
                        UploadSessionItem.ingest_task_id.in_(task_ids[start : start + 200])
                    )
                )
            ).all()
        )
    return {
        row.id: (
            f"upload:{batches[row.target_id]}:{row.project_id or 'company'}"
            if row.target_id in batches and row.target_kind == "ingest_task"
            else f"{row.target_kind}:{row.target_id}:{row.project_id or 'company'}"
        )
        for row in rows
    }


def matches(row, filters):
    if filters.view == "trash":
        if row.deleted_at is None:
            return False
    elif row.deleted_at is not None:
        return False
    elif filters.view == "archived":
        if row.archived_at is None:
            return False
    elif row.archived_at is not None and not filters.include_archived:
        return False
    if filters.view == "unread" and row.read_at is not None:
        return False
    return not (
        (filters.category and row.category != filters.category)
        or (filters.project_id and row.project_id != filters.project_id)
        or (filters.before and aware(row.created_at) >= filters.before)
        or (filters.after and aware(row.created_at) < filters.after)
        or (filters.read_only and row.read_at is None)
    )


async def authorized_rows(session, caller, snapshot, storage=None, view=None):
    result = []
    async for chunk in notification_reader._visible_chunks(
        session, caller, storage=storage, include_hidden=True, snapshot_at=snapshot, inbox_view=view
    ):
        result.extend(chunk)
    return result


async def archive_old_read(session, caller, rows, prefs):
    if not prefs.auto_archive_days:
        return
    cutoff = utc_now() - timedelta(days=prefs.auto_archive_days)
    ids = [
        row.id
        for row, target in rows
        if row.read_at is not None
        and aware(row.read_at) < cutoff
        and not target.action_required
        and target.status in {"completed", "cancelled", "duplicate_skipped"}
        and row.archived_at is None
        and row.deleted_at is None
    ]
    for start in range(0, len(ids), 200):
        await session.execute(
            update(N)
            .where(
                N.id.in_(ids[start : start + 200]),
                N.recipient_user_id == caller.user_id,
                N.deleted_at.is_(None),
                N.archived_at.is_(None),
                N.read_at < cutoff,
            )
            .values(archived_at=utc_now())
            .execution_options(synchronize_session="fetch")
        )
    if ids:
        await session.commit()


async def inbox(session, caller, filters, page, page_size, storage=None, snapshot=None):
    snapshot = min(snapshot, utc_now()) if snapshot else utc_now()
    rows = await authorized_rows(
        session, caller, snapshot, storage, None if filters.include_archived else filters.view
    )
    await archive_old_read(session, caller, rows, await preferences(session, caller.user_id))
    keys = await group_keys(session, [row for row, _ in rows])
    selected = defaultdict(list)
    unread, unseen = set(), set()
    projects = {row.project_id for row, _ in rows if row.project_id}
    names = (
        dict(
            (
                await session.execute(
                    select(Project.id, Project.name).where(Project.id.in_(projects))
                )
            ).all()
        )
        if projects
        else {}
    )
    for row, target in rows:
        key = keys[row.id]
        if row.archived_at is None and row.deleted_at is None:
            if row.read_at is None:
                unread.add(key)
            if row.seen_at is None:
                unseen.add(key)
        if matches(row, filters):
            selected[key].append((row, target))
    groups = []
    for key, members in selected.items():
        row, target = members[0]  # Keyset traversal is newest first.
        # Batch counts count distinct live targets, not progress event volume.
        latest_targets = {}
        for member, state in members:
            latest_targets.setdefault((member.target_kind, member.target_id), state)
        groups.append(
            InboxGroup(
                id=key,
                latest=notification_reader._out(row, target, names.get(row.project_id)),
                event_count=len(members),
                unread_count=sum(member.read_at is None for member, _ in members),
                failed_count=sum(
                    state.status in {"failed", "partial", "rejected"}
                    for state in latest_targets.values()
                ),
                completed_count=sum(
                    state.status == "completed" for state in latest_targets.values()
                ),
                action_required=any(state.action_required for state in latest_targets.values()),
            )
        )
    return InboxResponse(
        items=groups[(page - 1) * page_size : page * page_size],
        total=len(groups),
        unread_count=len(unread),
        unseen_count=len(unseen),
        snapshot_at=snapshot,
        categories=sorted({row.category for row, _ in rows}),
        projects=[{"id": str(key), "name": value} for key, value in names.items()],
    )


async def details(session, caller, group_id, filters, snapshot, page, storage=None):
    rows = await authorized_rows(session, caller, min(snapshot, utc_now()), storage, filters.view)
    keys = await group_keys(session, [row for row, _ in rows])
    members = [
        (row, state) for row, state in rows if keys[row.id] == group_id and matches(row, filters)
    ]
    if not members:
        raise HTTPException(404, "通知已清理或当前无法访问")
    return {
        "items": [
            notification_reader._out(row, state)
            for row, state in members[(page - 1) * 20 : page * 20]
        ],
        "total": len(members),
    }


async def act(session, caller, body, trace_id):
    snapshot = min(body.snapshot_at, utc_now())
    # The recipient lock serializes personal mutations, without locking business targets.
    from app.models.identity import User

    await session.scalar(select(User.id).where(User.id == caller.user_id).with_for_update())
    query = select(N).where(
        N.recipient_user_id == caller.user_id,
        N.created_at <= snapshot,
        N.target_kind != "notification_digest",
        N.in_app_enabled.is_(True),
    )
    filters = body.filters
    if filters.view == "trash":
        query = query.where(N.deleted_at.is_not(None))
    else:
        query = query.where(N.deleted_at.is_(None))
        if filters.view == "archived":
            query = query.where(N.archived_at.is_not(None))
        elif not filters.include_archived:
            query = query.where(N.archived_at.is_(None))
    if filters.category:
        query = query.where(N.category == filters.category)
    if filters.project_id:
        query = query.where(N.project_id == filters.project_id)
    if filters.before:
        query = query.where(N.created_at < filters.before)
    if filters.after:
        query = query.where(N.created_at >= filters.after)
    if filters.view == "unread":
        query = query.where(N.read_at.is_(None))
    if filters.read_only:
        query = query.where(N.read_at.is_not(None))
    if body.action == "seen":
        query = query.where(N.seen_at.is_(None))
    rows = list(await session.scalars(query))
    keys = await group_keys(session, rows) if not body.all_matching else {}
    selected_keys = set(body.group_ids)
    selected = [
        row
        for row in rows
        if matches(row, body.filters) and (body.all_matching or keys[row.id] in selected_keys)
    ]
    now, count = utc_now(), 0
    for row in selected:
        before = (row.read_at, row.seen_at, row.archived_at, row.deleted_at)
        if body.action == "read":
            row.read_at = row.read_at or now
            row.seen_at = row.seen_at or now
        elif body.action == "unread":
            row.read_at = None  # Manually unread is not a newly arrived event.
        elif body.action == "seen":
            row.seen_at = row.seen_at or now
        elif body.action == "archive":
            row.archived_at = row.archived_at or now
            row.seen_at = row.seen_at or now
        elif body.action == "delete":
            row.deleted_at = row.deleted_at or now
            row.seen_at = row.seen_at or now
        elif body.action == "restore":
            if row.deleted_at is None and row.archived_at is None:
                continue
            row.deleted_at = row.archived_at = None
            row.seen_at = row.seen_at or now
            if row.read_at is not None:
                row.read_at = now  # Give restored history a fresh retention window.
        count += before != (row.read_at, row.seen_at, row.archived_at, row.deleted_at)
    if count:
        await audit.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=f"notification.{body.action}_scope",
            trace_id=trace_id,
            target_type="notification_inbox",
            target_id=caller.user_id,
            extra={
                "affected_count": count,
                "snapshot_at": snapshot.isoformat(),
                "view": body.filters.view,
            },
        )
    await session.commit()
    return {"affected_count": count}
