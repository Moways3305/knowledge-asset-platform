"""Application workflow for an approved project ingest review."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.review import ReviewTask
from app.schemas.permission import CallerContext
from app.schemas.review import ReviewActionResponse
from app.services import ingest
from app.services.storage import LocalFileStorage
from app.services.weknora_client import NullWeKnoraClient, WeKnoraClient


async def execute(
    session: AsyncSession,
    caller: CallerContext,
    review: ReviewTask,
    comment: str | None,
    trace_id: str,
    *,
    storage: LocalFileStorage,
    weknora: WeKnoraClient | NullWeKnoraClient,
) -> ReviewActionResponse:
    """Coordinate the existing assetization command behind an application boundary."""
    return await ingest.approve_project_ingest_review(
        session,
        caller,
        review,
        comment,
        trace_id,
        storage=storage,
        weknora=weknora,
    )
