"""Company-upgrade review creation, preview, and dual-role approval commands."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetVersion,
)
from app.models.review import (
    CompanyAssetReviewDecision,
    ReviewTask,
)
from app.schemas.enums import (
    AuditAction,
    AuditLogType,
    CompanyAssetDecision,
    CompanyRole,
    KnowledgeScope,
    ReviewTaskStatus,
    ReviewType,
)
from app.schemas.naming import NamingPreviewResponse
from app.schemas.permission import CallerContext
from app.schemas.review import (
    CompanyUpgradeRequest,
    ReviewActionResponse,
    ReviewListItem,
)
from app.services import audit as audit_service
from app.services import governance_policy
from app.services.review_events import publish_action_required as _publish_review_action_required
from app.services.review_events import publish_decided as _publish_review_decided
from app.services.review_evidence_workflow import _load_project_asset
from app.services.review_queries import decision_states as _decision_states
from app.services.review_queries import display_maps as _aux_maps
from app.services.review_queries import load_task as _load_task
from app.services.review_support import (
    _NON_TERMINAL,
    _copy_publication_asset,
    _denied,
    _render_locked_publication,
    _render_publication_snapshot,
    _to_list_item,
)
from app.services.review_transitions import decide as apply_review_decision
from app.worker.enqueue import enqueue_outbox_delivery


async def create_or_get_company_upgrade(
    session: AsyncSession,
    caller: CallerContext,
    project_id: uuid.UUID,
    asset_id: uuid.UUID,
    req: CompanyUpgradeRequest,
    trace_id: str,
) -> ReviewListItem:
    """项目经理发起项目资产升格；创建后等待两个公司治理角色分别确认。"""
    if not caller.is_business_user:
        await audit_service.record_denied(
            session,
            caller=caller,
            log_type=AuditLogType.exception,
            action=AuditAction.admin_business_denied.value,
            trace_id=trace_id,
            target_type="knowledge_asset",
            target_id=asset_id,
            extra={
                "denied_reason": "admin_business_permission_denied",
                "attempted": "review.company_upgrade.create",
            },
        )
        raise _denied(403, "admin_business_permission_denied", "admin 不可发起公司资产升格")
    if not governance_policy.is_project_manager(caller, project_id):
        raise _denied(403, "project_manager_required", "仅目标项目经理可发起公司资产升格")
    asset = await _load_project_asset(session, project_id, asset_id)
    if asset.zone != "asset" or asset.asset_status != "active":
        raise _denied(422, "project_asset_required", "仅 active 项目资产可升格为公司资产")

    existing = (
        (
            await session.execute(
                select(ReviewTask)
                .where(
                    ReviewTask.target_asset_id == asset_id,
                    ReviewTask.review_type == ReviewType.project_to_company.value,
                    ReviewTask.status.in_(list(_NON_TERMINAL)),
                )
                .options(selectinload(ReviewTask.evidence_links))
            )
        )
        .scalars()
        .first()
    )
    if existing is not None:
        assets, projects = await _aux_maps(session, [existing])
        states = (await _decision_states(session, [existing])).get(existing.id, {})
        return _to_list_item(existing, assets, projects, decision_states=states)

    publication_snapshot, _rendered = await _render_publication_snapshot(
        session,
        caller,
        asset,
        target_scope=KnowledgeScope.company,
        target_project_id=None,
        confidentiality_level=req.confidentiality_level,
        naming=req.naming,
    )
    task = ReviewTask(
        review_type=ReviewType.project_to_company.value,
        trigger_source="project_manager_upgrade",
        target_asset_id=asset.id,
        target_project_id=project_id,
        target_scope=KnowledgeScope.company.value,
        confirmation_snapshot=publication_snapshot,
        status=ReviewTaskStatus.pending_reviewer.value,
        reviewer_user_id=None,
        submitted_by=caller.user_id,
    )
    session.add(task)
    await session.flush()
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.review_created.value,
        trace_id=trace_id,
        target_type="review_task",
        target_id=task.id,
        after={
            "review_type": task.review_type,
            "status": task.status,
            "target_asset_id": str(asset.id),
            "required_confirmations": [
                CompanyRole.boss.value,
                CompanyRole.consulting_director.value,
            ],
        },
        project_id=project_id,
    )
    await _publish_review_action_required(session, task)
    await session.commit()
    await enqueue_outbox_delivery(session)
    task = await _load_task(session, task.id)
    assets, projects = await _aux_maps(session, [task])
    return _to_list_item(task, assets, projects)


async def preview_company_upgrade(
    session: AsyncSession,
    caller: CallerContext,
    project_id: uuid.UUID,
    asset_id: uuid.UUID,
    req: CompanyUpgradeRequest,
) -> NamingPreviewResponse:
    if not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "admin 不可发起公司资产升格")
    if not governance_policy.is_project_manager(caller, project_id):
        raise _denied(403, "project_manager_required", "仅目标项目经理可发起公司资产升格")
    asset = await _load_project_asset(session, project_id, asset_id)
    if asset.zone != "asset" or asset.asset_status != "active":
        raise _denied(422, "project_asset_required", "仅 active 项目资产可升格为公司资产")
    _snapshot, rendered = await _render_publication_snapshot(
        session,
        caller,
        asset,
        target_scope=KnowledgeScope.company,
        target_project_id=None,
        confidentiality_level=req.confidentiality_level,
        naming=req.naming,
    )
    return NamingPreviewResponse(
        required=True,
        canonical_name=rendered.canonical_name,
        rule_version=rendered.rule_version,
        fields=rendered.metadata,
        notices=rendered.notices,
    )


def _select_company_confirmation_role(
    caller: CallerContext,
    states: dict[str, CompanyAssetReviewDecision],
) -> str | None:
    for role in (CompanyRole.boss.value, CompanyRole.consulting_director.value):
        if role not in caller.active_company_roles:
            continue
        current = states.get(role)
        if current is not None and current.decision == CompanyAssetDecision.confirmed.value:
            continue
        other_role = (
            CompanyRole.consulting_director.value
            if role == CompanyRole.boss.value
            else CompanyRole.boss.value
        )
        other = states.get(other_role)
        if (
            other is not None
            and other.decision == CompanyAssetDecision.confirmed.value
            and other.actor_user_id == caller.user_id
        ):
            continue
        return role
    return None


async def _approve_company_upgrade(
    session: AsyncSession,
    caller: CallerContext,
    task: ReviewTask,
    comment: str | None,
    trace_id: str,
    *,
    storage,
    weknora,
) -> ReviewActionResponse:
    if task.status != ReviewTaskStatus.pending_reviewer.value:
        raise _denied(409, "review_already_finalized", "审核任务当前不可确认")
    states = (await _decision_states(session, [task])).get(task.id, {})
    role = _select_company_confirmation_role(caller, states)
    if role is None:
        raise _denied(
            403,
            "company_confirmation_role_required",
            "当前身份没有可提交的公司资产确认席位",
        )
    decision = CompanyAssetReviewDecision(
        review_task_id=task.id,
        required_role=role,
        decision=CompanyAssetDecision.confirmed.value,
        actor_user_id=caller.user_id,
        comment=comment,
    )
    session.add(decision)
    await session.flush()
    states[role] = decision

    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.review_company_confirmation_recorded.value,
        trace_id=trace_id,
        target_type="review_task",
        target_id=task.id,
        after={"required_role": role, "decision": decision.decision},
        project_id=task.target_project_id,
    )

    general = states.get(CompanyRole.boss.value)
    director = states.get(CompanyRole.consulting_director.value)
    complete = bool(
        general
        and director
        and general.decision == CompanyAssetDecision.confirmed.value
        and director.decision == CompanyAssetDecision.confirmed.value
        and general.actor_user_id != director.actor_user_id
    )
    asset = (
        await session.execute(
            select(KnowledgeAsset)
            .where(KnowledgeAsset.id == task.target_asset_id)
            .with_for_update()
        )
    ).scalar_one()
    if complete:
        rendered = await _render_locked_publication(session, caller, asset, task)
        target_asset = await _copy_publication_asset(
            session,
            source=asset,
            target_scope=KnowledgeScope.company.value,
            target_project_id=None,
            actor_user_id=caller.user_id,
            confidentiality_level=str((task.confirmation_snapshot or {})["confidentiality_level"]),
            rendered=rendered,
        )
        apply_review_decision(
            task,
            target_status=ReviewTaskStatus.approved.value,
            comment=comment,
            decided_at=datetime.now(timezone.utc),
        )
        task.target_asset_id = target_asset.id
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.review_approved.value,
            trace_id=trace_id,
            target_type="review_task",
            target_id=task.id,
            after={"status": task.status, "review_type": task.review_type},
            project_id=task.target_project_id,
        )
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.asset_published.value,
            trace_id=trace_id,
            target_type="knowledge_asset",
            target_id=target_asset.id,
            before={"source_scope": asset.scope, "source_project_id": str(asset.project_id)},
            after={
                "target_scope": target_asset.scope,
                "target_asset_id": str(target_asset.id),
                "naming_rule_version": rendered.rule_version,
                "directory_key": rendered.metadata["directory_key"],
            },
            extra={
                "review_id": str(task.id),
                "source_asset_id": str(asset.id),
                "operator_id": str(caller.user_id),
            },
            project_id=task.target_project_id,
        )
        asset = target_asset
    response_review_id = task.id
    response_review_status = task.status
    response_asset_id = asset.id
    response_asset_zone = asset.zone
    response_asset_scope = asset.scope
    response_project_id = asset.project_id
    if complete:
        await _publish_review_decided(session, task)
    await session.commit()
    if complete:
        await enqueue_outbox_delivery(session)
    if complete:
        from app.services import indexing_ops

        try:
            await indexing_ops.create_publication_index_job(
                session,
                caller,
                response_asset_id,
                scope=response_asset_scope,
                project_id=response_project_id,
                weknora=weknora,
                storage=storage,
                trace_id=trace_id,
            )
        except Exception:
            # Publication is already committed. Queue failure is represented on the
            # preserved derivative and remains retryable from its detail page.
            await session.rollback()
    version = await session.scalar(
        select(KnowledgeAssetVersion).where(
            KnowledgeAssetVersion.asset_id == response_asset_id,
            KnowledgeAssetVersion.version_status == "active",
        )
    )
    return ReviewActionResponse(
        review_id=response_review_id,
        status=response_review_status,
        target_asset_id=response_asset_id,
        asset_zone=response_asset_zone,
        index_status=version.index_status if version is not None else None,
    )
