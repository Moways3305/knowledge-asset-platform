"""Prebuilt knowledge maintenance agent; commands stay in the service layer."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.maintenance_agent import (
    IssueCommand,
    IssueDetail,
    IssuePage,
    PolicyCommand,
    PolicyOut,
    RunDeleteCommand,
    RunDeleteResult,
    RunDetail,
    RunOut,
)
from app.schemas.permission import CallerContext
from app.services import maintenance_agent as service
from app.services import maintenance_run_actions as run_actions

router = APIRouter(prefix="/api/v1/maintenance-agent", tags=["maintenance-agent"])


@router.get("/policies", response_model=list[PolicyOut])
async def policies(
    caller: CallerContext = Depends(get_caller_context), session: AsyncSession = Depends(get_db)
):
    return await service.policies(session, caller)


@router.put("/policies/{library_key}", response_model=PolicyOut)
async def configure(
    library_key: str,
    body: PolicyCommand,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await service.configure(session, caller, library_key, body, get_trace_id(request))


@router.post("/policies/{library_key}/runs", response_model=RunOut)
async def run_now(
    library_key: str,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await service.run_now(session, caller, library_key, get_trace_id(request))


@router.get("/policies/{library_key}/runs", response_model=list[RunOut])
async def runs(
    library_key: str,
    page: int = Query(1, ge=1),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await service.runs(session, caller, library_key, page)


@router.get("/policies/{library_key}/runs/{run_id}", response_model=RunDetail)
async def run_detail(
    library_key: str,
    run_id: uuid.UUID,
    page: int = Query(1, ge=1),
    status: Literal["pending", "completed", "incomplete", "skipped"] | None = None,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await service.run_detail(session, caller, library_key, run_id, page=page, status=status)


@router.post("/policies/{library_key}/runs/delete", response_model=RunDeleteResult)
async def delete_runs(
    library_key: str,
    body: RunDeleteCommand,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await run_actions.delete_records(
        session, caller, library_key, body.run_ids, get_trace_id(request)
    )


@router.delete("/policies/{library_key}/runs/{run_id}", response_model=RunDeleteResult)
async def delete_run(
    library_key: str,
    run_id: uuid.UUID,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await run_actions.delete_records(
        session, caller, library_key, [run_id], get_trace_id(request)
    )


@router.post("/policies/{library_key}/runs/{run_id}/cancel", response_model=RunOut)
async def cancel_run(
    library_key: str,
    run_id: uuid.UUID,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await run_actions.cancel(session, caller, library_key, run_id, get_trace_id(request))


@router.post("/policies/{library_key}/runs/{run_id}/retry", response_model=RunOut)
async def retry_run(
    library_key: str,
    run_id: uuid.UUID,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await run_actions.retry(session, caller, library_key, run_id, get_trace_id(request))


@router.get("/issues", response_model=IssuePage)
async def issues(
    library_key: str | None = None,
    digest_id: uuid.UUID | None = None,
    priority: Literal["all", "actionable", "suggestion"] = "all",
    asset_id: uuid.UUID | None = None,
    status: Literal[
        "active",
        "all",
        "open",
        "in_progress",
        "awaiting_recheck",
        "resolved",
        "false_positive",
        "snoozed",
        "not_applicable",
    ] = "active",
    category: Literal[
        "integrity", "availability", "maintenance", "duplicates", "quality", "privacy"
    ]
    | None = None,
    mine: bool = False,
    page: int = Query(1, ge=1),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await service.list_issues(
        session,
        caller,
        key=library_key,
        status=status,
        category=category,
        mine=mine,
        page=page,
        priority=priority,
        asset_id=asset_id,
        digest_id=digest_id,
    )


@router.get("/issues/{issue_id}", response_model=IssueDetail)
async def issue_detail(
    issue_id: uuid.UUID,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await service.detail(session, caller, issue_id, get_trace_id(request))


@router.post("/issues/{issue_id}/actions", response_model=IssueDetail)
async def issue_action(
    issue_id: uuid.UUID,
    body: IssueCommand,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await service.transition(session, caller, issue_id, body, get_trace_id(request))
