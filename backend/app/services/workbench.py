"""Compose the first-party browser workbench from existing business services."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import safe_log_exception
from app.models.identity import Project, ProjectMember
from app.schemas.permission import CallerContext
from app.schemas.workbench import (
    WorkbenchOperationsIndexing,
    WorkbenchOperationsSection,
    WorkbenchOperationsSummary,
    WorkbenchOverviewResponse,
    WorkbenchProjectItem,
    WorkbenchProjectsSection,
    WorkbenchRecentActivityItem,
    WorkbenchRecentActivitySection,
    WorkbenchSectionStatus,
    WorkbenchTodoItem,
    WorkbenchTodosSection,
)
from app.services import ingest as ingest_service
from app.services import knowledge as knowledge_service
from app.services import knowledge_insights as insights_service
from app.services import original_access as original_access_service
from app.services import review as review_service

_logger = logging.getLogger(__name__)
_SectionT = TypeVar("_SectionT", bound=BaseModel)

_TODO_DEFINITIONS = {
    "review_approval_failed": ("error", "reviews", "resolve_review"),
    "review_pending": ("warning", "reviews", "decide_review"),
    "ingest_pending": ("warning", "upload", "confirm_ingest"),
    "ingest_failed": ("error", "upload", "retry_ingest"),
    "original_access_pending": ("info", "original_access", "decide_original_access"),
}
_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
# 待确认口径收窄：只统计真正需要用户确认的任务；失败 / 被拒归入独立待办。
_INGEST_PENDING_STATUSES = {"pending_confirmation"}
_INGEST_FAILED_STATUSES = {"failed", "rejected"}


async def _rollback_safely(session: AsyncSession, section: str) -> None:
    try:
        await session.rollback()
    except Exception as exc:
        safe_log_exception(
            _logger,
            "workbench_section_rollback_failed",
            exc,
            include_summary=False,
            section=section,
        )


async def _load_section(
    session: AsyncSession,
    name: str,
    loader: Callable[[], Awaitable[_SectionT]],
    section_type: type[_SectionT],
) -> _SectionT:
    try:
        return await loader()
    except HTTPException as exc:
        await _rollback_safely(session, name)
        if exc.status_code in {401, 403}:
            return section_type.model_validate(
                {"status": WorkbenchSectionStatus.forbidden, "error_code": f"{name}_forbidden"}
            )
        safe_log_exception(
            _logger,
            "workbench_section_failed",
            exc,
            include_summary=False,
            section=name,
        )
    except Exception as exc:
        await _rollback_safely(session, name)
        safe_log_exception(
            _logger,
            "workbench_section_failed",
            exc,
            include_summary=False,
            section=name,
        )
    return section_type.model_validate(
        {"status": WorkbenchSectionStatus.error, "error_code": f"{name}_unavailable"}
    )


def _todo_item(key: str, count: int) -> WorkbenchTodoItem:
    severity, route_key, action_key = _TODO_DEFINITIONS[key]
    return WorkbenchTodoItem(
        key=key,
        count=count,
        severity=severity,
        route_key=route_key,
        action_key=action_key,
    )


async def build_todos(session: AsyncSession, caller: CallerContext) -> WorkbenchTodosSection:
    if not caller.is_business_user:
        raise HTTPException(status_code=403)

    reviews = await review_service.list_reviews(session, caller)
    pending_reviews = sum(item.can_decide and item.status == "pending_reviewer" for item in reviews)
    failed_reviews = sum(item.can_decide and item.status == "approval_failed" for item in reviews)
    pending_ingest_items = await ingest_service.list_pending(
        session, caller, statuses=_INGEST_PENDING_STATUSES
    )
    failed_ingest_items = await ingest_service.list_pending(
        session, caller, statuses=_INGEST_FAILED_STATUSES
    )
    pending_ingest = len(pending_ingest_items)
    failed_ingest = len(failed_ingest_items)
    access_inbox = await original_access_service.list_requests(
        session, caller, box="inbox", status="pending"
    )

    counts = {
        "review_approval_failed": failed_reviews,
        "review_pending": pending_reviews,
        "ingest_pending": pending_ingest,
        "ingest_failed": failed_ingest,
        "original_access_pending": access_inbox.total,
    }
    items = [_todo_item(key, count) for key, count in counts.items() if count > 0]
    items.sort(key=lambda item: (_SEVERITY_ORDER[item.severity], -item.count, item.key))
    total = sum(item.count for item in items)
    return WorkbenchTodosSection(
        status=WorkbenchSectionStatus.available if items else WorkbenchSectionStatus.empty,
        items=items,
        total=total,
    )


async def build_operations(
    session: AsyncSession, caller: CallerContext
) -> WorkbenchOperationsSection:
    insights = await insights_service.get_ops_insights(
        session,
        caller,
        scope=None,
        project_id=None,
        days=30,
        limit=5,
    )
    summary = WorkbenchOperationsSummary(
        title_visible=insights.title_visible,
        scope=insights.scope,
        window_days=insights.window_days,
        cards=insights.cards,
        indexing=WorkbenchOperationsIndexing(
            index_failed=insights.indexing.index_failed,
            skipped=insights.indexing.skipped,
            not_indexed=insights.indexing.not_indexed,
            parse_failed=insights.indexing.parse_failed,
            parse_pending=insights.indexing.parse_pending,
            parse_processing=insights.indexing.parse_processing,
            kb_init_failed=insights.indexing.kb_init_failed,
        ),
        access=insights.access,
        lifecycle=insights.lifecycle,
    )
    return WorkbenchOperationsSection(status=WorkbenchSectionStatus.available, data=summary)


async def build_projects(session: AsyncSession, caller: CallerContext) -> WorkbenchProjectsSection:
    if not caller.is_business_user:
        raise HTTPException(status_code=403)

    rows = (
        await session.execute(
            select(ProjectMember, Project)
            .join(Project, Project.id == ProjectMember.project_id)
            .where(
                ProjectMember.user_id == caller.user_id,
                ProjectMember.status == "active",
                Project.status == "active",
            )
            .order_by(Project.name, Project.id)
        )
    ).all()
    items = [
        WorkbenchProjectItem(
            project_id=project.id,
            name=project.name,
            status=project.status,
            project_role=membership.project_role,
            lifecycle_route_key=project.lifecycle_route_key,
            lifecycle_phase_key=project.lifecycle_phase_key,
        )
        for membership, project in rows
    ]
    return WorkbenchProjectsSection(
        status=WorkbenchSectionStatus.available if items else WorkbenchSectionStatus.empty,
        items=items,
        total=len(items),
    )


async def build_recent_activity(
    session: AsyncSession, caller: CallerContext
) -> WorkbenchRecentActivitySection:
    if not caller.is_business_user:
        raise HTTPException(status_code=403)

    result = await knowledge_service.list_knowledge(
        session,
        caller,
        scope=None,
        project_id=None,
        include_archived=False,
        keyword=None,
        zone=None,
        asset_type=None,
        asset_status=None,
        confidentiality_level=None,
        created_from=None,
        created_to=None,
        updated_from=None,
        updated_to=None,
        sort_by="updated_at",
        sort_direction="desc",
        page=1,
        page_size=10,
    )
    items = [
        WorkbenchRecentActivityItem(
            asset_id=item.id,
            title=item.title,
            scope=item.scope,
            zone=item.zone,
            asset_type=item.asset_type,
            confidentiality_level=item.confidentiality_level,
            summary=item.summary_text,
            project_name=item.project_name,
            updated_at=item.updated_at,
        )
        for item in result.items
    ]
    return WorkbenchRecentActivitySection(
        status=WorkbenchSectionStatus.available if items else WorkbenchSectionStatus.empty,
        items=items,
        total=len(items),
    )


async def get_overview(session: AsyncSession, caller: CallerContext) -> WorkbenchOverviewResponse:
    """Return all partitions even when one internal dependency fails."""
    todos = await _load_section(
        session,
        "todos",
        lambda: build_todos(session, caller),
        WorkbenchTodosSection,
    )
    operations = await _load_section(
        session,
        "operations",
        lambda: build_operations(session, caller),
        WorkbenchOperationsSection,
    )
    projects = await _load_section(
        session,
        "projects",
        lambda: build_projects(session, caller),
        WorkbenchProjectsSection,
    )
    recent_activity = await _load_section(
        session,
        "recent_activity",
        lambda: build_recent_activity(session, caller),
        WorkbenchRecentActivitySection,
    )
    return WorkbenchOverviewResponse(
        todos=todos,
        operations=operations,
        projects=projects,
        recent_activity=recent_activity,
    )
