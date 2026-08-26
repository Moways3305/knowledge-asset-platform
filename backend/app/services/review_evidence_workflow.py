"""Evidence registration and project material assetization workflow."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.knowledge import (
    KnowledgeAsset,
)
from app.models.review import (
    ReviewTask,
    ReviewTaskEvidence,
    ValidationEvidence,
)
from app.schemas.enums import (
    AlertSeverity,
    AuditAction,
    AuditLogType,
    AuditRiskLevel,
    KnowledgeScope,
    ReviewTaskStatus,
    ReviewType,
)
from app.schemas.permission import CallerContext
from app.schemas.review import (
    AssetizationPreflightItem,
    AssetizationPreflightResponse,
    BulkEvidenceItem,
    BulkEvidenceRequest,
    BulkEvidenceResponse,
    EvidenceCreateRequest,
    EvidenceOut,
    ReviewListItem,
)
from app.services import audit as audit_service
from app.services.review_events import publish_action_required as _publish_review_action_required
from app.services.review_queries import active_project_manager as _active_pm_of
from app.services.review_queries import display_maps as _aux_maps
from app.services.review_queries import load_task as _load_task
from app.services.review_support import (
    _NON_TERMINAL,
    _denied,
    _to_list_item,
    _validate_attachments,
)
from app.worker.enqueue import enqueue_outbox_delivery


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
        await _publish_review_action_required(session, open_task)
    await session.commit()
    await enqueue_outbox_delivery(session)
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
    counts: dict[uuid.UUID, int] = {
        asset_id: int(count)
        for asset_id, count in (
            await session.execute(
                select(ValidationEvidence.related_asset_id, func.count())
                .where(ValidationEvidence.related_asset_id.in_(item_ids))
                .group_by(ValidationEvidence.related_asset_id)
            )
        ).tuples()
    }
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
    for task in tasks:
        if task.status == ReviewTaskStatus.pending_reviewer.value:
            await _publish_review_action_required(session, task)
    await session.commit()
    await enqueue_outbox_delivery(session)
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
        await _publish_review_action_required(session, task)
    await session.commit()
    await enqueue_outbox_delivery(session)

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
