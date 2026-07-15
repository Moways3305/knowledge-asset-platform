"""Permission-scoped first-party project overview composition."""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Project, ProjectMember, User
from app.models.ingest import IngestTask
from app.models.weknora import WeknoraKbMapping
from app.schemas.enums import KnowledgeScope, KnowledgeZone, MemberStatus, ProjectRole
from app.schemas.permission import CallerContext
from app.schemas.project_settings import (
    ProjectOverviewActivity,
    ProjectOverviewCapabilities,
    ProjectOverviewCounts,
    ProjectOverviewHeader,
    ProjectOverviewKbStatus,
    ProjectOverviewMember,
    ProjectOverviewResponse,
)
from app.services import knowledge as knowledge_service
from app.services import original_access as original_access_service
from app.services import review as review_service


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"denied_reason": "project_not_found", "message": "Project not found"},
    )


async def _load_active_membership(
    session: AsyncSession, caller: CallerContext, project_id: uuid.UUID
) -> tuple[ProjectMember, Project]:
    row = (
        await session.execute(
            select(ProjectMember, Project)
            .join(Project, Project.id == ProjectMember.project_id)
            .where(
                ProjectMember.user_id == caller.user_id,
                ProjectMember.project_id == project_id,
                ProjectMember.status == MemberStatus.active.value,
                Project.status == "active",
            )
        )
    ).one_or_none()
    if row is None:
        # Missing projects and inaccessible projects intentionally share one response.
        raise _not_found()
    return row[0], row[1]


async def _knowledge_page(
    session: AsyncSession,
    caller: CallerContext,
    project_id: uuid.UUID,
    *,
    zone: str | None,
    page_size: int,
):
    return await knowledge_service.list_knowledge(
        session,
        caller,
        scope=KnowledgeScope.project.value,
        project_id=project_id,
        zone=zone,
        sort_by="updated_at",
        sort_direction="desc",
        page=1,
        page_size=page_size,
    )


async def get_overview(
    session: AsyncSession, caller: CallerContext, project_id: uuid.UUID
) -> ProjectOverviewResponse:
    membership, project = await _load_active_membership(session, caller, project_id)
    is_manager = membership.project_role == ProjectRole.project_manager.value

    material = await _knowledge_page(
        session, caller, project_id, zone=KnowledgeZone.material.value, page_size=1
    )
    assets = await _knowledge_page(
        session, caller, project_id, zone=KnowledgeZone.asset.value, page_size=1
    )
    recent = await _knowledge_page(session, caller, project_id, zone=None, page_size=10)

    pending_confirmation = int(
        (
            await session.execute(
                select(func.count())
                .select_from(IngestTask)
                .where(
                    IngestTask.created_by == caller.user_id,
                    IngestTask.target_project_id == project_id,
                    IngestTask.status == "pending_confirmation",
                )
            )
        ).scalar_one()
    )

    pending_review = 0
    if is_manager:
        reviews = await review_service.list_reviews(session, caller)
        pending_review = sum(
            item.target_project_id == project_id
            and item.can_decide
            and item.status in {"pending_reviewer", "approval_failed"}
            for item in reviews
        )

    pending_access = 0
    if membership.project_role in {
        ProjectRole.project_manager.value,
        ProjectRole.coach.value,
    }:
        access_inbox = await original_access_service.list_requests(
            session, caller, box="inbox", status="pending"
        )
        pending_access = sum(item.project_id == project_id for item in access_inbox.items)

    mapping = (
        await session.execute(
            select(WeknoraKbMapping).where(
                WeknoraKbMapping.scope == KnowledgeScope.project.value,
                WeknoraKbMapping.project_id == project_id,
            )
        )
    ).scalar_one_or_none()

    members: list[ProjectOverviewMember] = []
    if is_manager:
        member_rows = (
            await session.execute(
                select(ProjectMember, User)
                .join(User, User.id == ProjectMember.user_id)
                .where(ProjectMember.project_id == project_id)
                .order_by(User.name, ProjectMember.id)
            )
        ).all()
        members = [
            ProjectOverviewMember(
                user_id=member.user_id,
                name=user.name,
                project_role=member.project_role,
                status=member.status,
            )
            for member, user in member_rows
        ]

    return ProjectOverviewResponse(
        project=ProjectOverviewHeader(
            project_id=project.id,
            name=project.name,
            client_name=project.client_name,
            status=project.status,
            project_role=membership.project_role,
            lifecycle_route_key=project.lifecycle_route_key,
            lifecycle_phase_key=project.lifecycle_phase_key,
            can_manage=is_manager,
        ),
        capabilities=ProjectOverviewCapabilities(
            can_manage_members=is_manager,
            can_manage_kb=is_manager,
            can_confirm_assets=is_manager,
        ),
        counts=ProjectOverviewCounts(
            material_count=material.total,
            asset_count=assets.total,
            pending_confirmation_count=pending_confirmation,
            pending_review_count=pending_review,
            original_access_request_count=pending_access,
        ),
        knowledge_base=ProjectOverviewKbStatus(
            configured=mapping is not None,
            status=mapping.status if mapping is not None else None,
        ),
        members=members,
        recent_activity=[
            ProjectOverviewActivity(
                asset_id=item.id,
                title=item.title,
                zone=item.zone,
                asset_type=item.asset_type,
                confidentiality_level=item.confidentiality_level,
                updated_at=item.updated_at,
            )
            for item in recent.items
        ],
    )
