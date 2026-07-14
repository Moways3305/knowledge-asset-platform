"""审核流服务。

闭环：项目 material 资产 → 登记验证证据 → 创建/进入 ReviewTask → PM approve →
KnowledgeAsset.zone = asset。approve/reject 不写 audit_events、
不通知、不调用 Agent、不发布公司库、不创建 access grant。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.identity import Project, ProjectMember
from app.models.ingest import IngestTask
from app.models.knowledge import KnowledgeAsset
from app.models.review import ReviewTask, ReviewTaskEvidence, ValidationEvidence
from app.schemas.enums import (
    AlertSeverity,
    AuditAction,
    AuditLogType,
    AuditRiskLevel,
    KnowledgeScope,
    MemberStatus,
    ProjectRole,
    ReviewTaskStatus,
    ReviewType,
)
from app.schemas.ingest import IngestConfirmRequest
from app.schemas.permission import CallerContext
from app.schemas.review import (
    EvidenceCreateRequest,
    EvidenceOut,
    ReviewActionResponse,
    ReviewDetail,
    ReviewListItem,
)
from app.services import audit as audit_service

_TERMINAL = {ReviewTaskStatus.approved.value, ReviewTaskStatus.rejected.value}
_NON_TERMINAL = {
    ReviewTaskStatus.pending_evidence.value,
    ReviewTaskStatus.pending_reviewer.value,
    ReviewTaskStatus.approving.value,
    ReviewTaskStatus.approval_failed.value,
}


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"denied_reason": reason, "message": message}
    )


def _is_admin(caller: CallerContext) -> bool:
    return "admin" in caller.active_company_roles


# 附件 metadata 黑名单：禁止携带真实 URL / 文件路径 / 内部存储引用 / 凭证。
_FORBIDDEN_ATTACHMENT_KEYS = {
    "url",
    "download_url",
    "file_url",
    "path",
    "storage_ref",
    "source_file_ref",
    "bucket",
    "object_key",
    "token",
}
_FORBIDDEN_VALUE_PREFIXES = (
    "http://",
    "https://",
    "file://",
    "s3://",
    "oss://",
    "internal://",
)


def _validate_attachments(attachments: list[dict] | None) -> None:
    """拒绝携带真实 URL / 路径 / 内部引用 / 凭证的附件 metadata（422）。"""
    if not attachments:
        return
    for item in attachments:
        for key, val in item.items():
            if str(key).lower() in _FORBIDDEN_ATTACHMENT_KEYS:
                raise _denied(
                    422,
                    "attachment_metadata_forbidden",
                    f"附件 metadata 不允许包含字段：{key}",
                )
            if isinstance(val, str):
                low = val.lower()
                if any(low.startswith(p) for p in _FORBIDDEN_VALUE_PREFIXES):
                    raise _denied(
                        422,
                        "attachment_metadata_forbidden",
                        "附件 metadata 不允许包含真实 URL / 路径 / 内部引用",
                    )


def _is_governance(caller: CallerContext) -> bool:
    return caller.can_discover_l5  # boss / consulting_director


async def _active_pm_of(session: AsyncSession, project_id: uuid.UUID) -> uuid.UUID | None:
    """返回该项目一名 active 的 project_manager 用户 id（无则 None）。"""
    return (
        (
            await session.execute(
                select(ProjectMember.user_id).where(
                    ProjectMember.project_id == project_id,
                    ProjectMember.project_role == ProjectRole.project_manager.value,
                    ProjectMember.status == MemberStatus.active.value,
                )
            )
        )
        .scalars()
        .first()
    )


async def _caller_is_pm_of(
    session: AsyncSession, caller: CallerContext, project_id: uuid.UUID | None
) -> bool:
    if project_id is None:
        return False
    pm = await _active_pm_of(session, project_id)
    # 简化：若调用人就是该项目的 active PM。
    row = (
        (
            await session.execute(
                select(ProjectMember.id).where(
                    ProjectMember.project_id == project_id,
                    ProjectMember.user_id == caller.user_id,
                    ProjectMember.project_role == ProjectRole.project_manager.value,
                    ProjectMember.status == MemberStatus.active.value,
                )
            )
        )
        .scalars()
        .first()
    )
    return row is not None or (pm is not None and pm == caller.user_id)


async def _load_task(
    session: AsyncSession, review_id: uuid.UUID, *, for_update: bool = False
) -> ReviewTask:
    stmt = (
        select(ReviewTask)
        .where(ReviewTask.id == review_id)
        .options(selectinload(ReviewTask.evidence_links))
    )
    if for_update:
        stmt = stmt.with_for_update()
    task = (await session.execute(stmt)).scalar_one_or_none()
    if task is None:
        raise _denied(404, "review_not_found", "审核任务不存在")
    return task


async def _aux_maps(session: AsyncSession, tasks: list[ReviewTask]):
    asset_ids = {t.target_asset_id for t in tasks if t.target_asset_id is not None}
    project_ids = {t.target_project_id for t in tasks if t.target_project_id}
    assets: dict[uuid.UUID, str] = {}
    projects: dict[uuid.UUID, str] = {}
    if asset_ids:
        rows = (
            await session.execute(
                select(KnowledgeAsset.id, KnowledgeAsset.title).where(
                    KnowledgeAsset.id.in_(asset_ids)
                )
            )
        ).all()
        assets = {r[0]: r[1] for r in rows}
    if project_ids:
        rows = (
            await session.execute(
                select(Project.id, Project.name).where(Project.id.in_(project_ids))
            )
        ).all()
        projects = {r[0]: r[1] for r in rows}
    return assets, projects


def _to_list_item(
    task: ReviewTask, assets, projects, *, can_decide: bool = False
) -> ReviewListItem:
    return ReviewListItem(
        id=task.id,
        review_type=task.review_type,
        trigger_source=task.trigger_source,
        status=task.status,
        target_asset_id=task.target_asset_id,
        asset_title=assets.get(task.target_asset_id)
        or (
            str(task.confirmation_snapshot.get("title"))
            if task.confirmation_snapshot and task.confirmation_snapshot.get("title")
            else None
        ),
        target_scope=task.target_scope,
        target_project_id=task.target_project_id,
        project_name=projects.get(task.target_project_id) if task.target_project_id else None,
        submitted_by=task.submitted_by,
        reviewer_user_id=task.reviewer_user_id,
        evidence_count=len(task.evidence_links),
        can_decide=can_decide,
        review_comment=task.review_comment,
        reviewed_at=task.reviewed_at,
        created_at=task.created_at,
    )


def _can_view(caller: CallerContext, task: ReviewTask, is_pm: bool) -> bool:
    return (
        task.submitted_by == caller.user_id
        or task.reviewer_user_id == caller.user_id
        or _is_governance(caller)
        or is_pm
    )


async def list_reviews(
    session: AsyncSession,
    caller: CallerContext,
    *,
    review_type: str | None = None,
    status: str | None = None,
) -> list[ReviewListItem]:
    if not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可查看审核队列")

    stmt = select(ReviewTask).options(selectinload(ReviewTask.evidence_links))
    if review_type:
        stmt = stmt.where(ReviewTask.review_type == review_type)
    if status:
        stmt = stmt.where(ReviewTask.status == status)
    tasks = list((await session.execute(stmt)).scalars().all())

    governance = _is_governance(caller)
    # 可见性：提交人 / 审核人 / 治理角色可见；治理角色可见全部。
    visible = []
    for task in tasks:
        is_project_pm = bool(
            task.target_project_id is not None
            and caller.active_project_roles.get(task.target_project_id)
            == ProjectRole.project_manager.value
        )
        if (
            governance
            or task.submitted_by == caller.user_id
            or task.reviewer_user_id == caller.user_id
            or is_project_pm
        ):
            visible.append(task)
    assets, projects = await _aux_maps(session, visible)
    return [
        _to_list_item(
            task,
            assets,
            projects,
            can_decide=(
                task.status
                in {
                    ReviewTaskStatus.pending_reviewer.value,
                    ReviewTaskStatus.approval_failed.value,
                }
                and (
                    (
                        task.review_type == ReviewType.project_ingest_approval.value
                        and _can_decide_project_ingest(caller, task)
                    )
                    or task.reviewer_user_id == caller.user_id
                )
            ),
        )
        for task in visible
    ]


async def get_review(
    session: AsyncSession, caller: CallerContext, review_id: uuid.UUID
) -> ReviewDetail:
    if not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可查看审核详情")
    task = await _load_task(session, review_id)
    is_pm = await _caller_is_pm_of(session, caller, task.target_project_id)
    if not _can_view(caller, task, is_pm):
        raise _denied(403, "review_view_forbidden", "无权查看该审核任务")

    assets, projects = await _aux_maps(session, [task])
    base = _to_list_item(
        task,
        assets,
        projects,
        can_decide=(
            task.status
            in {
                ReviewTaskStatus.pending_reviewer.value,
                ReviewTaskStatus.approval_failed.value,
            }
            and (
                (
                    task.review_type == ReviewType.project_ingest_approval.value
                    and _can_decide_project_ingest(caller, task)
                )
                or task.reviewer_user_id == caller.user_id
            )
        ),
    )

    evidence_ids = [link.evidence_id for link in task.evidence_links]
    evidences: list[EvidenceOut] = []
    if evidence_ids:
        rows = (
            (
                await session.execute(
                    select(ValidationEvidence).where(ValidationEvidence.id.in_(evidence_ids))
                )
            )
            .scalars()
            .all()
        )
        evidences = [
            EvidenceOut(
                id=e.id,
                evidence_type=e.evidence_type,
                evidence_category=e.evidence_category,
                description=e.description,
                submitted_by=e.submitted_by,
                created_at=e.created_at,
            )
            for e in rows
        ]
    return ReviewDetail(**base.model_dump(), evidences=evidences)


async def _load_project_asset(
    session: AsyncSession, project_id: uuid.UUID, asset_id: uuid.UUID
) -> KnowledgeAsset:
    asset = (
        await session.execute(select(KnowledgeAsset).where(KnowledgeAsset.id == asset_id))
    ).scalar_one_or_none()
    if asset is None:
        raise _denied(404, "knowledge_asset_not_found", "知识资产不存在")
    if asset.scope != KnowledgeScope.project.value or asset.project_id != project_id:
        raise _denied(422, "asset_not_in_project", "资产不属于该项目或不是项目知识")
    return asset


async def _find_open_material_review(
    session: AsyncSession, asset_id: uuid.UUID
) -> ReviewTask | None:
    return (
        (
            await session.execute(
                select(ReviewTask)
                .where(
                    ReviewTask.target_asset_id == asset_id,
                    ReviewTask.review_type == ReviewType.material_to_asset.value,
                    ReviewTask.status.in_(list(_NON_TERMINAL)),
                )
                .options(selectinload(ReviewTask.evidence_links))
            )
        )
        .scalars()
        .first()
    )


async def register_evidence(
    session: AsyncSession,
    caller: CallerContext,
    project_id: uuid.UUID,
    asset_id: uuid.UUID,
    req: EvidenceCreateRequest,
    trace_id: str,
) -> EvidenceOut:
    if not caller.is_business_user:
        await audit_service.record_denied(
            session,
            caller=caller,
            log_type=AuditLogType.exception,
            action=AuditAction.admin_business_denied.value,
            trace_id=trace_id,
            target_type="knowledge_asset",
            target_id=asset_id,
            severity=AlertSeverity.warning,
            risk_level=AuditRiskLevel.high.value,
            extra={
                "denied_reason": "admin_business_permission_denied",
                "attempted": "review.evidence",
            },
        )
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可登记证据")
    if project_id not in caller.active_project_ids:
        raise _denied(403, "project_membership_required", "需为该项目的有效成员")
    _validate_attachments(req.attachments)
    await _load_project_asset(session, project_id, asset_id)

    evidence = ValidationEvidence(
        evidence_type=req.evidence_type.value,
        evidence_category=req.evidence_category.value,
        related_asset_id=asset_id,
        project_id=project_id,
        submitted_by=caller.user_id,
        description=req.description,
        attachments=req.attachments,
    )
    session.add(evidence)
    await session.flush()

    # 若已有非终态的 material_to_asset review，绑定证据并推进状态。
    open_task = await _find_open_material_review(session, asset_id)
    if open_task is not None:
        session.add(ReviewTaskEvidence(review_task_id=open_task.id, evidence_id=evidence.id))
        if open_task.status == ReviewTaskStatus.pending_evidence.value:
            open_task.status = ReviewTaskStatus.pending_reviewer.value

    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.review_evidence_bound.value,
        trace_id=trace_id,
        target_type="knowledge_asset",
        target_id=asset_id,
        after={
            "evidence_id": str(evidence.id),
            "evidence_type": evidence.evidence_type,
            "evidence_category": evidence.evidence_category,
            "bound_review_id": str(open_task.id) if open_task is not None else None,
        },
        project_id=project_id,
    )
    await session.commit()
    return EvidenceOut(
        id=evidence.id,
        evidence_type=evidence.evidence_type,
        evidence_category=evidence.evidence_category,
        description=evidence.description,
        submitted_by=evidence.submitted_by,
        created_at=evidence.created_at,
    )


async def create_or_get_confirm_asset(
    session: AsyncSession,
    caller: CallerContext,
    project_id: uuid.UUID,
    asset_id: uuid.UUID,
    trace_id: str,
) -> ReviewListItem:
    if not caller.is_business_user:
        await audit_service.record_denied(
            session,
            caller=caller,
            log_type=AuditLogType.exception,
            action=AuditAction.admin_business_denied.value,
            trace_id=trace_id,
            target_type="knowledge_asset",
            target_id=asset_id,
            severity=AlertSeverity.warning,
            risk_level=AuditRiskLevel.high.value,
            extra={
                "denied_reason": "admin_business_permission_denied",
                "attempted": "review.confirm_asset",
            },
        )
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可发起资产确认")
    if project_id not in caller.active_project_ids:
        raise _denied(403, "project_membership_required", "需为该项目的有效成员")
    asset = await _load_project_asset(session, project_id, asset_id)
    if asset.zone != "material":
        raise _denied(422, "asset_not_material", "仅资料区（material）资产可发起资产确认")
    if asset.asset_status != "active":
        raise _denied(422, "asset_not_active", "仅 active 资产可发起资产确认")

    # 已有非终态 review → 返回已有，不重复创建。
    existing = await _find_open_material_review(session, asset_id)
    if existing is not None:
        assets, projects = await _aux_maps(session, [existing])
        return _to_list_item(existing, assets, projects)

    reviewer_id = await _active_pm_of(session, project_id)
    if reviewer_id is None:
        # 不自动升级到咨询总监；升级策略暂未实现。
        raise _denied(422, "reviewer_not_found", "目标项目无 active 项目经理可作为审核人")

    # 已有证据 → pending_reviewer 并绑定；否则 pending_evidence。
    evidences = list(
        (
            await session.execute(
                select(ValidationEvidence).where(ValidationEvidence.related_asset_id == asset_id)
            )
        )
        .scalars()
        .all()
    )
    status = (
        ReviewTaskStatus.pending_reviewer.value
        if evidences
        else ReviewTaskStatus.pending_evidence.value
    )
    task = ReviewTask(
        review_type=ReviewType.material_to_asset.value,
        trigger_source="project_manager_confirm",
        target_asset_id=asset_id,
        target_project_id=project_id,
        target_scope=KnowledgeScope.project.value,
        status=status,
        reviewer_user_id=reviewer_id,
        submitted_by=caller.user_id,
    )
    session.add(task)
    await session.flush()
    for e in evidences:
        session.add(ReviewTaskEvidence(review_task_id=task.id, evidence_id=e.id))

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
            "target_asset_id": str(asset_id),
            "reviewer_user_id": str(reviewer_id),
        },
        project_id=project_id,
    )
    await session.commit()

    task = await _load_task(session, task.id)
    assets, projects = await _aux_maps(session, [task])
    return _to_list_item(task, assets, projects)


async def create_or_get_project_ingest_review(
    session: AsyncSession,
    caller: CallerContext,
    ingest_task: IngestTask,
    req: IngestConfirmRequest,
    trace_id: str,
) -> ReviewListItem:
    """Persist a consultant project submission without creating a knowledge asset."""
    existing = (
        await session.execute(
            select(ReviewTask).where(ReviewTask.source_ingest_task_id == ingest_task.id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        assets, projects = await _aux_maps(session, [existing])
        return _to_list_item(existing, assets, projects)

    assert req.target_project_id is not None
    reviewer_id = await _active_pm_of(session, req.target_project_id)
    task = ReviewTask(
        review_type=ReviewType.project_ingest_approval.value,
        trigger_source="ingest_confirm",
        target_asset_id=None,
        source_ingest_task_id=ingest_task.id,
        confirmation_snapshot=req.model_dump(mode="json"),
        target_project_id=req.target_project_id,
        target_scope=KnowledgeScope.project.value,
        status=ReviewTaskStatus.pending_reviewer.value,
        reviewer_user_id=reviewer_id,
        submitted_by=caller.user_id,
    )
    session.add(task)
    ingest_task.status = "waiting_review"
    ingest_task.target_scope = KnowledgeScope.project.value
    ingest_task.target_project_id = req.target_project_id
    ingest_task.target_zone = req.target_zone.value
    if ingest_task.ai_result is not None:
        ingest_task.ai_result.human_corrected = True
        ingest_task.ai_result.corrected_title = req.title
        ingest_task.ai_result.corrected_summary = req.summary
        ingest_task.ai_result.corrected_tags = req.tags
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
            "target_scope": task.target_scope,
        },
        project_id=req.target_project_id,
    )
    await session.commit()
    task = await _load_task(session, task.id)
    assets, projects = await _aux_maps(session, [task])
    return _to_list_item(task, assets, projects)


def _can_decide_project_ingest(caller: CallerContext, task: ReviewTask) -> bool:
    return bool(
        _is_governance(caller)
        or (
            task.target_project_id is not None
            and caller.active_project_roles.get(task.target_project_id)
            == ProjectRole.project_manager.value
        )
    )


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
            raise _denied(403, "project_ingest_review_forbidden", "仅目标项目经理或治理角色可审批")
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
        from app.services.ingest import approve_project_ingest_review

        return await approve_project_ingest_review(
            session,
            caller,
            task,
            comment,
            trace_id,
            storage=storage,
            weknora=weknora,
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
    task.status = ReviewTaskStatus.approved.value
    task.review_comment = comment
    task.reviewed_at = datetime.now(timezone.utc)
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
    await session.commit()
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
            raise _denied(403, "project_ingest_review_forbidden", "仅目标项目经理或治理角色可审批")
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
        task.status = ReviewTaskStatus.rejected.value
        task.review_comment = comment
        task.reviewed_at = datetime.now(timezone.utc)
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
        await session.commit()
        return ReviewActionResponse(
            review_id=task.id,
            status=task.status,
            target_asset_id=task.target_asset_id,
            asset_zone=None,
        )
    if task.reviewer_user_id != caller.user_id:
        raise _denied(403, "review_action_forbidden", "只有被分配的审核人可审批")
    if task.status in _TERMINAL:
        raise _denied(409, "review_already_finalized", "审核任务已是终态，不可重复操作")

    task.status = ReviewTaskStatus.rejected.value
    task.review_comment = comment
    task.reviewed_at = datetime.now(timezone.utc)
    # 不改变 asset.zone。
    asset = (
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
    await session.commit()
    return ReviewActionResponse(
        review_id=task.id,
        status=task.status,
        target_asset_id=task.target_asset_id,
        asset_zone=asset,
    )
