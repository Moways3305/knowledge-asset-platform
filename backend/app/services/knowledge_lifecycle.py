"""Knowledge asset lifecycle commands.

Read projections stay in :mod:`app.services.knowledge`; this module owns the
state-changing soft-delete workflow and its external index cleanup boundary.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import safe_log_exception
from app.db.utils import utc_now
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.original_access import AccessGrant, OriginalAccessRequest
from app.models.review import PersonalKnowledgeSubmission, ReviewTask
from app.schemas.enums import (
    AssetStatus,
    AuditAction,
    AuditLogType,
    KnowledgeScope,
    PersonalSubmissionType,
    ProjectRole,
    ReviewTaskStatus,
)
from app.schemas.knowledge import KnowledgeDeleteResponse
from app.schemas.permission import AccessLayer, CallerContext
from app.services import audit as audit_service
from app.services.permission import decide
from app.services.weknora_client import NullWeKnoraClient, WeKnoraClient, weknora_enabled

_logger = logging.getLogger(__name__)
_DELETED_STATUS = AssetStatus.deleted.value
_PENDING_REVIEW_STATUSES = {
    ReviewTaskStatus.pending_evidence.value,
    ReviewTaskStatus.pending_reviewer.value,
    ReviewTaskStatus.approving.value,
    ReviewTaskStatus.approval_failed.value,
}


def can_delete(caller: CallerContext, asset: KnowledgeAsset) -> bool:
    if asset.asset_status == _DELETED_STATUS or not caller.is_business_user:
        return False
    if asset.scope == KnowledgeScope.personal.value:
        return asset.owner_user_id == caller.user_id
    if asset.scope == KnowledgeScope.project.value:
        return (
            asset.project_id is not None
            and caller.active_project_roles.get(asset.project_id)
            == ProjectRole.project_manager.value
        )
    if asset.scope == KnowledgeScope.company.value:
        return caller.can_discover_l5
    return False


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"denied_reason": reason, "message": message},
    )


async def delete_asset(
    session: AsyncSession,
    caller: CallerContext,
    asset_id: uuid.UUID,
    *,
    reason: str | None,
    weknora: WeKnoraClient | NullWeKnoraClient,
    trace_id: str,
    weknora_is_enabled: Callable[[], bool] = weknora_enabled,
) -> KnowledgeDeleteResponse:
    """Soft-delete an asset and revoke all dependent runtime access."""
    asset = (
        await session.execute(
            select(KnowledgeAsset)
            .where(KnowledgeAsset.id == asset_id)
            .options(selectinload(KnowledgeAsset.tags))
        )
    ).scalar_one_or_none()
    not_found = _denied(404, "knowledge_asset_not_found", "知识资产不存在或不可见")
    if asset is None or asset.asset_status == _DELETED_STATUS:
        raise not_found
    if not can_delete(caller, asset):
        if not decide(caller, asset, AccessLayer.discovery).allowed:
            raise not_found
        if not caller.is_business_user:
            raise _denied(403, "admin_business_permission_denied", "系统管理员不具备业务知识删除权")
        raise _denied(403, "knowledge_delete_forbidden", "无权删除该知识资产")

    if asset.scope == KnowledgeScope.personal.value:
        pending_submission = (
            await session.execute(
                select(PersonalKnowledgeSubmission.id)
                .join(ReviewTask, ReviewTask.id == PersonalKnowledgeSubmission.review_task_id)
                .where(
                    PersonalKnowledgeSubmission.source_asset_id == asset.id,
                    PersonalKnowledgeSubmission.submission_type
                    == PersonalSubmissionType.submit_to_project.value,
                    ReviewTask.status.in_(_PENDING_REVIEW_STATUSES),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        active_project_copy = (
            await session.execute(
                select(KnowledgeAsset.id)
                .where(
                    KnowledgeAsset.source_asset_id == asset.id,
                    KnowledgeAsset.scope == KnowledgeScope.project.value,
                    KnowledgeAsset.asset_status == AssetStatus.active.value,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if pending_submission is not None or active_project_copy is not None:
            raise _denied(
                409, "personal_asset_project_locked", "项目审核或项目使用中的资料不可删除"
            )

    previous_status = asset.asset_status
    clean_reason = (reason or "").strip()[:500] or None
    grants = list(
        (
            await session.execute(
                select(AccessGrant).where(
                    AccessGrant.asset_id == asset_id,
                    AccessGrant.status == "active",
                )
            )
        )
        .scalars()
        .all()
    )
    for grant in grants:
        grant.status = "revoked"
        grant.revoked_at = utc_now()
        grant.revoked_by_user_id = caller.user_id
        grant.revoke_reason = "asset_deleted"

    requests = list(
        (
            await session.execute(
                select(OriginalAccessRequest).where(
                    OriginalAccessRequest.asset_id == asset_id,
                    OriginalAccessRequest.status == "pending",
                )
            )
        )
        .scalars()
        .all()
    )
    for request in requests:
        request.status = "cancelled"
        request.reviewer_user_id = caller.user_id
        request.reviewed_at = utc_now()
        request.review_note = "asset_deleted"

    weknora_attempted = False
    weknora_succeeded = False
    if weknora_is_enabled():
        version = (
            await session.execute(
                select(KnowledgeAssetVersion)
                .where(KnowledgeAssetVersion.asset_id == asset_id)
                .where(KnowledgeAssetVersion.version_status == "active")
            )
        ).scalar_one_or_none()
        doc_id = version.weknora_doc_id if version is not None else None
        if version is not None and doc_id:
            weknora_attempted = True
            try:
                await weknora.delete_knowledge(doc_id, trace_id=trace_id)
                weknora_succeeded = True
                version.weknora_parse_status = "deleted"
            except Exception as exc:  # noqa: BLE001
                safe_log_exception(
                    _logger,
                    "weknora_delete_cleanup_failed",
                    exc,
                    include_summary=False,
                    level=logging.WARNING,
                )

    asset.asset_status = _DELETED_STATUS
    asset.deleted_at = utc_now()
    asset.deleted_by = caller.user_id
    asset.delete_reason = clean_reason
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.knowledge_asset_deleted.value,
        trace_id=trace_id,
        target_type="knowledge_asset",
        target_id=asset.id,
        before={"asset_status": previous_status},
        after={
            "asset_status": asset.asset_status,
            "scope": asset.scope,
            "zone": asset.zone,
            "confidentiality_level": asset.confidentiality_level,
        },
        extra={
            "reason": clean_reason,
            "revoked_grants": len(grants),
            "cancelled_requests": len(requests),
            "weknora_delete_attempted": weknora_attempted,
            "weknora_delete_succeeded": weknora_succeeded,
        },
        project_id=asset.project_id,
    )
    await session.commit()
    return KnowledgeDeleteResponse(
        asset_id=asset.id,
        asset_status=asset.asset_status,
        deleted_at=asset.deleted_at,
        trace_id=trace_id,
    )
