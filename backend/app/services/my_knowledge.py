"""个人知识写动作服务。

三类写动作：
- confirm_asset：本人个人知识 material → asset（仅 owner 本人；幂等）。
- submit_to_project：个人知识提交进项目资料区，建 submission + personal_to_project review_task。
- register_validation_candidate：内部分享 / 客户验证候选，建 validation_evidence + submission +
  review_task。系统**只登记**用户声明的证据线索，不证明分享 / 客户验证真实发生。

权限：仅 `owner_user_id == caller.user_id` 且 `scope=personal` 的资产可操作；他人个人知识 /
纯 admin 一律 404 `personal_asset_not_owned`（不泄露存在）。提交到项目需调用人为目标项目
active 成员或治理角色（boss / 咨询总监，提交本人个人知识）。审核仍由项目经理人工确认。

安全：响应 / 审计绝不含原文 / 摘要全文 / storage_ref / source_file_ref / WeKnora id /
token / 真实附件 URL / provider 内部标识。
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Project
from app.models.knowledge import KnowledgeAsset
from app.models.review import (
    PersonalKnowledgeSubmission,
    ReviewTask,
    ReviewTaskEvidence,
    ValidationEvidence,
)
from app.schemas.enums import (
    AuditAction,
    AuditLogType,
    EvidenceType,
    KnowledgeScope,
    PersonalSubmissionStatus,
    PersonalSubmissionType,
    ProjectStatus,
    ReviewTaskStatus,
    ReviewType,
)
from app.schemas.my_knowledge import (
    ConfirmAssetResponse,
    PersonalKnowledgeSubmissionOut,
    SubmitToProjectRequest,
    ValidationCandidateRequest,
)
from app.schemas.permission import CallerContext
from app.services import audit as audit_service
from app.services import review as review_service


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"denied_reason": reason, "message": message}
    )


async def _load_owned_personal_asset(
    session: AsyncSession, caller: CallerContext, asset_id: uuid.UUID
) -> KnowledgeAsset:
    """加载本人个人知识资产。非本人 / 非 personal / 纯 admin 一律 404，不泄露存在。"""
    not_owned = _denied(404, "personal_asset_not_owned", "个人知识不存在或不可操作")
    if not caller.is_business_user:
        # admin 系统身份不作为业务个人知识库主体。
        raise not_owned
    asset = (
        await session.execute(select(KnowledgeAsset).where(KnowledgeAsset.id == asset_id))
    ).scalar_one_or_none()
    if asset is None:
        raise not_owned
    if asset.scope != KnowledgeScope.personal.value or asset.owner_user_id != caller.user_id:
        raise not_owned
    return asset


async def _load_target_project(session: AsyncSession, project_id: uuid.UUID) -> Project:
    project = (
        await session.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise _denied(404, "project_not_found", "目标项目不存在")
    if project.status != ProjectStatus.active.value:
        raise _denied(422, "project_not_active", "目标项目非进行中状态")
    return project


def _require_can_submit(caller: CallerContext, project: Project) -> None:
    """提交本人个人知识到项目：目标项目 active 成员，或治理角色（boss / 咨询总监）。

    治理角色（can_discover_l5）的提交权来自公司级知识治理身份，提交的是其本人个人知识；
    纯 admin 不在 is_business_user 内，已在 owner 校验阶段被 404 拦截，无法绕过。
    """
    if project.id in caller.active_project_ids:
        return
    if caller.can_discover_l5:
        return
    raise _denied(403, "project_membership_required", "需为目标项目 active 成员或治理角色")


async def _find_existing_submission(
    session: AsyncSession,
    caller: CallerContext,
    asset_id: uuid.UUID,
    project_id: uuid.UUID,
    submission_type: str,
    idempotency_key: str | None,
) -> PersonalKnowledgeSubmission | None:
    """幂等 / 防重复：先按 idempotency_key 命中，再对同组 pending 去重。"""
    base = select(PersonalKnowledgeSubmission).where(
        PersonalKnowledgeSubmission.submitter_user_id == caller.user_id,
        PersonalKnowledgeSubmission.source_asset_id == asset_id,
        PersonalKnowledgeSubmission.submission_type == submission_type,
        PersonalKnowledgeSubmission.target_project_id == project_id,
    )
    if idempotency_key:
        row = (
            (
                await session.execute(
                    base.where(PersonalKnowledgeSubmission.idempotency_key == idempotency_key)
                )
            )
            .scalars()
            .first()
        )
        if row is not None:
            return row
    # 无论是否带 key：同组已有 pending 则复用，避免刷出多个待审任务。
    return (
        (
            await session.execute(
                base.where(
                    PersonalKnowledgeSubmission.status == PersonalSubmissionStatus.pending.value
                )
            )
        )
        .scalars()
        .first()
    )


async def _submission_out(
    session: AsyncSession, sub: PersonalKnowledgeSubmission
) -> PersonalKnowledgeSubmissionOut:
    project_name = None
    if sub.target_project_id is not None:
        project_name = (
            (await session.execute(select(Project.name).where(Project.id == sub.target_project_id)))
            .scalars()
            .first()
        )
    if sub.submission_type == PersonalSubmissionType.submit_to_project.value:
        message = "已提交项目审核，待项目经理确认进入项目资料区"
    elif sub.submission_type == PersonalSubmissionType.internal_sharing_candidate.value:
        message = "内部分享候选已登记，待项目经理审核（系统不自动证明分享真实发生）"
    else:
        message = "客户验证候选已登记，待项目经理审核（系统不自动证明客户验证真实发生）"
    return PersonalKnowledgeSubmissionOut(
        submission_id=sub.id,
        asset_id=sub.source_asset_id,
        target_project_id=sub.target_project_id,
        target_project_name=project_name,
        submission_type=sub.submission_type,
        status=sub.status,
        review_task_id=sub.review_task_id,
        evidence_id=sub.evidence_id,
        created_at=sub.created_at,
        message=message,
        next_action="等待项目经理在 /review 审核确认",
    )


# ---------------------------------------------------------------------------
# 1) 本人资产确认（material → asset）
# ---------------------------------------------------------------------------
async def confirm_asset(
    session: AsyncSession, caller: CallerContext, asset_id: uuid.UUID, trace_id: str
) -> ConfirmAssetResponse:
    asset = await _load_owned_personal_asset(session, caller, asset_id)

    # 幂等：已是 asset → 原样返回，不报错、无副作用。
    if asset.zone == "asset":
        return ConfirmAssetResponse(
            asset_id=asset.id,
            zone="asset",
            status="already_asset",
            message="个人知识已是本人确认资产",
        )
    if asset.asset_status != "active":
        raise _denied(422, "asset_not_active", "仅 active 个人知识可确认为资产")

    before_zone = asset.zone
    asset.zone = "asset"
    await session.flush()
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.review_personal_asset_confirmed.value,
        trace_id=trace_id,
        target_type="knowledge_asset",
        target_id=asset.id,
        before={"zone": before_zone},
        after={"zone": asset.zone},
    )
    await session.commit()
    return ConfirmAssetResponse(
        asset_id=asset.id,
        zone="asset",
        status="confirmed",
        message="已确认为本人个人知识资产（仅本人可见，不自动进入项目或公司）",
    )


# ---------------------------------------------------------------------------
# 2) 提交到项目资料区
# ---------------------------------------------------------------------------
async def submit_to_project(
    session: AsyncSession,
    caller: CallerContext,
    asset_id: uuid.UUID,
    req: SubmitToProjectRequest,
    trace_id: str,
    idempotency_key: str | None,
) -> PersonalKnowledgeSubmissionOut:
    asset = await _load_owned_personal_asset(session, caller, asset_id)
    project = await _load_target_project(session, req.target_project_id)
    _require_can_submit(caller, project)

    stype = PersonalSubmissionType.submit_to_project.value
    existing = await _find_existing_submission(
        session, caller, asset.id, project.id, stype, idempotency_key
    )
    if existing is not None:
        return await _submission_out(session, existing)

    reviewer_id = await review_service._active_pm_of(session, project.id)
    task = ReviewTask(
        review_type=ReviewType.personal_to_project.value,
        trigger_source=stype,
        target_asset_id=asset.id,
        target_project_id=project.id,
        target_scope=KnowledgeScope.project.value,
        status=ReviewTaskStatus.pending_reviewer.value,
        reviewer_user_id=reviewer_id,
        submitted_by=caller.user_id,
    )
    session.add(task)
    await session.flush()

    sub = PersonalKnowledgeSubmission(
        submitter_user_id=caller.user_id,
        source_asset_id=asset.id,
        target_project_id=project.id,
        submission_type=stype,
        status=PersonalSubmissionStatus.pending.value,
        review_task_id=task.id,
        idempotency_key=idempotency_key,
        note=audit_service.sanitize_text(req.note),
    )
    session.add(sub)
    await session.flush()

    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.submission_created.value,
        trace_id=trace_id,
        target_type="personal_knowledge_submission",
        target_id=sub.id,
        after={"submission_type": stype, "status": sub.status},
        extra={
            "target_project_id": str(project.id),
            "submission_type": stype,
            "review_task_id": str(task.id),
            "source_asset_id": str(asset.id),
        },
        project_id=project.id,
    )
    await session.commit()
    return await _submission_out(session, sub)


# ---------------------------------------------------------------------------
# 3) 内部分享候选 / 客户验证候选（证据登记）
# ---------------------------------------------------------------------------
async def register_validation_candidate(
    session: AsyncSession,
    caller: CallerContext,
    asset_id: uuid.UUID,
    req: ValidationCandidateRequest,
    trace_id: str,
    idempotency_key: str | None,
) -> PersonalKnowledgeSubmissionOut:
    asset = await _load_owned_personal_asset(session, caller, asset_id)
    project = await _load_target_project(session, req.target_project_id)
    _require_can_submit(caller, project)
    review_service._validate_attachments(req.attachments)

    stype = (
        PersonalSubmissionType.internal_sharing_candidate.value
        if req.evidence_type == EvidenceType.internal_sharing
        else PersonalSubmissionType.client_validation_candidate.value
    )
    existing = await _find_existing_submission(
        session, caller, asset.id, project.id, stype, idempotency_key
    )
    if existing is not None:
        return await _submission_out(session, existing)

    evidence = ValidationEvidence(
        evidence_type=req.evidence_type.value,
        evidence_category=req.evidence_category.value,
        related_asset_id=asset.id,
        project_id=project.id,
        submitted_by=caller.user_id,
        description=audit_service.sanitize_text(req.description),
        attachments=req.attachments,
    )
    session.add(evidence)
    await session.flush()

    reviewer_id = await review_service._active_pm_of(session, project.id)
    task = ReviewTask(
        review_type=ReviewType.personal_to_project.value,
        trigger_source=stype,
        target_asset_id=asset.id,
        target_project_id=project.id,
        target_scope=KnowledgeScope.project.value,
        status=ReviewTaskStatus.pending_reviewer.value,
        reviewer_user_id=reviewer_id,
        submitted_by=caller.user_id,
    )
    session.add(task)
    await session.flush()
    session.add(ReviewTaskEvidence(review_task_id=task.id, evidence_id=evidence.id))

    sub = PersonalKnowledgeSubmission(
        submitter_user_id=caller.user_id,
        source_asset_id=asset.id,
        target_project_id=project.id,
        submission_type=stype,
        status=PersonalSubmissionStatus.pending.value,
        review_task_id=task.id,
        evidence_id=evidence.id,
        idempotency_key=idempotency_key,
        note=audit_service.sanitize_text(req.note),
    )
    session.add(sub)
    await session.flush()

    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.evidence_validation_registered.value,
        trace_id=trace_id,
        target_type="validation_evidence",
        target_id=evidence.id,
        after={
            "evidence_type": evidence.evidence_type,
            "evidence_category": evidence.evidence_category,
        },
        extra={
            "target_project_id": str(project.id),
            "submission_type": stype,
            "review_task_id": str(task.id),
            "submission_id": str(sub.id),
        },
        project_id=project.id,
    )
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.submission_created.value,
        trace_id=trace_id,
        target_type="personal_knowledge_submission",
        target_id=sub.id,
        after={"submission_type": stype, "status": sub.status},
        extra={"target_project_id": str(project.id), "evidence_id": str(evidence.id)},
        project_id=project.id,
    )
    await session.commit()
    return await _submission_out(session, sub)
