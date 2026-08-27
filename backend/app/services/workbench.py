"""Compose the first-party browser workbench from existing business services."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import TypeVar

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import safe_log_exception
from app.models.identity import Project, ProjectMember, User
from app.models.ingest import IngestTask
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
    WorkbenchTaskCenterSection,
    WorkbenchTaskItem,
    WorkbenchTaskSummary,
    WorkbenchTodoItem,
    WorkbenchTodosSection,
)
from app.services import indexing_ops as indexing_ops_service
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
_REVIEW_TERMINAL_STATUSES = {"approved", "rejected"}
_JOB_RUNNING_STATUSES = {"queued", "running"}
_JOB_TERMINAL_STATUSES = {"completed", "completed_with_errors", "failed", "no_action"}
_PRIORITY_ORDER = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
_TASK_STATUS_ORDER = {"failed": 0, "needs_action": 1, "processing": 2, "submitted": 3}
_OPS_TASK_TYPES = {
    "retry_index": "indexing",
    "reparse": "parsing",
    "kb_migrate": "kb_migration",
    "markdown_backfill": "markdown_backfill",
}
_OPS_OBJECT_NAMES = {
    "retry_index": "索引重试作业",
    "reparse": "解析重试作业",
    "kb_migrate": "知识库迁移",
    "markdown_backfill": "规范 Markdown 补齐",
}
_ATTENTION_OBJECT_NAMES = {
    "index_failed": "索引失败或中断资产",
    "parse_failed": "解析异常资产",
    "kb_init_failed": "知识库初始化异常",
    "pending_original_requests": "待处理原文申请",
    "overdue_original_requests": "超时原文申请",
    "archive_candidates": "归档候选资产",
    "reuse_upgrade_candidates": "复用升格候选",
}


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


def _task_ref(task_type: str, source_id: object) -> str:
    """Return a stable opaque browser reference without exposing a database identifier."""
    digest = hashlib.sha256(f"workbench:{task_type}:{source_id}".encode()).hexdigest()[:20]
    return f"{task_type}-{digest}"


def _waiting_minutes(created_at: datetime | None) -> int | None:
    if created_at is None:
        return None
    value = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - value).total_seconds() // 60))


def _priority(*, failed: bool, waiting_minutes: int | None, action_required: bool) -> str:
    if failed or (waiting_minutes is not None and waiting_minutes >= 24 * 60):
        return "urgent"
    if action_required or (waiting_minutes is not None and waiting_minutes >= 8 * 60):
        return "high"
    return "normal"


def _sort_tasks(items: list[WorkbenchTaskItem]) -> None:
    items.sort(
        key=lambda item: (
            _PRIORITY_ORDER.get(item.priority, 9),
            _TASK_STATUS_ORDER.get(item.status, 9),
            -(item.waiting_minutes or 0),
            item.task_ref,
        )
    )


async def _caller_name(session: AsyncSession, caller: CallerContext) -> str:
    name = await session.scalar(select(User.name).where(User.id == caller.user_id))
    return (name or "当前用户").strip() or "当前用户"


async def build_task_center(
    session: AsyncSession, caller: CallerContext
) -> WorkbenchTaskCenterSection:
    """Aggregate real task sources through their existing permission-filtered services."""
    is_ops_viewer = "admin" in caller.active_company_roles or caller.can_discover_l5
    if not caller.is_business_user and not is_ops_viewer:
        raise HTTPException(status_code=403)

    current_name = await _caller_name(session, caller)
    my_tasks: list[WorkbenchTaskItem] = []
    running_jobs: list[WorkbenchTaskItem] = []
    attention_items: list[WorkbenchTaskItem] = []
    recent_completed: list[WorkbenchTaskItem] = []

    if caller.is_business_user:
        reviews = await review_service.list_reviews(session, caller)
        for review_item in reviews:
            waiting = _waiting_minutes(review_item.created_at)
            actionable = review_item.can_decide and review_item.status in {
                "pending_reviewer",
                "approval_failed",
            }
            is_mine = actionable or (
                review_item.submitted_by == caller.user_id
                and review_item.status not in _REVIEW_TERMINAL_STATUSES
            )
            if is_mine:
                failed = review_item.status == "approval_failed"
                my_tasks.append(
                    WorkbenchTaskItem(
                        task_ref=_task_ref("review", review_item.id),
                        task_type="review",
                        object_name=(review_item.asset_title or "待审核知识资产").strip(),
                        project_name=review_item.project_name,
                        status=(
                            "failed"
                            if failed
                            else "needs_action"
                            if actionable
                            else "processing"
                            if review_item.status == "approving"
                            else "submitted"
                        ),
                        priority=_priority(
                            failed=failed, waiting_minutes=waiting, action_required=actionable
                        ),
                        assignee=current_name if actionable else "审核负责人",
                        responsibility="由你处理" if actionable else "由你提交",
                        created_at=review_item.created_at,
                        updated_at=review_item.reviewed_at or review_item.created_at,
                        waiting_minutes=waiting,
                        next_action_key="resolve_review"
                        if failed
                        else "decide_review"
                        if actionable
                        else None,
                        next_action_label=(
                            "处理失败原因"
                            if failed
                            else "进入审核"
                            if actionable
                            else "等待审核结果"
                        ),
                        route_key="reviews",
                    )
                )
            if review_item.status in _REVIEW_TERMINAL_STATUSES and review_item.reviewed_at:
                reviewed = review_item.reviewed_at
                reviewed_date = (
                    reviewed if reviewed.tzinfo else reviewed.replace(tzinfo=timezone.utc)
                ).date()
                if reviewed_date == datetime.now(timezone.utc).date() and (
                    review_item.submitted_by == caller.user_id
                    or review_item.reviewer_user_id == caller.user_id
                ):
                    recent_completed.append(
                        WorkbenchTaskItem(
                            task_ref=_task_ref("review", review_item.id),
                            task_type="review",
                            object_name=(review_item.asset_title or "知识资产审核").strip(),
                            project_name=review_item.project_name,
                            status="completed",
                            priority="low",
                            assignee=current_name,
                            responsibility="已处理",
                            created_at=review_item.created_at,
                            updated_at=review_item.reviewed_at,
                            next_action_label="查看审核结果",
                            route_key="reviews",
                            result_summary="审核已通过"
                            if review_item.status == "approved"
                            else "审核已结束",
                        )
                    )

        ingest_items = await ingest_service.list_pending(
            session,
            caller,
            statuses={
                "pending",
                "processing",
                "pending_confirmation",
                "waiting_review",
                "failed",
                "rejected",
            },
        )
        for ingest_item in ingest_items:
            waiting = _waiting_minutes(ingest_item.created_at)
            actionable = ingest_item.status in {"pending_confirmation", "failed", "rejected"}
            failed = ingest_item.status in {"failed", "rejected"}
            task = WorkbenchTaskItem(
                task_ref=_task_ref("ingest", ingest_item.id),
                task_type="ingest",
                object_name=(
                    ingest_item.suggested_title or ingest_item.source_file_name or "待入库资料"
                ).strip(),
                status=(
                    "failed"
                    if failed
                    else "needs_action"
                    if actionable
                    else "processing"
                    if ingest_item.status in {"processing", "waiting_review"}
                    else "submitted"
                ),
                priority=_priority(
                    failed=failed, waiting_minutes=waiting, action_required=actionable
                ),
                assignee=current_name if actionable else "系统作业",
                responsibility="由你确认" if actionable else "由你发起",
                created_at=ingest_item.created_at,
                updated_at=ingest_item.updated_at or ingest_item.created_at,
                waiting_minutes=waiting,
                next_action_key="retry_ingest"
                if failed
                else "confirm_ingest"
                if actionable
                else None,
                next_action_label=(
                    "修正或重试" if failed else "核对并确认" if actionable else "等待处理完成"
                ),
                route_key="upload",
            )
            (my_tasks if actionable else running_jobs).append(task)

        access_inbox = await original_access_service.list_requests(
            session, caller, box="inbox", status="pending"
        )
        for access_item in access_inbox.items:
            waiting = _waiting_minutes(access_item.created_at)
            my_tasks.append(
                WorkbenchTaskItem(
                    task_ref=_task_ref("original_access", access_item.request_id),
                    task_type="original_access",
                    object_name=(access_item.asset_title or "原文访问申请").strip(),
                    status="needs_action",
                    priority=_priority(failed=False, waiting_minutes=waiting, action_required=True),
                    assignee=current_name,
                    responsibility="由你审批",
                    created_at=access_item.created_at,
                    updated_at=access_item.created_at,
                    waiting_minutes=waiting,
                    next_action_key="decide_original_access",
                    next_action_label="审批原文访问",
                    route_key="original_access",
                )
            )
        mine_access = await original_access_service.list_requests(session, caller, box="mine")
        for access_item in mine_access.items:
            if access_item.status == "pending":
                waiting = _waiting_minutes(access_item.created_at)
                my_tasks.append(
                    WorkbenchTaskItem(
                        task_ref=_task_ref("original_access", access_item.request_id),
                        task_type="original_access",
                        object_name=(access_item.asset_title or "原文访问申请").strip(),
                        status="submitted",
                        priority="normal",
                        assignee=access_item.reviewer_name or "项目审批人",
                        responsibility="由你提交",
                        created_at=access_item.created_at,
                        updated_at=access_item.created_at,
                        waiting_minutes=waiting,
                        next_action_label="等待审批结果",
                        route_key="original_access",
                    )
                )
            elif access_item.reviewed_at:
                reviewed = access_item.reviewed_at
                reviewed_date = (
                    reviewed if reviewed.tzinfo else reviewed.replace(tzinfo=timezone.utc)
                ).date()
                if reviewed_date == datetime.now(timezone.utc).date():
                    recent_completed.append(
                        WorkbenchTaskItem(
                            task_ref=_task_ref("original_access", access_item.request_id),
                            task_type="original_access",
                            object_name=(access_item.asset_title or "原文访问申请").strip(),
                            status="completed" if access_item.status == "approved" else "failed",
                            priority="low",
                            assignee=access_item.reviewer_name or "项目审批人",
                            responsibility="由你提交",
                            created_at=access_item.created_at,
                            updated_at=access_item.reviewed_at,
                            next_action_label="查看审批结果",
                            route_key="original_access",
                            result_summary="访问已授权"
                            if access_item.status == "approved"
                            else "申请未通过",
                        )
                    )

        completed_ingest = list(
            (
                await session.execute(
                    select(IngestTask)
                    .where(
                        IngestTask.created_by == caller.user_id,
                        IngestTask.status.in_({"completed", "duplicate_skipped"}),
                    )
                    .order_by(IngestTask.updated_at.desc())
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )
        for completed_ingest_item in completed_ingest:
            updated = completed_ingest_item.updated_at or completed_ingest_item.created_at
            updated_date = (
                updated if updated.tzinfo else updated.replace(tzinfo=timezone.utc)
            ).date()
            if updated_date == datetime.now(timezone.utc).date():
                recent_completed.append(
                    WorkbenchTaskItem(
                        task_ref=_task_ref("ingest", completed_ingest_item.id),
                        task_type="ingest",
                        object_name=completed_ingest_item.source_file_name.strip()
                        or "知识资产入库",
                        status=(
                            "duplicate_skipped"
                            if completed_ingest_item.status == "duplicate_skipped"
                            else "completed"
                        ),
                        priority="low",
                        assignee=current_name,
                        responsibility="由你发起",
                        created_at=completed_ingest_item.created_at,
                        updated_at=updated,
                        next_action_label="查看入库结果",
                        route_key="upload",
                        result_summary=(
                            "因内容重复已跳过"
                            if completed_ingest_item.status == "duplicate_skipped"
                            else "入库已完成"
                        ),
                    )
                )

    if is_ops_viewer:
        jobs = await indexing_ops_service.list_jobs(session, caller)
        for job in jobs.items:
            if job.status not in _JOB_RUNNING_STATUSES | _JOB_TERMINAL_STATUSES:
                continue
            mapped_status = (
                "submitted"
                if job.status == "queued"
                else "processing"
                if job.status == "running"
                else "partial"
                if job.status == "completed_with_errors"
                else "failed"
                if job.status == "failed"
                else "completed"
            )
            task = WorkbenchTaskItem(
                task_ref=_task_ref("operation", job.job_id),
                task_type=_OPS_TASK_TYPES.get(job.operation_type, "operation"),
                object_name=_OPS_OBJECT_NAMES.get(job.operation_type, "后台作业"),
                status=mapped_status,
                priority="urgent"
                if mapped_status == "failed"
                else "high"
                if mapped_status == "partial"
                else "normal",
                assignee=job.requested_by_name or "平台运维",
                responsibility="运维作业",
                created_at=job.requested_at,
                updated_at=job.finished_at or job.started_at or job.requested_at,
                waiting_minutes=_waiting_minutes(job.requested_at),
                next_action_key="inspect_operation",
                next_action_label="处理失败项"
                if mapped_status in {"failed", "partial"}
                else "查看作业进度"
                if mapped_status in {"submitted", "processing"}
                else "查看作业结果",
                route_key="models" if job.operation_type == "kb_migrate" else "admin_ingest",
                result_summary=(
                    f"成功 {job.success_count}，失败 {job.failed_count}，跳过 {job.skipped_count}"
                    if mapped_status in {"completed", "partial", "failed"}
                    else None
                ),
                progress_total=job.total_count,
                progress_success=job.success_count,
                progress_failed=job.failed_count,
            )
            if job.status in _JOB_RUNNING_STATUSES:
                running_jobs.append(task)
            elif job.finished_at:
                finished = (
                    job.finished_at
                    if job.finished_at.tzinfo
                    else job.finished_at.replace(tzinfo=timezone.utc)
                )
                if finished.date() == datetime.now(timezone.utc).date():
                    recent_completed.append(task)

    if is_ops_viewer:
        insights = await insights_service.get_ops_insights(
            session, caller, scope=None, project_id=None, days=30, limit=8
        )
        for index, card in enumerate(insights.cards):
            if card.count <= 0 or card.key not in _ATTENTION_OBJECT_NAMES:
                continue
            attention_items.append(
                WorkbenchTaskItem(
                    task_ref=_task_ref("attention", f"{card.key}:{card.scope}:{index}"),
                    task_type=card.key,
                    object_name=_ATTENTION_OBJECT_NAMES[card.key],
                    project_name=card.context_label,
                    status="failed" if card.severity == "error" else "needs_action",
                    priority="urgent"
                    if card.severity == "error"
                    else "high"
                    if card.severity == "warning"
                    else "normal",
                    assignee="有权限的治理负责人",
                    responsibility="运营关注",
                    next_action_key="inspect_attention",
                    next_action_label="查看受影响范围",
                    route_key="models"
                    if card.key == "kb_init_failed"
                    else "original_access"
                    if "original" in card.key
                    else "knowledge"
                    if card.key in {"archive_candidates", "reuse_upgrade_candidates"}
                    else "admin_ingest",
                    result_summary=f"当前有 {card.count} 项需要关注",
                )
            )

    for items in (my_tasks, running_jobs, attention_items, recent_completed):
        _sort_tasks(items)
    priority_items = sorted(
        [*my_tasks, *attention_items],
        key=lambda item: (_PRIORITY_ORDER.get(item.priority, 9), -(item.waiting_minutes or 0)),
    )[:5]
    summary = WorkbenchTaskSummary(
        needs_action=sum(item.status in {"needs_action", "failed"} for item in my_tasks),
        running=len(running_jobs),
        attention=len(attention_items),
        completed_today=len(recent_completed),
    )
    has_items = any((my_tasks, running_jobs, attention_items, recent_completed))
    return WorkbenchTaskCenterSection(
        status=WorkbenchSectionStatus.available if has_items else WorkbenchSectionStatus.empty,
        summary=summary,
        priority_items=priority_items,
        my_tasks=my_tasks[:20],
        running_jobs=running_jobs[:20],
        attention_items=attention_items[:20],
        recent_completed=recent_completed[:20],
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
        require_directory_context=False,
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
    task_center = await _load_section(
        session,
        "task_center",
        lambda: build_task_center(session, caller),
        WorkbenchTaskCenterSection,
    )
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
        task_center=task_center,
        todos=todos,
        operations=operations,
        projects=projects,
        recent_activity=recent_activity,
    )
