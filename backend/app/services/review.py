"""审核流服务。

闭环：项目 material 资产 → 登记验证证据 → 创建/进入 ReviewTask → PM approve →
KnowledgeAsset.zone = asset。approve/reject 不写 audit_events、
不通知、不调用 Agent、不发布公司库、不创建 access grant。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.identity import Project, ProjectMember
from app.models.ingest import IngestTask
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetTag
from app.models.review import (
    CompanyAssetReviewDecision,
    PersonalKnowledgeSubmission,
    ReviewTask,
    ReviewTaskEvidence,
    ValidationEvidence,
)
from app.schemas.enums import (
    AlertSeverity,
    AuditAction,
    AuditLogType,
    AuditRiskLevel,
    CompanyAssetDecision,
    CompanyRole,
    KnowledgeScope,
    MemberStatus,
    PersonalSubmissionStatus,
    PersonalSubmissionType,
    ProjectRole,
    ReviewTaskStatus,
    ReviewType,
)
from app.schemas.ingest import IngestConfirmRequest
from app.schemas.permission import CallerContext
from app.schemas.review import (
    AssetizationPreflightItem,
    AssetizationPreflightResponse,
    BulkEvidenceItem,
    BulkEvidenceRequest,
    BulkEvidenceResponse,
    EvidenceCreateRequest,
    EvidenceOut,
    ReviewActionResponse,
    ReviewDetail,
    ReviewListItem,
)
from app.services import audit as audit_service
from app.services import governance_policy

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
    return governance_policy.is_admin(caller)


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
    return governance_policy.is_governance(caller)


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


async def _decision_states(
    session: AsyncSession, tasks: list[ReviewTask]
) -> dict[uuid.UUID, dict[str, CompanyAssetReviewDecision]]:
    task_ids = [
        task.id for task in tasks if task.review_type == ReviewType.project_to_company.value
    ]
    if not task_ids:
        return {}
    rows = list(
        (
            await session.execute(
                select(CompanyAssetReviewDecision)
                .where(CompanyAssetReviewDecision.review_task_id.in_(task_ids))
                .order_by(
                    CompanyAssetReviewDecision.created_at,
                    CompanyAssetReviewDecision.id,
                )
            )
        )
        .scalars()
        .all()
    )
    states: dict[uuid.UUID, dict[str, CompanyAssetReviewDecision]] = {}
    for row in rows:
        states.setdefault(row.review_task_id, {})[row.required_role] = row
    return states


def _company_can_decide(
    caller: CallerContext,
    task: ReviewTask,
    states: dict[str, CompanyAssetReviewDecision],
) -> bool:
    if task.status != ReviewTaskStatus.pending_reviewer.value:
        return False
    roles = caller.active_company_roles & governance_policy.GOVERNANCE_COMPANY_ROLES
    return any(
        role not in states or states[role].decision != CompanyAssetDecision.confirmed.value
        for role in roles
    )


def _company_can_withdraw(
    caller: CallerContext,
    task: ReviewTask,
    states: dict[str, CompanyAssetReviewDecision],
) -> bool:
    return task.status == ReviewTaskStatus.pending_reviewer.value and any(
        row.decision == CompanyAssetDecision.confirmed.value and row.actor_user_id == caller.user_id
        for row in states.values()
    )


def _to_list_item(
    task: ReviewTask,
    assets,
    projects,
    *,
    can_decide: bool = False,
    can_withdraw: bool = False,
    decision_states: dict[str, CompanyAssetReviewDecision] | None = None,
) -> ReviewListItem:
    states = decision_states or {}
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
        can_withdraw=can_withdraw,
        blocking_reason=(
            "资料资产化需要至少一项验证证据；请登记适用场景和说明后再交审核人。"
            if task.review_type == ReviewType.material_to_asset.value
            and task.status == ReviewTaskStatus.pending_evidence.value
            else (
                "上次处理未完成，可在确认业务条件未变化后重试。"
                if task.status == ReviewTaskStatus.approval_failed.value
                else None
            )
        ),
        general_manager_confirmation_status=(
            states[CompanyRole.boss.value].decision if CompanyRole.boss.value in states else None
        ),
        consulting_director_confirmation_status=(
            states[CompanyRole.consulting_director.value].decision
            if CompanyRole.consulting_director.value in states
            else None
        ),
        review_comment=task.review_comment,
        reviewed_at=task.reviewed_at,
        created_at=task.created_at,
    )


def _can_view(caller: CallerContext, task: ReviewTask, is_pm: bool) -> bool:
    return (
        task.submitted_by == caller.user_id
        or task.reviewer_user_id == caller.user_id
        or (task.review_type == ReviewType.project_to_company.value and _is_governance(caller))
        or is_pm
    )


async def list_reviews(
    session: AsyncSession,
    caller: CallerContext,
    *,
    review_type: str | None = None,
    status: str | None = None,
) -> list[ReviewListItem]:
    items, _ = await list_reviews_page(
        session,
        caller,
        review_type=review_type,
        status=status,
        page=1,
        page_size=None,
    )
    return items


async def list_reviews_page(
    session: AsyncSession,
    caller: CallerContext,
    *,
    queue: str | None = None,
    review_type: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int | None = 100,
) -> tuple[list[ReviewListItem], int]:
    if not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可查看审核队列")

    stmt = select(ReviewTask).options(selectinload(ReviewTask.evidence_links))
    visibility = [
        ReviewTask.submitted_by == caller.user_id,
        ReviewTask.reviewer_user_id == caller.user_id,
    ]
    pm_project_ids = [
        project_id
        for project_id, role in caller.active_project_roles.items()
        if role == ProjectRole.project_manager.value
    ]
    if pm_project_ids:
        visibility.append(ReviewTask.target_project_id.in_(pm_project_ids))
    if _is_governance(caller):
        visibility.append(ReviewTask.review_type == ReviewType.project_to_company.value)
    stmt = stmt.where(or_(*visibility))
    if queue == "open":
        stmt = stmt.where(ReviewTask.status.in_(list(_NON_TERMINAL)))
    elif queue == "completed":
        stmt = stmt.where(ReviewTask.status.in_(list(_TERMINAL)))
    if review_type:
        stmt = stmt.where(ReviewTask.review_type == review_type)
    if status:
        stmt = stmt.where(ReviewTask.status == status)
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = int((await session.scalar(count_stmt)) or 0)
    if queue == "completed":
        stmt = stmt.order_by(
            ReviewTask.reviewed_at.desc(),
            ReviewTask.created_at.desc(),
            ReviewTask.id.desc(),
        )
    else:
        stmt = stmt.order_by(ReviewTask.created_at.desc(), ReviewTask.id.desc())
    if page_size is not None:
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    visible = list((await session.execute(stmt)).scalars().unique().all())
    assets, projects = await _aux_maps(session, visible)
    decisions = await _decision_states(session, visible)
    return [
        _to_list_item(
            task,
            assets,
            projects,
            can_decide=(
                _company_can_decide(caller, task, decisions.get(task.id, {}))
                if task.review_type == ReviewType.project_to_company.value
                else (
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
                )
            ),
            can_withdraw=(
                _company_can_withdraw(caller, task, decisions.get(task.id, {}))
                or (
                    task.review_type == ReviewType.material_to_asset.value
                    and task.status
                    in {
                        ReviewTaskStatus.pending_evidence.value,
                        ReviewTaskStatus.pending_reviewer.value,
                    }
                    and task.submitted_by == caller.user_id
                )
            ),
            decision_states=decisions.get(task.id),
        )
        for task in visible
    ], total


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
    decisions = (await _decision_states(session, [task])).get(task.id, {})
    base = _to_list_item(
        task,
        assets,
        projects,
        can_decide=(
            _company_can_decide(caller, task, decisions)
            if task.review_type == ReviewType.project_to_company.value
            else (
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
            )
        ),
        can_withdraw=(
            _company_can_withdraw(caller, task, decisions)
            or (
                task.review_type == ReviewType.material_to_asset.value
                and task.status
                in {
                    ReviewTaskStatus.pending_evidence.value,
                    ReviewTaskStatus.pending_reviewer.value,
                }
                and task.submitted_by == caller.user_id
            )
        ),
        decision_states=decisions,
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
    session: AsyncSession,
    project_id: uuid.UUID,
    asset_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> KnowledgeAsset:
    stmt = select(KnowledgeAsset).where(KnowledgeAsset.id == asset_id)
    if for_update:
        stmt = stmt.with_for_update()
    asset = (await session.execute(stmt)).scalar_one_or_none()
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
    await _load_project_asset(session, project_id, asset_id, for_update=True)

    existing_evidence = None
    if req.idempotency_key:
        existing_evidence = (
            await session.execute(
                select(ValidationEvidence).where(
                    ValidationEvidence.submitted_by == caller.user_id,
                    ValidationEvidence.related_asset_id == asset_id,
                    ValidationEvidence.idempotency_key == req.idempotency_key,
                )
            )
        ).scalar_one_or_none()
    evidence = existing_evidence or ValidationEvidence(
        evidence_type=req.evidence_type.value,
        evidence_category=req.evidence_category.value,
        related_asset_id=asset_id,
        project_id=project_id,
        submitted_by=caller.user_id,
        description=req.description,
        attachments=req.attachments,
        idempotency_key=req.idempotency_key,
    )
    if existing_evidence is None:
        session.add(evidence)
        await session.flush()

    open_task = await _find_open_material_review(session, asset_id)
    if open_task is not None:
        linked = any(link.evidence_id == evidence.id for link in open_task.evidence_links)
        if not linked:
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
    if open_task is not None and open_task.status == ReviewTaskStatus.pending_reviewer.value:
        from app.services.notifications import notify_review_pending

        await notify_review_pending(session, open_task)
    await session.commit()
    return EvidenceOut(
        id=evidence.id,
        evidence_type=evidence.evidence_type,
        evidence_category=evidence.evidence_category,
        description=evidence.description,
        submitted_by=evidence.submitted_by,
        created_at=evidence.created_at,
    )


async def preflight_assetization(
    session: AsyncSession,
    caller: CallerContext,
    project_id: uuid.UUID,
    item_ids: list[uuid.UUID],
) -> AssetizationPreflightResponse:
    if not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可发起资产化审核")
    if project_id not in caller.active_project_ids:
        raise _denied(403, "project_membership_required", "需为该项目的有效成员")
    rows = list(
        (
            await session.execute(
                select(KnowledgeAsset)
                .where(KnowledgeAsset.id.in_(item_ids))
                .options(selectinload(KnowledgeAsset.tags))
            )
        )
        .scalars()
        .all()
    )
    assets = {row.id: row for row in rows}
    open_tasks = {
        row.target_asset_id: row
        for row in (
            await session.execute(
                select(ReviewTask)
                .where(
                    ReviewTask.target_asset_id.in_(item_ids),
                    ReviewTask.review_type == ReviewType.material_to_asset.value,
                    ReviewTask.status.in_(list(_NON_TERMINAL)),
                )
                .options(selectinload(ReviewTask.evidence_links))
            )
        )
        .scalars()
        .unique()
        .all()
    }
    counts = dict(
        (
            await session.execute(
                select(ValidationEvidence.related_asset_id, func.count())
                .where(ValidationEvidence.related_asset_id.in_(item_ids))
                .group_by(ValidationEvidence.related_asset_id)
            )
        ).all()
    )
    items = []
    for item_id in item_ids:
        asset = assets.get(item_id)
        count = int(counts.get(item_id, 0))
        if (
            asset is None
            or asset.project_id != project_id
            or asset.scope != KnowledgeScope.project.value
        ):
            items.append(
                AssetizationPreflightItem(
                    item_id=item_id,
                    title="不可见资料",
                    status="ineligible",
                    evidence_count=0,
                    reason_code="asset_not_in_project",
                    message="资料不属于当前项目",
                )
            )
        elif asset.zone != "material" or asset.asset_status != "active":
            items.append(
                AssetizationPreflightItem(
                    item_id=item_id,
                    title=asset.canonical_name or asset.title or "待确认资料",
                    status="ineligible",
                    evidence_count=count,
                    reason_code="asset_not_eligible",
                    message="仅可对有效资料区内容发起审核",
                )
            )
        elif item_id in open_tasks:
            task = open_tasks[item_id]
            task_count = max(count, len(task.evidence_links))
            if task.status == ReviewTaskStatus.pending_evidence.value and task_count == 0:
                items.append(
                    AssetizationPreflightItem(
                        item_id=item_id,
                        title=asset.canonical_name or asset.title or "待确认资料",
                        status="evidence_missing",
                        evidence_count=0,
                        reason_code="assetization_evidence_required",
                        message="已有待补证据任务；补齐后将复用，不会重复建单",
                    )
                )
            else:
                items.append(
                    AssetizationPreflightItem(
                        item_id=item_id,
                        title=asset.canonical_name or asset.title or "待确认资料",
                        status="existing",
                        evidence_count=task_count,
                        message="已有待办，将复用现有审核",
                    )
                )
        elif count:
            items.append(
                AssetizationPreflightItem(
                    item_id=item_id,
                    title=asset.canonical_name or asset.title or "待确认资料",
                    status="ready",
                    evidence_count=count,
                    message="已有可绑定证据",
                )
            )
        else:
            items.append(
                AssetizationPreflightItem(
                    item_id=item_id,
                    title=asset.canonical_name or asset.title or "待确认资料",
                    status="evidence_missing",
                    evidence_count=0,
                    reason_code="assetization_evidence_required",
                    message="需先登记验证证据",
                )
            )
    return AssetizationPreflightResponse(items=items)


async def bulk_register_evidence(
    session: AsyncSession,
    caller: CallerContext,
    body: BulkEvidenceRequest,
    trace_id: str,
) -> BulkEvidenceResponse:
    if not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可补充证据")
    _validate_attachments(body.evidence.attachments)
    tasks = list(
        (
            await session.execute(
                select(ReviewTask)
                .where(ReviewTask.id.in_(body.review_ids))
                .options(selectinload(ReviewTask.evidence_links))
                .with_for_update()
            )
        )
        .scalars()
        .unique()
        .all()
    )
    by_id = {row.id: row for row in tasks}
    if len(tasks) != len(set(body.review_ids)):
        raise _denied(404, "review_not_found", "部分审核任务不存在或不可用")
    project_ids = {row.target_project_id for row in tasks}
    if len(project_ids) != 1 or None in project_ids:
        raise _denied(422, "bulk_evidence_project_mismatch", "批量补证据仅适用于同一项目")
    project_id = next(iter(project_ids))
    if project_id not in caller.active_project_ids:
        raise _denied(403, "project_membership_required", "需为该项目的有效成员")
    results: list[BulkEvidenceItem] = []
    transitioned = existing_count = skipped = failed = 0
    for review_id in body.review_ids:
        task = by_id.get(review_id)
        if task is None:
            skipped += 1
            results.append(
                BulkEvidenceItem(
                    review_id=review_id, status="skipped", reason_code="review_not_found"
                )
            )
            continue
        if (
            task.review_type != ReviewType.material_to_asset.value
            or task.status
            not in {
                ReviewTaskStatus.pending_evidence.value,
                ReviewTaskStatus.pending_reviewer.value,
            }
            or not task.target_asset_id
        ):
            skipped += 1
            results.append(
                BulkEvidenceItem(
                    review_id=review_id, status="skipped", reason_code="review_not_eligible"
                )
            )
            continue
        key = f"{body.evidence.idempotency_key or 'bulk'}:{review_id}"
        evidence = (
            await session.execute(
                select(ValidationEvidence).where(
                    ValidationEvidence.submitted_by == caller.user_id,
                    ValidationEvidence.related_asset_id == task.target_asset_id,
                    ValidationEvidence.idempotency_key == key,
                )
            )
        ).scalar_one_or_none()
        if evidence is None:
            evidence = ValidationEvidence(
                evidence_type=body.evidence.evidence_type.value,
                evidence_category=body.evidence.evidence_category.value,
                related_asset_id=task.target_asset_id,
                project_id=project_id,
                submitted_by=caller.user_id,
                description=body.evidence.description,
                attachments=body.evidence.attachments,
                idempotency_key=key,
            )
            session.add(evidence)
            await session.flush()
        if not any(link.evidence_id == evidence.id for link in task.evidence_links):
            session.add(ReviewTaskEvidence(review_task_id=task.id, evidence_id=evidence.id))
        else:
            existing_count += 1
        if task.status == ReviewTaskStatus.pending_evidence.value:
            task.status = ReviewTaskStatus.pending_reviewer.value
            transitioned += 1
        results.append(
            BulkEvidenceItem(
                review_id=review_id,
                status="transitioned"
                if task.status == ReviewTaskStatus.pending_reviewer.value
                else "existing",
            )
        )
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.review_evidence_bound.value,
            trace_id=trace_id,
            target_type="review_task",
            target_id=task.id,
            after={"status": task.status, "evidence_type": evidence.evidence_type},
            project_id=project_id,
        )
    from app.services.notifications import notify_review_pending

    for task in tasks:
        if task.status == ReviewTaskStatus.pending_reviewer.value:
            await notify_review_pending(session, task)
    await session.commit()
    return BulkEvidenceResponse(
        submitted=len(body.review_ids),
        transitioned=transitioned,
        existing=existing_count,
        skipped=skipped,
        failed=failed,
        items=results,
    )


async def create_or_get_confirm_asset_with_outcome(
    session: AsyncSession,
    caller: CallerContext,
    project_id: uuid.UUID,
    asset_id: uuid.UUID,
    trace_id: str,
) -> tuple[ReviewListItem, bool]:
    """Return the authoritative item and whether this locked call created it."""
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
    asset = await _load_project_asset(session, project_id, asset_id, for_update=True)
    if asset.zone != "material":
        raise _denied(422, "asset_not_material", "仅资料区（material）资产可发起资产确认")
    if asset.asset_status != "active":
        raise _denied(422, "asset_not_active", "仅 active 资产可发起资产确认")

    # 已有非终态 review → 返回已有，不重复创建。
    existing = await _find_open_material_review(session, asset_id)
    if existing is not None:
        assets, projects = await _aux_maps(session, [existing])
        return _to_list_item(existing, assets, projects), False

    reviewer_id = await _active_pm_of(session, project_id)
    if reviewer_id is None:
        # 不自动升级到咨询总监；升级策略暂未实现。
        raise _denied(422, "reviewer_not_found", "目标项目无 active 项目经理可作为审核人")

    # New submissions fail closed. Historical pending_evidence tasks remain recoverable
    # through the evidence workspace, but this endpoint never creates another one.
    evidences = list(
        (
            await session.execute(
                select(ValidationEvidence).where(ValidationEvidence.related_asset_id == asset_id)
            )
        )
        .scalars()
        .all()
    )
    if not evidences:
        raise _denied(422, "assetization_evidence_required", "请先登记验证证据，再发起资产化审核")
    status = ReviewTaskStatus.pending_reviewer.value
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
    if task.status == ReviewTaskStatus.pending_reviewer.value:
        from app.services.notifications import notify_review_pending

        await notify_review_pending(session, task)
    await session.commit()

    task = await _load_task(session, task.id)
    assets, projects = await _aux_maps(session, [task])
    return _to_list_item(task, assets, projects), True


async def create_or_get_confirm_asset(
    session: AsyncSession,
    caller: CallerContext,
    project_id: uuid.UUID,
    asset_id: uuid.UUID,
    trace_id: str,
) -> ReviewListItem:
    item, _created = await create_or_get_confirm_asset_with_outcome(
        session, caller, project_id, asset_id, trace_id
    )
    return item


async def create_or_get_company_upgrade(
    session: AsyncSession,
    caller: CallerContext,
    project_id: uuid.UUID,
    asset_id: uuid.UUID,
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

    task = ReviewTask(
        review_type=ReviewType.project_to_company.value,
        trigger_source="project_manager_upgrade",
        target_asset_id=asset.id,
        target_project_id=project_id,
        target_scope=KnowledgeScope.company.value,
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
    from app.services.notifications import notify_review_pending

    await notify_review_pending(session, task)
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

    if req.target_project_id is None:
        raise RuntimeError("project ingest review requires target_project_id")
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
    from app.services.notifications import notify_review_pending

    await notify_review_pending(session, task)
    await session.commit()
    task = await _load_task(session, task.id)
    assets, projects = await _aux_maps(session, [task])
    return _to_list_item(task, assets, projects)


def _can_decide_project_ingest(caller: CallerContext, task: ReviewTask) -> bool:
    return bool(
        task.target_project_id is not None
        and caller.active_project_roles.get(task.target_project_id)
        == ProjectRole.project_manager.value
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
        before = {"scope": asset.scope, "project_id": str(asset.project_id)}
        asset.scope = KnowledgeScope.company.value
        asset.project_id = None
        task.status = ReviewTaskStatus.approved.value
        task.review_comment = comment
        task.reviewed_at = datetime.now(timezone.utc)
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
            action=AuditAction.asset_scope_changed.value,
            trace_id=trace_id,
            target_type="knowledge_asset",
            target_id=asset.id,
            before=before,
            after={"scope": asset.scope, "project_id": None},
            extra={"review_id": str(task.id), "change": "project_to_company"},
            project_id=task.target_project_id,
        )
    await session.commit()
    return ReviewActionResponse(
        review_id=task.id,
        status=task.status,
        target_asset_id=asset.id,
        asset_zone=asset.zone,
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
    if task.review_type == ReviewType.project_to_company.value:
        return await _approve_company_upgrade(session, caller, task, comment, trace_id)
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
        task.status = ReviewTaskStatus.approved.value
        task.review_comment = comment
        task.reviewed_at = datetime.now(timezone.utc)
        submission.status = PersonalSubmissionStatus.approved.value
        result_asset = await session.get(KnowledgeAsset, task.target_asset_id)
        if (
            submission.submission_type == PersonalSubmissionType.submit_to_project.value
            and result_asset is not None
            and task.target_project_id is not None
        ):
            existing_copy = (
                await session.execute(
                    select(KnowledgeAsset).where(
                        KnowledgeAsset.source_asset_id == result_asset.id,
                        KnowledgeAsset.scope == KnowledgeScope.project.value,
                        KnowledgeAsset.project_id == task.target_project_id,
                        KnowledgeAsset.asset_status == "active",
                    )
                )
            ).scalar_one_or_none()
            if existing_copy is None:
                source = (
                    await session.execute(
                        select(KnowledgeAsset)
                        .where(KnowledgeAsset.id == result_asset.id)
                        .options(selectinload(KnowledgeAsset.tags))
                    )
                ).scalar_one()
                existing_copy = KnowledgeAsset(
                    title=source.title,
                    scope=KnowledgeScope.project.value,
                    zone="material",
                    asset_type=source.asset_type,
                    owner_user_id=source.owner_user_id,
                    maintainer_user_id=source.maintainer_user_id or source.owner_user_id,
                    project_id=task.target_project_id,
                    source_asset_id=source.id,
                    current_version_id=source.current_version_id,
                    visibility="project_only",
                    confidentiality_level=source.confidentiality_level,
                    ai_access_level=source.ai_access_level,
                    asset_status="active",
                )
                existing_copy.tags.extend(
                    KnowledgeAssetTag(tag_name=tag.tag_name) for tag in source.tags
                )
                session.add(existing_copy)
                await session.flush()
            result_asset = existing_copy
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
        await session.commit()
        return ReviewActionResponse(
            review_id=task.id,
            status=task.status,
            target_asset_id=result_asset.id if result_asset else task.target_asset_id,
            asset_zone=result_asset.zone if result_asset else None,
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
        task.status = ReviewTaskStatus.rejected.value
        task.review_comment = comment
        task.reviewed_at = datetime.now(timezone.utc)
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
        await session.commit()
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
        await session.commit()
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

    task.status = ReviewTaskStatus.rejected.value
    task.review_comment = comment
    task.reviewed_at = datetime.now(timezone.utc)
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
    await session.commit()
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
    task.status = ReviewTaskStatus.rejected.value
    task.review_comment = comment
    task.reviewed_at = datetime.now(timezone.utc)
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
    await session.commit()
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
    task.status = ReviewTaskStatus.rejected.value
    task.review_comment = (comment or "发起人撤回").strip()
    task.reviewed_at = datetime.now(timezone.utc)
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
    await session.commit()
    asset = await session.get(KnowledgeAsset, task.target_asset_id)
    return ReviewActionResponse(
        review_id=task.id,
        status=task.status,
        target_asset_id=task.target_asset_id,
        asset_zone=asset.zone if asset else None,
    )
