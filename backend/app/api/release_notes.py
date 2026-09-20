"""Release notes: all active users read, active system administrators publish."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.permission import CallerContext
from app.schemas.release_note import (
    PublishRelease,
    ReadReleases,
    ReleaseDraft,
    ReleaseList,
    ReleaseOut,
    ReleaseStatus,
    ReleaseUpdate,
)
from app.services import release_notes as service

router = APIRouter(prefix="/api/v1", tags=["release-notes"])


@router.get("/release-notes/status", response_model=ReleaseStatus)
async def status(
    caller: CallerContext = Depends(get_caller_context), session: AsyncSession = Depends(get_db)
):
    return await service.status(session, caller)


@router.get("/release-notes", response_model=ReleaseList)
async def list_notes(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await service.list_notes(session, caller, page=page, page_size=page_size)


@router.post("/release-notes/read", response_model=ReleaseStatus)
async def read(
    body: ReadReleases,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await service.mark_read(session, caller, body.release_ids)


@router.get("/admin/release-notes", response_model=ReleaseList)
async def admin_list(
    state: Literal["draft", "published"] = "draft",
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await service.list_notes(
        session, caller, page=page, page_size=page_size, state=state, admin=True
    )


@router.post("/admin/release-notes", response_model=ReleaseOut, status_code=201)
async def create(
    body: ReleaseDraft,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await service.create(session, caller, body, get_trace_id(request))


@router.put("/admin/release-notes/{note_id}", response_model=ReleaseOut)
async def edit(
    note_id: uuid.UUID,
    body: ReleaseUpdate,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await service.edit(session, caller, note_id, body, get_trace_id(request))


@router.post("/admin/release-notes/{note_id}/publish", response_model=ReleaseOut)
async def publish(
    note_id: uuid.UUID,
    body: PublishRelease,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await service.publish(session, caller, note_id, body.revision, get_trace_id(request))
