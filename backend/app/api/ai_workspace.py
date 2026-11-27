"""Authenticated harness commands; persistence and execution live in services."""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_caller_context
from app.db.session import get_db
from app.schemas.ai_workspace import (
    ArtifactOut,
    ArtifactPatch,
    EventPage,
    MessageCreate,
    OptionsOut,
    RetryCommand,
    RunOut,
    SessionCreate,
    SessionDetail,
    SessionOut,
    SessionPatch,
)
from app.schemas.permission import CallerContext
from app.services import ai_workspace as service


class PrivateInputRoute(APIRoute):
    """Validation must not echo pasted personal information in error responses."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def private_handler(request):
            try:
                return await handler(request)
            except RequestValidationError:
                raise HTTPException(
                    422, detail={"message": "输入格式或长度不符合要求，请检查后重试"}
                ) from None

        return private_handler


router = APIRouter(
    prefix="/api/v1/ai-workspace", tags=["ai-workspace"], route_class=PrivateInputRoute
)


@router.get("/options", response_model=OptionsOut)
async def options(
    caller: CallerContext = Depends(get_caller_context), session: AsyncSession = Depends(get_db)
):
    return await service.options(session, caller)


@router.get("/sessions", response_model=list[SessionOut])
async def sessions(
    caller: CallerContext = Depends(get_caller_context), session: AsyncSession = Depends(get_db)
):
    return await service.sessions(session, caller)


@router.post("/sessions", response_model=SessionOut, status_code=201)
async def create_session(
    body: SessionCreate,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await service.create_session(session, caller, body)


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def detail(
    session_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await service.detail(session, caller, session_id)


@router.patch("/sessions/{session_id}", response_model=SessionOut)
async def rename_session(
    session_id: uuid.UUID,
    body: SessionPatch,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await service.rename_session(session, caller, session_id, body)


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    await service.delete_session(session, caller, session_id)
    return Response(status_code=204)


@router.post("/sessions/{session_id}/messages", response_model=RunOut, status_code=202)
async def send_message(
    session_id: uuid.UUID,
    body: MessageCreate,
    background: BackgroundTasks,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    run = await service.start(session, caller, session_id, body)
    if run.status == "queued":
        background.add_task(
            service.execute, async_sessionmaker(session.bind, expire_on_commit=False), run.id
        )
    return run


@router.get("/sessions/{session_id}/events", response_model=EventPage)
async def events(
    session_id: uuid.UUID,
    after: int = Query(0, ge=0),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await service.events(session, caller, session_id, after)


@router.post("/sessions/{session_id}/runs/{run_id}/stop", response_model=RunOut)
async def stop(
    session_id: uuid.UUID,
    run_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await service.stop(session, caller, session_id, run_id)


@router.post("/sessions/{session_id}/runs/{run_id}/retry", response_model=RunOut, status_code=202)
async def retry(
    session_id: uuid.UUID,
    run_id: uuid.UUID,
    body: RetryCommand,
    background: BackgroundTasks,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    run = await service.retry(session, caller, session_id, run_id, body)
    if run.status == "queued":
        background.add_task(
            service.execute, async_sessionmaker(session.bind, expire_on_commit=False), run.id
        )
    return run


@router.patch("/sessions/{session_id}/artifacts/{artifact_id}", response_model=ArtifactOut)
async def edit_artifact(
    session_id: uuid.UUID,
    artifact_id: uuid.UUID,
    body: ArtifactPatch,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await service.edit_artifact(session, caller, session_id, artifact_id, body)
