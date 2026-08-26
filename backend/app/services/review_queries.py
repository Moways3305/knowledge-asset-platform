"""Review task reads and permission facts; contains no state transitions."""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.identity import Project, ProjectMember
from app.models.knowledge import KnowledgeAsset
from app.models.review import CompanyAssetReviewDecision, ReviewTask
from app.schemas.enums import MemberStatus, ProjectRole, ReviewType
from app.schemas.permission import CallerContext


async def active_project_manager(session: AsyncSession, project_id: uuid.UUID) -> uuid.UUID | None:
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


async def caller_is_project_manager(
    session: AsyncSession, caller: CallerContext, project_id: uuid.UUID | None
) -> bool:
    if project_id is None:
        return False
    membership = (
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
    return membership is not None


async def load_task(
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
        raise HTTPException(
            status_code=404,
            detail={"denied_reason": "review_not_found", "message": "审核任务不存在"},
        )
    return task


async def display_maps(
    session: AsyncSession, tasks: list[ReviewTask]
) -> tuple[dict[uuid.UUID, str], dict[uuid.UUID, str]]:
    asset_ids = {task.target_asset_id for task in tasks if task.target_asset_id is not None}
    project_ids = {task.target_project_id for task in tasks if task.target_project_id is not None}
    assets = {}
    projects = {}
    if asset_ids:
        rows = (
            await session.execute(
                select(KnowledgeAsset.id, KnowledgeAsset.title).where(
                    KnowledgeAsset.id.in_(asset_ids)
                )
            )
        ).all()
        assets = {row[0]: row[1] for row in rows}
    if project_ids:
        rows = (
            await session.execute(
                select(Project.id, Project.name).where(Project.id.in_(project_ids))
            )
        ).all()
        projects = {row[0]: row[1] for row in rows}
    return assets, projects


async def decision_states(
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
