"""Read-only authorization projection for notification targets.

This repository deliberately queries domain facts directly. It never imports or
invokes review, ingest, original-access, or knowledge command services.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.indexing_job import IndexingOperationJob
from app.models.ingest import IngestTask
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.notification import BusinessNotification
from app.models.original_access import OriginalAccessRequest
from app.models.review import ReviewTask
from app.schemas.enums import AccessRequestStatus, CompanyRole, ProjectRole
from app.schemas.notification import NotificationTarget
from app.schemas.permission import AccessLayer, CallerContext
from app.services.permission import decide

_ROUTES = {
    "review": "reviews",
    "original_access_request": "original_access",
    "ingest_task": "upload",
    "ops_index": "admin_ingest",
    "indexing_job": "admin_ingest",
    "knowledge_asset": "knowledge_detail",
}


@dataclass(frozen=True, slots=True)
class VisibleNotificationTarget:
    target: NotificationTarget
    status: str
    action_required: bool


def _ops_viewer(caller: CallerContext) -> bool:
    return CompanyRole.admin.value in caller.active_company_roles or caller.can_discover_l5


def _review_status(task: ReviewTask, can_decide: bool) -> tuple[str, bool]:
    actionable = task.status in {"pending_reviewer", "approval_failed"} and can_decide
    status = (
        "failed"
        if task.status == "approval_failed"
        else "completed"
        if task.status in {"approved", "rejected"}
        else "processing"
        if task.status == "approving"
        else "needs_action"
        if actionable
        else "submitted"
    )
    return status, actionable


async def resolve(
    session: AsyncSession, caller: CallerContext, row: BusinessNotification
) -> VisibleNotificationTarget | None:
    if not caller.is_active or (not caller.is_business_user and not _ops_viewer(caller)):
        return None
    if (
        row.project_id is not None
        and row.target_kind not in {"indexing_job", "ops_index"}
        and row.event_type != "review.company_confirmation_pending"
        and row.project_id not in caller.active_project_ids
    ):
        return None

    route_key = _ROUTES.get(row.target_kind)
    if route_key is None:
        return None
    if row.target_kind == "review":
        review_task = await session.get(ReviewTask, row.target_id)
        if review_task is None:
            return None
        if row.event_type == "review.decided":
            if review_task.submitted_by != caller.user_id:
                return None
            status = "completed"
            action_required = False
        elif row.event_type == "review.project_pending":
            can_decide = bool(
                row.project_id is not None
                and caller.active_project_roles.get(row.project_id)
                == ProjectRole.project_manager.value
            )
        elif row.event_type == "review.company_confirmation_pending":
            can_decide = bool(
                {CompanyRole.boss.value, CompanyRole.consulting_director.value}
                & set(caller.active_company_roles)
            )
        else:
            return None
        if row.event_type != "review.decided":
            if not can_decide:
                return None
            status, action_required = _review_status(review_task, can_decide)
    elif row.target_kind == "original_access_request":
        request = await session.get(OriginalAccessRequest, row.target_id)
        if request is None:
            return None
        asset = await session.get(KnowledgeAsset, request.asset_id)
        if asset is None:
            return None
        if row.event_type == "original_access.decided":
            if request.requester_user_id != caller.user_id:
                return None
            if not decide(caller, asset, AccessLayer.discovery).allowed:
                return None
            action_required = False
            status = "completed"
        else:
            governance = bool(
                {CompanyRole.boss.value, CompanyRole.consulting_director.value}
                & set(caller.active_company_roles)
            )
            project_approver = bool(
                asset.project_id is not None
                and caller.active_project_roles.get(asset.project_id)
                in {ProjectRole.project_manager.value, ProjectRole.coach.value}
            )
            if not governance and not project_approver:
                return None
            action_required = request.status == AccessRequestStatus.pending.value
            status = "needs_action" if action_required else "completed"
    elif row.target_kind == "ingest_task":
        ingest_task = await session.get(IngestTask, row.target_id)
        if ingest_task is None or ingest_task.created_by != caller.user_id:
            return None
        action_required = ingest_task.status == "failed"
        status = {
            "failed": "failed",
            "processing": "processing",
            "completed": "completed",
            "duplicate_skipped": "duplicate_skipped",
            "waiting_review": "submitted",
            "pending_confirmation": "needs_action",
        }.get(ingest_task.status, "submitted")
    elif row.target_kind == "ops_index":
        if not _ops_viewer(caller):
            return None
        action_required = False
        status = "failed"
    elif row.target_kind == "knowledge_asset":
        asset = await session.get(KnowledgeAsset, row.target_id)
        if asset is None or not decide(caller, asset, AccessLayer.discovery).allowed:
            return None
        version = (
            await session.get(KnowledgeAssetVersion, asset.current_version_id)
            if asset.current_version_id is not None
            else None
        )
        action_required = version is not None and version.index_status == "index_failed"
        status = "failed" if action_required else "completed"
    else:
        job = await session.get(IndexingOperationJob, row.target_id)
        if job is None or (job.requested_by_user_id != caller.user_id and not _ops_viewer(caller)):
            return None
        action_required = False
        status = {
            "queued": "submitted",
            "running": "processing",
            "completed": "completed",
            "no_action": "completed",
            "completed_with_errors": "partial",
            "failed": "failed",
        }.get(job.status, "submitted")
        if job.operation_type == "kb_migrate":
            route_key = "models"
    return VisibleNotificationTarget(
        target=NotificationTarget(route_key=route_key, resource_id=row.target_id),
        status=status,
        action_required=action_required,
    )
