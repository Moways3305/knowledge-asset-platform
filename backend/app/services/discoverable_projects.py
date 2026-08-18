"""Authoritative project discovery for knowledge-library entry points.

This is deliberately separate from ``projects.list_projects``: that service is
the user's membership-backed project workspace list.  Knowledge discovery also
admits active non-member projects when at least one active project asset passes
the central discovery policy and any additional channel ceiling.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import and_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.identity import Project
from app.models.knowledge import KnowledgeAsset
from app.schemas.enums import ConfidentialityLevel, KnowledgeScope
from app.schemas.external_agent import ProjectAccessLabel, ProjectAccessMode
from app.schemas.permission import CallerContext
from app.services.permission import discovery_filter

MEMBER: ProjectAccessMode = "member"
SUMMARY_VISIBLE: ProjectAccessMode = "summary_visible"
_ACCESS_LABELS: dict[ProjectAccessMode, ProjectAccessLabel] = {
    MEMBER: "可查看资料",
    SUMMARY_VISIBLE: "摘要可见",
}


@dataclass(frozen=True, slots=True)
class DiscoverableProject:
    project_id: uuid.UUID
    name: str
    status: str
    access_mode: ProjectAccessMode

    @property
    def access_label(self) -> ProjectAccessLabel:
        return _ACCESS_LABELS[self.access_mode]


def discoverable_project_asset_filter(
    caller: CallerContext,
    *,
    additional_filter: ColumnElement[bool] | None = None,
) -> ColumnElement[bool]:
    """Asset existence evidence for non-member project discovery.

    Cross-project L5 is never valid project-existence evidence, including for a
    caller who may discover company-level L5. Keep this explicit in addition to
    ``discovery_filter`` so later policy changes cannot widen project discovery.
    """
    return and_(
        KnowledgeAsset.scope == KnowledgeScope.project.value,
        KnowledgeAsset.project_id.is_not(None),
        KnowledgeAsset.confidentiality_level != ConfidentialityLevel.L5.value,
        discovery_filter(caller),
        additional_filter if additional_filter is not None else true(),
    )


async def list_discoverable_projects(
    session: AsyncSession,
    caller: CallerContext,
    *,
    allowed_scope: str | None = None,
    allowed_project_id: uuid.UUID | None = None,
    asset_filter: ColumnElement[bool] | None = None,
) -> list[DiscoverableProject]:
    """Return active member projects plus evidence-backed summary projects.

    Member projects remain discoverable when empty. Non-member projects require
    at least one asset passing ``discovery_filter`` and ``asset_filter``. Results
    are stable: members first, then case-insensitive project name and UUID.
    """
    if allowed_scope not in (None, "all", KnowledgeScope.project.value):
        return []

    project_conditions = [Project.status == "active"]
    if allowed_project_id is not None:
        project_conditions.append(Project.id == allowed_project_id)

    member_ids = set(caller.active_project_ids)
    member_stmt = select(Project).where(*project_conditions, Project.id.in_(member_ids))
    members = list((await session.execute(member_stmt)).scalars().all()) if member_ids else []

    evidence = discoverable_project_asset_filter(caller, additional_filter=asset_filter)
    summary_stmt = (
        select(Project)
        .join(KnowledgeAsset, KnowledgeAsset.project_id == Project.id)
        .where(*project_conditions, evidence)
        .distinct()
    )
    if member_ids:
        summary_stmt = summary_stmt.where(Project.id.notin_(member_ids))
    summaries = list((await session.execute(summary_stmt)).scalars().all())

    def key(project: Project) -> tuple[str, str]:
        return ((project.name or "").casefold(), str(project.id))

    return [
        *[DiscoverableProject(p.id, p.name, p.status, MEMBER) for p in sorted(members, key=key)],
        *[
            DiscoverableProject(p.id, p.name, p.status, SUMMARY_VISIBLE)
            for p in sorted(summaries, key=key)
        ],
    ]


async def get_discoverable_project(
    session: AsyncSession,
    caller: CallerContext,
    project_id: uuid.UUID,
    *,
    allowed_scope: str | None = None,
    allowed_project_id: uuid.UUID | None = None,
    asset_filter: ColumnElement[bool] | None = None,
) -> DiscoverableProject | None:
    rows = await list_discoverable_projects(
        session,
        caller,
        allowed_scope=allowed_scope,
        allowed_project_id=allowed_project_id or project_id,
        asset_filter=asset_filter,
    )
    return next((row for row in rows if row.project_id == project_id), None)
