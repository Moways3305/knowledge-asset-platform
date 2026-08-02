"""Naming rule governance and authorized confirmation preview API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.enums import KnowledgeScope
from app.schemas.naming import (
    NamingDraftUpdateRequest,
    NamingOptionsResponse,
    NamingPreviewRequest,
    NamingPreviewResponse,
    NamingPublishRequest,
    NamingRuleCenterOut,
    NamingRuleRevisionOut,
)
from app.schemas.permission import CallerContext
from app.services import naming_rules

router = APIRouter(prefix="/api/v1", tags=["naming-rules"])


@router.get("/admin/naming-rules", response_model=NamingRuleCenterOut)
async def get_rule_center(
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> NamingRuleCenterOut:
    return await naming_rules.get_rule_center(session, caller)


@router.put("/admin/naming-rules/draft", response_model=NamingRuleRevisionOut)
async def save_draft(
    body: NamingDraftUpdateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> NamingRuleRevisionOut:
    return await naming_rules.save_draft(session, caller, body, get_trace_id(request))


@router.post("/admin/naming-rules/publish", response_model=NamingRuleCenterOut)
async def publish_draft(
    body: NamingPublishRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> NamingRuleCenterOut:
    return await naming_rules.publish_draft(session, caller, body, get_trace_id(request))


@router.post(
    "/ingest/{task_id}/naming-preview",
    response_model=NamingPreviewResponse,
)
async def preview_naming(
    task_id: uuid.UUID,
    body: NamingPreviewRequest,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> NamingPreviewResponse:
    return await naming_rules.preview(session, caller, task_id, body)


@router.get("/naming-options", response_model=NamingOptionsResponse)
async def get_naming_options(
    scope: KnowledgeScope = Query(),
    project_id: uuid.UUID | None = Query(default=None),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> NamingOptionsResponse:
    return await naming_rules.options(session, caller, scope, project_id)
