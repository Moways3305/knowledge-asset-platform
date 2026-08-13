"""Naming rule governance and authorized confirmation preview API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.directory_migration import (
    DirectoryMigrationConfirmRequest,
    DirectoryMigrationConfirmResponse,
    DirectoryMigrationWorkspaceOut,
)
from app.schemas.enums import KnowledgeScope
from app.schemas.naming import (
    BatchNamingPreviewRequest,
    BatchNamingPreviewResponse,
    CategoryClassificationBatchRequest,
    CategoryClassificationBatchResponse,
    CategoryClassificationItemResponse,
    ManualCategorySelectionRequest,
    NamingDraftUpdateRequest,
    NamingOptionsResponse,
    NamingPreviewRequest,
    NamingPreviewResponse,
    NamingPublishRequest,
    NamingRuleCenterOut,
    NamingRuleRevisionOut,
)
from app.schemas.permission import CallerContext
from app.services import category_classification, directory_migration, naming_rules
from app.services.generation_models import get_generation_llm_client
from app.services.llm_client import LLMClient, NullLLMClient

router = APIRouter(prefix="/api/v1", tags=["naming-rules"])


@router.get("/admin/directory-migration", response_model=DirectoryMigrationWorkspaceOut)
async def get_directory_migration_workspace(
    scope: str | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    old_category: str | None = Query(default=None),
    directory_key: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> DirectoryMigrationWorkspaceOut:
    return await directory_migration.workspace(
        session,
        caller,
        scope=scope,
        project_id=project_id,
        old_category=old_category,
        directory_key=directory_key,
        status=status,
        page=page,
        page_size=page_size,
    )


@router.post("/admin/directory-migration/confirm", response_model=DirectoryMigrationConfirmResponse)
async def confirm_directory_migration(
    body: DirectoryMigrationConfirmRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> DirectoryMigrationConfirmResponse:
    return await directory_migration.confirm(session, caller, body, get_trace_id(request))


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


@router.post(
    "/ingest/bulk-naming-preview",
    response_model=BatchNamingPreviewResponse,
)
async def preview_batch_naming(
    body: BatchNamingPreviewRequest,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> BatchNamingPreviewResponse:
    return await naming_rules.batch_preview(session, caller, body)


@router.get("/naming-options", response_model=NamingOptionsResponse)
async def get_naming_options(
    scope: KnowledgeScope = Query(),
    project_id: uuid.UUID | None = Query(default=None),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> NamingOptionsResponse:
    return await naming_rules.options(session, caller, scope, project_id)


@router.post(
    "/ingest/bulk-category-classification",
    response_model=CategoryClassificationBatchResponse,
)
async def classify_categories(
    body: CategoryClassificationBatchRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    llm: LLMClient | NullLLMClient = Depends(get_generation_llm_client),
) -> CategoryClassificationBatchResponse:
    return await category_classification.classify_batch(
        session, caller, body, llm, get_trace_id(request)
    )


@router.put(
    "/ingest/{task_id}/category-selection",
    response_model=CategoryClassificationItemResponse,
)
async def save_manual_category(
    task_id: uuid.UUID,
    body: ManualCategorySelectionRequest,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> CategoryClassificationItemResponse:
    return await category_classification.save_manual_selection(session, caller, task_id, body)
