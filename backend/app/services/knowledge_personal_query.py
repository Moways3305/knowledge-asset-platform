"""Personal-knowledge state expressions and caller-safe list projection."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.models.identity import Project
from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetTag,
)
from app.models.review import PersonalKnowledgeSubmission, ReviewTask
from app.schemas.enums import (
    AssetStatus,
    KnowledgeScope,
    PersonalKnowledgeState,
    PersonalSubmissionStatus,
    PersonalSubmissionType,
    ReviewTaskStatus,
)
from app.schemas.my_knowledge import (
    PersonalEvidenceSummary,
    PersonalKnowledgeItemOut,
    PersonalKnowledgeListResponse,
    PersonalKnowledgeSummary,
    PersonalProjectSubmissionSummary,
)
from app.schemas.permission import (
    CallerContext,
)
from app.services import (
    original_access,
)
from app.services.knowledge_projection import (
    _aux_maps,
    _denied,
    _like_pattern,
    _to_list_item,
    _version_index_map,
)
from app.services.permission_rules import load_access_policy

_PERSONAL_STATE_LABELS = {
    PersonalKnowledgeState.awaiting_confirmation.value: "待本人确认",
    PersonalKnowledgeState.ready_to_submit.value: "可提交项目",
    PersonalKnowledgeState.pending_project_review.value: "待项目经理审批",
    PersonalKnowledgeState.active_in_project.value: "已进入项目",
    PersonalKnowledgeState.project_rejected.value: "项目未通过",
}
_PENDING_REVIEW_STATUSES = {
    ReviewTaskStatus.pending_evidence.value,
    ReviewTaskStatus.pending_reviewer.value,
    ReviewTaskStatus.approving.value,
    ReviewTaskStatus.approval_failed.value,
}


def _effective_submission_status(
    submission: PersonalKnowledgeSubmission, task: ReviewTask | None
) -> str:
    """审核任务是真实裁决源；无任务时才回退提交记录状态。"""
    if task is None:
        return submission.status
    if task.status == ReviewTaskStatus.approved.value:
        return PersonalSubmissionStatus.approved.value
    if task.status == ReviewTaskStatus.rejected.value:
        return PersonalSubmissionStatus.rejected.value
    if task.status in _PENDING_REVIEW_STATUSES:
        return PersonalSubmissionStatus.pending.value
    return submission.status


def _latest_project_submission_status_expression():
    return (
        select(
            case(
                (
                    ReviewTask.status == ReviewTaskStatus.approved.value,
                    PersonalSubmissionStatus.approved.value,
                ),
                (
                    ReviewTask.status == ReviewTaskStatus.rejected.value,
                    PersonalSubmissionStatus.rejected.value,
                ),
                (
                    ReviewTask.status.in_(_PENDING_REVIEW_STATUSES),
                    PersonalSubmissionStatus.pending.value,
                ),
                else_=PersonalKnowledgeSubmission.status,
            )
        )
        .select_from(PersonalKnowledgeSubmission)
        .outerjoin(ReviewTask, ReviewTask.id == PersonalKnowledgeSubmission.review_task_id)
        .where(
            PersonalKnowledgeSubmission.source_asset_id == KnowledgeAsset.id,
            PersonalKnowledgeSubmission.submission_type
            == PersonalSubmissionType.submit_to_project.value,
        )
        .order_by(
            PersonalKnowledgeSubmission.created_at.desc(),
            PersonalKnowledgeSubmission.id.desc(),
        )
        .limit(1)
        .correlate(KnowledgeAsset)
        .scalar_subquery()
    )


def _active_project_copy_exists_expression():
    project_copy = aliased(KnowledgeAsset)
    return KnowledgeAsset.id.in_(
        select(project_copy.source_asset_id).where(
            project_copy.scope == KnowledgeScope.project.value,
            project_copy.asset_status == AssetStatus.active.value,
            project_copy.source_asset_id.is_not(None),
        )
    )


def _personal_state_expression():
    latest_status = _latest_project_submission_status_expression()
    return case(
        (
            _active_project_copy_exists_expression(),
            PersonalKnowledgeState.active_in_project.value,
        ),
        (
            KnowledgeAsset.zone == "material",
            PersonalKnowledgeState.awaiting_confirmation.value,
        ),
        (
            latest_status == PersonalSubmissionStatus.pending.value,
            PersonalKnowledgeState.pending_project_review.value,
        ),
        (
            latest_status == PersonalSubmissionStatus.rejected.value,
            PersonalKnowledgeState.project_rejected.value,
        ),
        else_=PersonalKnowledgeState.ready_to_submit.value,
    )


def _personal_state_filter_expression(personal_state: str):
    return _personal_state_expression() == personal_state


async def _personal_projection(
    session: AsyncSession, assets: list[KnowledgeAsset]
) -> dict[uuid.UUID, dict]:
    asset_ids = [asset.id for asset in assets]
    if not asset_ids:
        return {}
    submissions = list(
        (
            await session.execute(
                select(PersonalKnowledgeSubmission)
                .where(PersonalKnowledgeSubmission.source_asset_id.in_(asset_ids))
                .order_by(
                    PersonalKnowledgeSubmission.created_at.desc(),
                    PersonalKnowledgeSubmission.id.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    task_ids = {row.review_task_id for row in submissions if row.review_task_id is not None}
    tasks = (
        {
            row.id: row
            for row in (
                (await session.execute(select(ReviewTask).where(ReviewTask.id.in_(task_ids))))
                .scalars()
                .all()
            )
        }
        if task_ids
        else {}
    )
    project_ids = {row.target_project_id for row in submissions if row.target_project_id}
    project_names: dict[uuid.UUID, str] = {}
    if project_ids:
        project_name_rows = (
            await session.execute(
                select(Project.id, Project.name).where(Project.id.in_(project_ids))
            )
        ).all()
        project_names = {project_id: name for project_id, name in project_name_rows}
    project_copies = set(
        (
            await session.execute(
                select(KnowledgeAsset.source_asset_id).where(
                    KnowledgeAsset.source_asset_id.in_(asset_ids),
                    KnowledgeAsset.scope == KnowledgeScope.project.value,
                    KnowledgeAsset.asset_status == AssetStatus.active.value,
                )
            )
        )
        .scalars()
        .all()
    )

    grouped: dict[uuid.UUID, list[PersonalKnowledgeSubmission]] = {}
    for row in submissions:
        grouped.setdefault(row.source_asset_id, []).append(row)

    result: dict[uuid.UUID, dict] = {}
    for asset in assets:
        rows = grouped.get(asset.id, [])
        project_rows = [
            row
            for row in rows
            if row.submission_type == PersonalSubmissionType.submit_to_project.value
        ]
        evidence_rows = [
            row
            for row in rows
            if row.submission_type
            in {
                PersonalSubmissionType.internal_sharing_candidate.value,
                PersonalSubmissionType.client_validation_candidate.value,
            }
        ]
        latest = project_rows[0] if project_rows else None
        latest_task = (
            tasks.get(latest.review_task_id)
            if latest is not None and latest.review_task_id is not None
            else None
        )
        latest_status = (
            _effective_submission_status(latest, latest_task) if latest is not None else None
        )
        if asset.id in project_copies:
            state = PersonalKnowledgeState.active_in_project.value
        elif asset.zone == "material":
            state = PersonalKnowledgeState.awaiting_confirmation.value
        elif latest_status == PersonalSubmissionStatus.pending.value:
            state = PersonalKnowledgeState.pending_project_review.value
        elif latest_status == PersonalSubmissionStatus.rejected.value:
            state = PersonalKnowledgeState.project_rejected.value
        else:
            state = PersonalKnowledgeState.ready_to_submit.value

        task = latest_task
        project_summary = (
            PersonalProjectSubmissionSummary(
                status=latest_status or latest.status,
                target_project_name=(
                    project_names.get(latest.target_project_id)
                    if latest.target_project_id is not None
                    else None
                ),
                submitted_at=latest.created_at,
                resolved_at=task.reviewed_at if task else None,
            )
            if latest is not None
            else None
        )
        evidence_summary = None
        if evidence_rows:
            evidence_latest = evidence_rows[0]
            evidence_task = (
                tasks.get(evidence_latest.review_task_id)
                if evidence_latest.review_task_id is not None
                else None
            )
            evidence_summary = PersonalEvidenceSummary(
                registered_count=len(evidence_rows),
                latest_status=_effective_submission_status(evidence_latest, evidence_task),
                updated_at=evidence_latest.updated_at,
            )
        result[asset.id] = {
            "state": state,
            "project_submission": project_summary,
            "evidence_summary": evidence_summary,
        }
    return result


async def list_my_knowledge(
    session: AsyncSession,
    caller: CallerContext,
    *,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    asset_type: str | None = None,
    personal_state: str | None = None,
    sort_by: str = "updated_at",
    sort_direction: str = "desc",
) -> PersonalKnowledgeListResponse:
    """个人知识 owner-only 分页读模型及安全治理状态投影。"""
    if not caller.is_business_user:
        # admin 不作为业务个人知识库主体。
        raise _denied(
            403,
            "admin_business_permission_denied",
            "仅业务用户可拥有个人知识库",
        )
    conditions = [
        KnowledgeAsset.scope == KnowledgeScope.personal.value,
        KnowledgeAsset.owner_user_id == caller.user_id,
        KnowledgeAsset.asset_status == AssetStatus.active.value,
    ]
    if asset_type:
        conditions.append(KnowledgeAsset.asset_type == asset_type)
    if keyword:
        pattern = _like_pattern(keyword)
        conditions.append(
            or_(
                KnowledgeAsset.title.ilike(pattern, escape="\\"),
                KnowledgeAsset.tags.any(KnowledgeAssetTag.tag_name.ilike(pattern, escape="\\")),
            )
        )
    if personal_state:
        conditions.append(_personal_state_filter_expression(personal_state))

    total = int(
        (
            await session.execute(select(func.count(KnowledgeAsset.id)).where(*conditions))
        ).scalar_one()
    )
    sort_column = (
        func.lower(KnowledgeAsset.title) if sort_by == "title" else getattr(KnowledgeAsset, sort_by)
    )
    order = sort_column.desc() if sort_direction == "desc" else sort_column.asc()
    id_order = KnowledgeAsset.id.desc() if sort_direction == "desc" else KnowledgeAsset.id.asc()
    page_stmt = (
        select(KnowledgeAsset)
        .where(*conditions)
        .options(selectinload(KnowledgeAsset.tags), selectinload(KnowledgeAsset.summaries))
        .order_by(order, id_order)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    page_assets = list((await session.execute(page_stmt)).scalars().all())
    policy = await load_access_policy(session)
    projection = await _personal_projection(session, page_assets)
    projects, _users = await _aux_maps(session, page_assets)
    granted = await original_access.active_grant_asset_ids(
        session, caller, [a.id for a in page_assets]
    )
    vindex = await _version_index_map(session, page_assets)
    items: list[PersonalKnowledgeItemOut] = []
    for asset in page_assets:
        base = _to_list_item(caller, asset, projects, granted, vindex, policy)
        projected = projection[asset.id]
        items.append(
            PersonalKnowledgeItemOut(
                **base.model_dump(),
                created_at=asset.created_at,
                personal_state=projected["state"],
                personal_state_label=_PERSONAL_STATE_LABELS[projected["state"]],
                project_submission=projected["project_submission"],
                evidence_summary=projected["evidence_summary"],
            )
        )

    summary_conditions = [
        KnowledgeAsset.scope == KnowledgeScope.personal.value,
        KnowledgeAsset.owner_user_id == caller.user_id,
        KnowledgeAsset.asset_status == AssetStatus.active.value,
    ]
    month_start = (
        datetime.now(ZoneInfo("Asia/Shanghai"))
        .replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        .astimezone(timezone.utc)
    )
    summary_rows = (
        select(
            KnowledgeAsset.id.label("asset_id"),
            KnowledgeAsset.created_at.label("created_at"),
            _personal_state_expression().label("personal_state"),
        )
        .where(*summary_conditions)
        .subquery()
    )
    summary_state = summary_rows.c.personal_state
    summary_row = (
        await session.execute(
            select(
                func.count(summary_rows.c.asset_id),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                summary_state == PersonalKnowledgeState.awaiting_confirmation.value,
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                summary_state
                                == PersonalKnowledgeState.pending_project_review.value,
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                summary_state == PersonalKnowledgeState.active_in_project.value,
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(case((summary_rows.c.created_at >= month_start, 1), else_=0)),
                    0,
                ),
            ).select_from(summary_rows)
        )
    ).one()
    summary = PersonalKnowledgeSummary(
        total_assets=int(summary_row[0]),
        awaiting_confirmation=int(summary_row[1]),
        pending_project_review=int(summary_row[2]),
        active_in_project=int(summary_row[3]),
        created_this_month=int(summary_row[4]),
    )
    return PersonalKnowledgeListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_next=page * page_size < total,
        summary=summary,
    )
