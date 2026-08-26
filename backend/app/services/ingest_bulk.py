"""Bulk-ingest recovery reads kept outside the HTTP adapter."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingest import IngestTask
from app.models.knowledge import KnowledgeAssetVersion
from app.schemas.ingest import IngestBulkConfirmItemResult


async def confirmed_task_result(
    session: AsyncSession, task_id: uuid.UUID
) -> IngestBulkConfirmItemResult | None:
    row = (
        await session.execute(
            select(IngestTask.result_asset_id, KnowledgeAssetVersion.index_status)
            .outerjoin(
                KnowledgeAssetVersion,
                KnowledgeAssetVersion.id == IngestTask.result_version_id,
            )
            .where(IngestTask.id == task_id)
        )
    ).one_or_none()
    if row is None or row.result_asset_id is None:
        return None
    return IngestBulkConfirmItemResult(
        item_id=task_id,
        status="succeeded",
        result_asset_id=row.result_asset_id,
        index_status=row.index_status,
    )
