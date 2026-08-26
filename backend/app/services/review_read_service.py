"""Review task queries and caller-safe response assembly."""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.review import (
    ReviewTask,
    ValidationEvidence,
)
from app.schemas.enums import (
    ProjectRole,
    ReviewTaskStatus,
    ReviewType,
)
from app.schemas.permission import CallerContext
from app.schemas.review import (
    EvidenceOut,
    ReviewDetail,
    ReviewListItem,
)
from app.services.review_queries import caller_is_project_manager as _caller_is_pm_of
from app.services.review_queries import decision_states as _decision_states
from app.services.review_queries import display_maps as _aux_maps
from app.services.review_queries import load_task as _load_task
from app.services.review_support import (
    _NON_TERMINAL,
    _TERMINAL,
    _can_decide_project_ingest,
    _can_view,
    _company_can_decide,
    _company_can_withdraw,
    _denied,
    _is_governance,
    _to_list_item,
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
