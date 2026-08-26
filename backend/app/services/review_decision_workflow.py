"""Review decision side-effect orchestration over explicit transition services."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingest import IngestTask
from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetVersion,
)
from app.models.review import (
    CompanyAssetReviewDecision,
    PersonalKnowledgeSubmission,
    ReviewTask,
)
from app.schemas.enums import (
    AlertSeverity,
    AuditAction,
    AuditLogType,
    AuditRiskLevel,
    CompanyAssetDecision,
    KnowledgeScope,
    PersonalSubmissionStatus,
    PersonalSubmissionType,
    ReviewTaskStatus,
    ReviewType,
)
from app.schemas.permission import CallerContext
from app.schemas.review import (
    ReviewActionResponse,
)
from app.services import audit as audit_service
from app.services.review_company_workflow import (
    _approve_company_upgrade,
    _select_company_confirmation_role,
)
from app.services.review_events import publish_decided as _publish_review_decided
from app.services.review_queries import decision_states as _decision_states
from app.services.review_queries import load_task as _load_task
from app.services.review_support import (
    _TERMINAL,
    _can_decide_project_ingest,
    _copy_publication_asset,
    _denied,
    _render_locked_publication,
)
from app.services.review_transitions import decide as apply_review_decision
from app.worker.enqueue import enqueue_outbox_delivery


async def approve(
    session: AsyncSession,
    caller: CallerContext,
    review_id: uuid.UUID,
    comment: str | None,
    trace_id: str,
    *,
    storage,
    weknora,
) -> ReviewActionResponse:
    if not caller.is_business_user:
        await audit_service.record_denied(
            session,
            caller=caller,
            log_type=AuditLogType.exception,
            action=AuditAction.admin_business_denied.value,
            trace_id=trace_id,
            target_type="review_task",
            target_id=review_id,
            severity=AlertSeverity.warning,
            risk_level=AuditRiskLevel.high.value,
            extra={
                "denied_reason": "admin_business_permission_denied",
                "attempted": "review.approve",
            },
        )
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可审批")
    task = await _load_task(session, review_id, for_update=True)
    if task.review_type == ReviewType.project_to_company.value:
        return await _approve_company_upgrade(
            session,
            caller,
            task,
            comment,
            trace_id,
            storage=storage,
            weknora=weknora,
        )
    if task.review_type == ReviewType.project_ingest_approval.value:
        target_project_id = task.target_project_id
        if not _can_decide_project_ingest(caller, task):
            await audit_service.record_denied(
                session,
                caller=caller,
                log_type=AuditLogType.exception,
                action=AuditAction.review_approved.value,
                trace_id=trace_id,
                target_type="review_task",
                target_id=review_id,
                extra={
                    "denied_reason": "project_ingest_review_forbidden",
                    "attempted": "review.approve",
                },
                project_id=target_project_id,
            )
            raise _denied(403, "project_ingest_review_forbidden", "仅目标项目经理可审批")
        claim = await session.execute(
            update(ReviewTask)
            .where(
                ReviewTask.id == review_id,
                ReviewTask.status.in_(
                    (
                        ReviewTaskStatus.pending_reviewer.value,
                        ReviewTaskStatus.approval_failed.value,
                    )
                ),
            )
            .values(status=ReviewTaskStatus.approving.value)
            .execution_options(synchronize_session=False)
        )
        if getattr(claim, "rowcount", 0) != 1:
            await session.rollback()
            await audit_service.record_denied(
                session,
                caller=caller,
                log_type=AuditLogType.exception,
                action=AuditAction.review_approved.value,
                trace_id=trace_id,
                target_type="review_task",
                target_id=review_id,
                extra={
                    "denied_reason": "review_decision_conflict",
                    "attempted": "review.approve",
                },
                project_id=target_project_id,
            )
            raise _denied(409, "review_already_finalized", "审核任务不可重复操作")
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.review_approval_started.value,
            trace_id=trace_id,
            target_type="review_task",
            target_id=review_id,
            after={"status": ReviewTaskStatus.approving.value},
            project_id=target_project_id,
        )
        await session.commit()
        task = await _load_task(session, review_id)
        from app.services.workflows import project_ingest_approval

        return await project_ingest_approval.execute(
            session,
            caller,
            task,
            comment,
            trace_id,
            storage=storage,
            weknora=weknora,
        )
    if task.review_type == ReviewType.personal_to_project.value:
        if task.reviewer_user_id != caller.user_id:
            raise _denied(403, "review_action_forbidden", "只有被分配的审核人可审批")
        if task.status in _TERMINAL:
            raise _denied(409, "review_already_finalized", "审核任务已是终态，不可重复操作")
        submission = (
            await session.execute(
                select(PersonalKnowledgeSubmission).where(
                    PersonalKnowledgeSubmission.review_task_id == task.id
                )
            )
        ).scalar_one_or_none()
        if submission is None:
            raise _denied(409, "personal_submission_missing", "个人知识提交记录不可用")
        result_asset = (
            await session.execute(
                select(KnowledgeAsset)
                .where(KnowledgeAsset.id == submission.source_asset_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if result_asset is None:
            raise _denied(409, "publication_source_missing", "来源个人资料已不存在，无法发布")
        if (
            submission.submission_type == PersonalSubmissionType.submit_to_project.value
            and task.target_project_id is not None
        ):
            source = result_asset
            rendered = await _render_locked_publication(session, caller, source, task)
            result_asset = await _copy_publication_asset(
                session,
                source=source,
                target_scope=KnowledgeScope.project.value,
                target_project_id=task.target_project_id,
                actor_user_id=caller.user_id,
                confidentiality_level=str(
                    (task.confirmation_snapshot or {})["confidentiality_level"]
                ),
                rendered=rendered,
            )
            task.target_asset_id = result_asset.id
            await audit_service.record_event(
                session,
                caller=caller,
                log_type=AuditLogType.operation,
                action=AuditAction.asset_published.value,
                trace_id=trace_id,
                target_type="knowledge_asset",
                target_id=result_asset.id,
                before={
                    "source_scope": source.scope,
                    "source_project_id": None,
                },
                after={
                    "target_scope": result_asset.scope,
                    "target_project_id": str(result_asset.project_id),
                    "target_asset_id": str(result_asset.id),
                    "naming_rule_version": rendered.rule_version,
                    "directory_key": rendered.metadata["directory_key"],
                },
                extra={
                    "review_id": str(task.id),
                    "source_asset_id": str(source.id),
                    "operator_id": str(caller.user_id),
                },
                project_id=task.target_project_id,
            )
        task.status = ReviewTaskStatus.approved.value
        task.review_comment = comment
        task.reviewed_at = datetime.now(timezone.utc)
        submission.status = PersonalSubmissionStatus.approved.value
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.review_approved.value,
            trace_id=trace_id,
            target_type="review_task",
            target_id=task.id,
            after={
                "status": task.status,
                "submission_type": submission.submission_type,
            },
            project_id=task.target_project_id,
        )
        should_index_publication = bool(
            submission.submission_type == PersonalSubmissionType.submit_to_project.value
            and task.target_project_id is not None
        )
        response_review_id = task.id
        response_review_status = task.status
        response_asset_id = result_asset.id
        response_asset_zone = result_asset.zone
        response_asset_scope = result_asset.scope
        response_project_id = result_asset.project_id
        await _publish_review_decided(session, task)
        await session.commit()
        await enqueue_outbox_delivery(session)
        if should_index_publication:
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
                # The target copy remains published; its safe failure status exposes retry.
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
    if task.reviewer_user_id != caller.user_id:
        raise _denied(403, "review_action_forbidden", "只有被分配的审核人可审批")
    if task.status in _TERMINAL:
        raise _denied(409, "review_already_finalized", "审核任务已是终态，不可重复操作")
    if len(task.evidence_links) < 1:
        raise _denied(422, "review_evidence_required", "material_to_asset 审核需至少一条证据")

    asset = (
        await session.execute(
            select(KnowledgeAsset).where(KnowledgeAsset.id == task.target_asset_id)
        )
    ).scalar_one()
    apply_review_decision(
        task,
        target_status=ReviewTaskStatus.approved.value,
        comment=comment,
        decided_at=datetime.now(timezone.utc),
    )
    before_zone = asset.zone
    asset.zone = "asset"  # material → asset

    # 审批通过审计 + 资产化 zone 变更审计（trace_id 串联"证据—审核—确认"链）。
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.review_approved.value,
        trace_id=trace_id,
        target_type="review_task",
        target_id=task.id,
        after={"status": task.status, "target_asset_id": str(asset.id)},
        project_id=task.target_project_id,
    )
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.asset_zone_changed.value,
        trace_id=trace_id,
        target_type="knowledge_asset",
        target_id=asset.id,
        before={"zone": before_zone},
        after={"zone": asset.zone},
        extra={"review_id": str(task.id), "confidentiality_level": asset.confidentiality_level},
        project_id=task.target_project_id,
    )
    await _publish_review_decided(session, task)
    await session.commit()
    await enqueue_outbox_delivery(session)
    return ReviewActionResponse(
        review_id=task.id, status=task.status, target_asset_id=asset.id, asset_zone=asset.zone
    )


async def reject(
    session: AsyncSession,
    caller: CallerContext,
    review_id: uuid.UUID,
    comment: str,
    trace_id: str,
) -> ReviewActionResponse:
    if not caller.is_business_user:
        await audit_service.record_denied(
            session,
            caller=caller,
            log_type=AuditLogType.exception,
            action=AuditAction.admin_business_denied.value,
            trace_id=trace_id,
            target_type="review_task",
            target_id=review_id,
            severity=AlertSeverity.warning,
            risk_level=AuditRiskLevel.high.value,
            extra={
                "denied_reason": "admin_business_permission_denied",
                "attempted": "review.reject",
            },
        )
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可审批")
    task = await _load_task(session, review_id, for_update=True)
    if task.review_type == ReviewType.project_to_company.value:
        if task.status != ReviewTaskStatus.pending_reviewer.value:
            raise _denied(409, "review_already_finalized", "审核任务当前不可拒绝")
        states = (await _decision_states(session, [task])).get(task.id, {})
        role = _select_company_confirmation_role(caller, states)
        if role is None:
            raise _denied(
                403,
                "company_confirmation_role_required",
                "当前身份没有可提交的公司资产确认席位",
            )
        session.add(
            CompanyAssetReviewDecision(
                review_task_id=task.id,
                required_role=role,
                decision=CompanyAssetDecision.rejected.value,
                actor_user_id=caller.user_id,
                comment=comment,
            )
        )
        apply_review_decision(
            task,
            target_status=ReviewTaskStatus.rejected.value,
            comment=comment,
            decided_at=datetime.now(timezone.utc),
        )
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.review_rejected.value,
            trace_id=trace_id,
            target_type="review_task",
            target_id=task.id,
            after={
                "status": task.status,
                "review_type": task.review_type,
                "required_role": role,
            },
            project_id=task.target_project_id,
        )
        await _publish_review_decided(session, task)
        await session.commit()
        await enqueue_outbox_delivery(session)
        asset = await session.get(KnowledgeAsset, task.target_asset_id)
        return ReviewActionResponse(
            review_id=task.id,
            status=task.status,
            target_asset_id=task.target_asset_id,
            asset_zone=asset.zone if asset is not None else None,
        )
    if task.review_type == ReviewType.project_ingest_approval.value:
        target_project_id = task.target_project_id
        if not _can_decide_project_ingest(caller, task):
            await audit_service.record_denied(
                session,
                caller=caller,
                log_type=AuditLogType.exception,
                action=AuditAction.review_rejected.value,
                trace_id=trace_id,
                target_type="review_task",
                target_id=review_id,
                extra={
                    "denied_reason": "project_ingest_review_forbidden",
                    "attempted": "review.reject",
                },
                project_id=target_project_id,
            )
            raise _denied(403, "project_ingest_review_forbidden", "仅目标项目经理可审批")
        claim = await session.execute(
            update(ReviewTask)
            .where(
                ReviewTask.id == review_id,
                ReviewTask.status.in_(
                    (
                        ReviewTaskStatus.pending_reviewer.value,
                        ReviewTaskStatus.approval_failed.value,
                    )
                ),
            )
            .values(
                status=ReviewTaskStatus.rejected.value,
                review_comment=comment,
                reviewed_at=datetime.now(timezone.utc),
            )
            .execution_options(synchronize_session=False)
        )
        if getattr(claim, "rowcount", 0) != 1:
            await session.rollback()
            await audit_service.record_denied(
                session,
                caller=caller,
                log_type=AuditLogType.exception,
                action=AuditAction.review_rejected.value,
                trace_id=trace_id,
                target_type="review_task",
                target_id=review_id,
                extra={
                    "denied_reason": "review_decision_conflict",
                    "attempted": "review.reject",
                },
                project_id=target_project_id,
            )
            raise _denied(409, "review_already_finalized", "审核任务不可重复操作")
        apply_review_decision(
            task,
            target_status=ReviewTaskStatus.rejected.value,
            comment=comment,
            decided_at=datetime.now(timezone.utc),
        )
        if task.source_ingest_task_id is not None:
            ingest_task = await session.get(IngestTask, task.source_ingest_task_id)
            if ingest_task is not None:
                ingest_task.status = "rejected"
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.review_rejected.value,
            trace_id=trace_id,
            target_type="review_task",
            target_id=task.id,
            after={"status": task.status, "review_type": task.review_type},
            project_id=task.target_project_id,
        )
        await _publish_review_decided(session, task)
        await session.commit()
        await enqueue_outbox_delivery(session)
        return ReviewActionResponse(
            review_id=task.id,
            status=task.status,
            target_asset_id=task.target_asset_id,
            asset_zone=None,
        )
    if task.review_type == ReviewType.personal_to_project.value:
        if task.reviewer_user_id != caller.user_id:
            raise _denied(403, "review_action_forbidden", "只有被分配的审核人可审批")
        if task.status in _TERMINAL:
            raise _denied(409, "review_already_finalized", "审核任务已是终态，不可重复操作")
        submission = (
            await session.execute(
                select(PersonalKnowledgeSubmission).where(
                    PersonalKnowledgeSubmission.review_task_id == task.id
                )
            )
        ).scalar_one_or_none()
        if submission is None:
            raise _denied(409, "personal_submission_missing", "个人知识提交记录不可用")
        task.status = ReviewTaskStatus.rejected.value
        task.review_comment = comment
        task.reviewed_at = datetime.now(timezone.utc)
        submission.status = PersonalSubmissionStatus.rejected.value
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.review_rejected.value,
            trace_id=trace_id,
            target_type="review_task",
            target_id=task.id,
            after={
                "status": task.status,
                "submission_type": submission.submission_type,
            },
            project_id=task.target_project_id,
        )
        await _publish_review_decided(session, task)
        await session.commit()
        await enqueue_outbox_delivery(session)
        asset = await session.get(KnowledgeAsset, task.target_asset_id)
        return ReviewActionResponse(
            review_id=task.id,
            status=task.status,
            target_asset_id=task.target_asset_id,
            asset_zone=asset.zone if asset else None,
        )
    if task.reviewer_user_id != caller.user_id:
        raise _denied(403, "review_action_forbidden", "只有被分配的审核人可审批")
    if task.status in _TERMINAL:
        raise _denied(409, "review_already_finalized", "审核任务已是终态，不可重复操作")

    apply_review_decision(
        task,
        target_status=ReviewTaskStatus.rejected.value,
        comment=comment,
        decided_at=datetime.now(timezone.utc),
    )
    # 不改变 asset.zone。
    asset_zone = (
        await session.execute(
            select(KnowledgeAsset.zone).where(KnowledgeAsset.id == task.target_asset_id)
        )
    ).scalar_one()

    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.review_rejected.value,
        trace_id=trace_id,
        target_type="review_task",
        target_id=task.id,
        after={"status": task.status, "target_asset_id": str(task.target_asset_id)},
        project_id=task.target_project_id,
    )
    await _publish_review_decided(session, task)
    await session.commit()
    await enqueue_outbox_delivery(session)
    return ReviewActionResponse(
        review_id=task.id,
        status=task.status,
        target_asset_id=task.target_asset_id,
        asset_zone=asset_zone,
    )


async def withdraw_company_confirmation(
    session: AsyncSession,
    caller: CallerContext,
    review_id: uuid.UUID,
    comment: str | None,
    trace_id: str,
) -> ReviewActionResponse:
    if not caller.is_business_user:
        await audit_service.record_denied(
            session,
            caller=caller,
            log_type=AuditLogType.exception,
            action=AuditAction.admin_business_denied.value,
            trace_id=trace_id,
            target_type="review_task",
            target_id=review_id,
            extra={
                "denied_reason": "admin_business_permission_denied",
                "attempted": "review.company_confirmation.withdraw",
            },
        )
        raise _denied(403, "admin_business_permission_denied", "admin 不可撤回业务确认")
    task = await _load_task(session, review_id, for_update=True)
    if task.review_type != ReviewType.project_to_company.value:
        raise _denied(422, "withdraw_not_supported", "该审核类型不支持撤回确认")
    if task.status != ReviewTaskStatus.pending_reviewer.value:
        raise _denied(409, "review_already_finalized", "已完成或已拒绝的升格不可撤回")
    states = (await _decision_states(session, [task])).get(task.id, {})
    owned = next(
        (
            row
            for row in states.values()
            if row.decision == CompanyAssetDecision.confirmed.value
            and row.actor_user_id == caller.user_id
            and row.required_role in caller.active_company_roles
        ),
        None,
    )
    if owned is None:
        raise _denied(403, "confirmation_withdraw_forbidden", "只能撤回本人当前有效的确认")
    session.add(
        CompanyAssetReviewDecision(
            review_task_id=task.id,
            required_role=owned.required_role,
            decision=CompanyAssetDecision.withdrawn.value,
            actor_user_id=caller.user_id,
            comment=comment,
        )
    )
    apply_review_decision(
        task,
        target_status=ReviewTaskStatus.rejected.value,
        comment=comment,
        decided_at=datetime.now(timezone.utc),
    )
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.review_company_confirmation_withdrawn.value,
        trace_id=trace_id,
        target_type="review_task",
        target_id=task.id,
        after={
            "required_role": owned.required_role,
            "decision": "withdrawn",
            "status": task.status,
        },
        project_id=task.target_project_id,
    )
    await _publish_review_decided(session, task)
    await session.commit()
    await enqueue_outbox_delivery(session)
    asset = await session.get(KnowledgeAsset, task.target_asset_id)
    return ReviewActionResponse(
        review_id=task.id,
        status=task.status,
        target_asset_id=task.target_asset_id,
        asset_zone=asset.zone if asset is not None else None,
    )


async def withdraw_review(
    session: AsyncSession,
    caller: CallerContext,
    review_id: uuid.UUID,
    comment: str | None,
    trace_id: str,
) -> ReviewActionResponse:
    task = await _load_task(session, review_id, for_update=True)
    if task.review_type == ReviewType.project_to_company.value:
        # Release this lock before the established function reloads it.
        await session.rollback()
        return await withdraw_company_confirmation(session, caller, review_id, comment, trace_id)
    if not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可撤回本人任务")
    if task.review_type != ReviewType.material_to_asset.value:
        raise _denied(422, "withdraw_not_supported", "该审核类型不支持撤回")
    if task.submitted_by != caller.user_id:
        raise _denied(403, "review_withdraw_forbidden", "只能撤回本人发起的任务")
    if task.status not in {
        ReviewTaskStatus.pending_evidence.value,
        ReviewTaskStatus.pending_reviewer.value,
    }:
        raise _denied(409, "review_already_decided", "任务已进入处理或终态，不能撤回")
    apply_review_decision(
        task,
        target_status=ReviewTaskStatus.rejected.value,
        comment=(comment or "发起人撤回").strip(),
        decided_at=datetime.now(timezone.utc),
    )
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.review_withdrawn.value,
        trace_id=trace_id,
        target_type="review_task",
        target_id=task.id,
        after={"status": task.status, "withdrawn_by_submitter": True},
        project_id=task.target_project_id,
    )
    await _publish_review_decided(session, task)
    await session.commit()
    await enqueue_outbox_delivery(session)
    asset = await session.get(KnowledgeAsset, task.target_asset_id)
    return ReviewActionResponse(
        review_id=task.id,
        status=task.status,
        target_asset_id=task.target_asset_id,
        asset_zone=asset.zone if asset else None,
    )
