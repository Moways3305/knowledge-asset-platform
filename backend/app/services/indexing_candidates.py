"""Shared, safety-bounded eligibility rules for indexing operation candidates."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.schemas.enums import AssetStatus, KnowledgeScope


def scope_conditions(
    scope: str | None,
    project_id: str | uuid.UUID | None,
) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    if scope and scope != "all":
        conditions.append(KnowledgeAsset.scope == scope)
    if scope == KnowledgeScope.project.value and project_id is not None:
        conditions.append(KnowledgeAsset.project_id == uuid.UUID(str(project_id)))
    return conditions


def reparse_candidate_conditions(
    *,
    scope: str | None,
    project_id: str | uuid.UUID | None,
    parse_statuses: Sequence[str],
) -> list[ColumnElement[bool]]:
    """Return the single source of truth for assets eligible for reparse."""
    return [
        KnowledgeAssetVersion.version_status == "active",
        KnowledgeAsset.asset_status != AssetStatus.deleted.value,
        KnowledgeAssetVersion.index_status == "indexed",
        KnowledgeAssetVersion.weknora_doc_id.is_not(None),
        KnowledgeAssetVersion.weknora_parse_status.in_(tuple(parse_statuses)),
        *scope_conditions(scope, project_id),
    ]


async def count_reparse_candidates(
    session: AsyncSession,
    *,
    scope: str | None = "all",
    project_id: str | uuid.UUID | None = None,
    parse_statuses: Sequence[str] = ("failed", "pending"),
) -> int:
    conditions = reparse_candidate_conditions(
        scope=scope,
        project_id=project_id,
        parse_statuses=parse_statuses,
    )
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(KnowledgeAssetVersion)
                .join(KnowledgeAsset, KnowledgeAssetVersion.asset_id == KnowledgeAsset.id)
                .where(*conditions)
            )
        ).scalar()
        or 0
    )
