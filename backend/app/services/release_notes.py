"""Published notes are immutable. CAS revisions protect concurrent draft editors."""

import uuid
from typing import Literal

from fastapi import HTTPException
from sqlalchemy import exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.utils import utc_now
from app.models.release_note import ReleaseNote, ReleaseNoteRead
from app.schemas.enums import AuditLogType
from app.schemas.permission import CallerContext
from app.schemas.release_note import (
    ReleaseDraft,
    ReleaseList,
    ReleaseOut,
    ReleaseStatus,
    ReleaseUpdate,
)
from app.services.audit import record_event


def _error(status_code: int, message: str) -> HTTPException:
    # The first-party HTTP client reads safe detail.message, not raw string detail.
    return HTTPException(status_code, detail={"message": message})


def require_reader(caller: CallerContext) -> None:
    if not caller.is_active:
        raise _error(403, "当前账号不可查看版本日志")


def require_admin(caller: CallerContext) -> None:
    require_reader(caller)
    if caller.active_company_role != "admin":
        raise _error(403, "仅系统管理员可管理版本日志")


def unread(caller: CallerContext):
    return (
        ReleaseNote.published_at.is_not(None),
        ReleaseNote.notify_users.is_(True),
        ~exists().where(
            ReleaseNoteRead.release_id == ReleaseNote.id,
            ReleaseNoteRead.user_id == caller.user_id,
        ),
    )


async def status(session: AsyncSession, caller: CallerContext) -> ReleaseStatus:
    require_reader(caller)
    count = await session.scalar(
        select(func.count()).select_from(ReleaseNote).where(*unread(caller))
    )
    return ReleaseStatus(running_version=get_settings().app_version, unread_count=count or 0)


async def list_notes(
    session: AsyncSession,
    caller: CallerContext,
    *,
    page: int,
    page_size: int,
    state: Literal["draft", "published"] = "published",
    admin: bool = False,
) -> ReleaseList:
    require_admin(caller) if admin else require_reader(caller)
    condition = (
        ReleaseNote.published_at.is_(None)
        if admin and state == "draft"
        else ReleaseNote.published_at.is_not(None)
    )
    total = await session.scalar(select(func.count()).select_from(ReleaseNote).where(condition))
    read_exists = exists().where(
        ReleaseNoteRead.release_id == ReleaseNote.id, ReleaseNoteRead.user_id == caller.user_id
    )
    rows = (
        await session.execute(
            select(ReleaseNote, read_exists)
            .where(condition)
            .order_by(
                ReleaseNote.published_at.desc(),
                ReleaseNote.updated_at.desc(),
                ReleaseNote.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    items = []
    for note, read in rows:
        out = ReleaseOut.model_validate(note)
        out.is_unread = note.published_at is not None and note.notify_users and not read
        items.append(out)
    return ReleaseList(items=items, total=total or 0, page=page, page_size=page_size)


async def commit_change(
    session: AsyncSession,
    caller: CallerContext,
    note: ReleaseNote,
    action: str,
    trace_id: str | None,
) -> ReleaseOut:
    await record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=f"release_note.{action}",
        trace_id=trace_id,
        target_type="release_note",
        target_id=note.id,
        after={
            "version": note.version,
            "revision": note.revision,
            "published": note.published_at is not None,
        },
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise _error(409, "该版本号已存在，请打开已有日志或使用其他版本号") from exc
    return ReleaseOut.model_validate(note)


async def create(
    session: AsyncSession, caller: CallerContext, body: ReleaseDraft, trace_id: str | None
) -> ReleaseOut:
    require_admin(caller)
    note = ReleaseNote(id=uuid.uuid4(), created_by=caller.user_id, **body.model_dump())
    session.add(note)
    # Flush before audit so generated timestamps/revision are available, handling duplicates safely.
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise _error(409, "该版本号已存在，请打开已有日志或使用其他版本号") from exc
    return await commit_change(session, caller, note, "created", trace_id)


async def edit(
    session: AsyncSession,
    caller: CallerContext,
    note_id: uuid.UUID,
    body: ReleaseUpdate,
    trace_id: str | None,
) -> ReleaseOut:
    require_admin(caller)
    try:
        changed = await session.scalar(
            update(ReleaseNote)
            .where(
                ReleaseNote.id == note_id,
                ReleaseNote.published_at.is_(None),
                ReleaseNote.revision == body.revision,
            )
            .values(
                **body.model_dump(exclude={"revision"}),
                revision=body.revision + 1,
                updated_at=utc_now(),
            )
            .returning(ReleaseNote.id)
        )
    except IntegrityError as exc:
        await session.rollback()
        raise _error(409, "该版本号已存在，请使用其他版本号") from exc
    if changed is None:
        raise _error(409, "日志已变更或已发布，请重新加载后再编辑")
    note = await session.get(ReleaseNote, note_id, populate_existing=True)
    assert note is not None
    return await commit_change(session, caller, note, "updated", trace_id)


async def publish(
    session: AsyncSession,
    caller: CallerContext,
    note_id: uuid.UUID,
    revision: int,
    trace_id: str | None,
) -> ReleaseOut:
    require_admin(caller)
    note = await session.get(ReleaseNote, note_id)
    if note is None:
        raise _error(404, "版本日志不存在")
    if note.published_at is not None or note.revision != revision:
        raise _error(409, "日志已变更或已发布，请重新加载后再操作")
    if not note.entries:
        raise _error(422, "请至少添加一条更新内容后再发布")
    changed = await session.scalar(
        update(ReleaseNote)
        .where(
            ReleaseNote.id == note_id,
            ReleaseNote.published_at.is_(None),
            ReleaseNote.revision == revision,
        )
        .values(
            published_at=utc_now(),
            published_by=caller.user_id,
            revision=revision + 1,
            updated_at=utc_now(),
        )
        .returning(ReleaseNote.id)
    )
    if changed is None:
        raise _error(409, "日志已变更或已发布，请重新加载后再操作")
    await session.refresh(note)
    return await commit_change(session, caller, note, "published", trace_id)


async def mark_read(
    session: AsyncSession, caller: CallerContext, ids: list[uuid.UUID]
) -> ReleaseStatus:
    require_reader(caller)
    # Only acknowledge explicitly displayed published IDs, never unseen concurrent releases.
    visible = (
        await session.scalars(
            select(ReleaseNote.id).where(
                ReleaseNote.id.in_(ids),
                ReleaseNote.published_at.is_not(None),
            )
        )
    ).all()
    for release_id in visible:
        try:
            async with session.begin_nested():
                session.add(ReleaseNoteRead(user_id=caller.user_id, release_id=release_id))
                await session.flush()
        except IntegrityError:
            pass  # Concurrent tabs / retries are idempotent.
    await session.commit()
    return await status(session, caller)
