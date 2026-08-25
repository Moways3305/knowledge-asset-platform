"""Authoritative knowledge-library project catalog.

Project folders are identity-safe navigation entries, not evidence that any
discoverable asset exists. Asset discovery, summaries, and originals remain
separate per-asset permission decisions.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Project
from app.schemas.enums import KnowledgeScope
from app.schemas.external_agent import ProjectAccessLabel, ProjectAccessMode
from app.schemas.permission import CallerContext

MEMBER: ProjectAccessMode = "member"
SUMMARY_VISIBLE: ProjectAccessMode = "summary_visible"
_ACCESS_LABELS: dict[ProjectAccessMode, ProjectAccessLabel] = {
    MEMBER: "可查看资料",
    SUMMARY_VISIBLE: "摘要可见",
}


@dataclass(frozen=True, slots=True)
class KnowledgeLibraryProject:
    project_id: uuid.UUID
    name: str
    status: str
    access_mode: ProjectAccessMode

    @property
    def access_label(self) -> ProjectAccessLabel:
        return _ACCESS_LABELS[self.access_mode]


async def list_knowledge_library_projects(
    session: AsyncSession,
    caller: CallerContext,
    *,
    allowed_scope: str | None = None,
    allowed_project_id: uuid.UUID | None = None,
) -> list[KnowledgeLibraryProject]:
    """Return every active project allowed by an optional channel project lock.

    Membership determines only the navigation label. It never determines
    whether the active project folder exists. Assets, versions, directories,
    ingest state, and indexes are intentionally absent from this query.
    """
    if not caller.is_active or not caller.is_business_user:
        return []
    if allowed_scope not in (None, "all", KnowledgeScope.project.value):
        return []

    conditions = [Project.status == "active"]
    if allowed_project_id is not None:
        conditions.append(Project.id == allowed_project_id)
    projects = list((await session.execute(select(Project).where(*conditions))).scalars().all())
    projects.sort(key=lambda project: ((project.name or "").casefold(), str(project.id)))
    member_ids = caller.active_project_ids
    return [
        KnowledgeLibraryProject(
            project_id=project.id,
            name=project.name,
            status=project.status,
            access_mode=MEMBER if project.id in member_ids else SUMMARY_VISIBLE,
        )
        for project in projects
    ]


async def get_knowledge_library_project(
    session: AsyncSession,
    caller: CallerContext,
    project_id: uuid.UUID,
    *,
    allowed_scope: str | None = None,
    allowed_project_id: uuid.UUID | None = None,
) -> KnowledgeLibraryProject | None:
    if allowed_project_id is not None and allowed_project_id != project_id:
        return None
    rows = await list_knowledge_library_projects(
        session,
        caller,
        allowed_scope=allowed_scope,
        allowed_project_id=project_id,
    )
    return rows[0] if rows else None
