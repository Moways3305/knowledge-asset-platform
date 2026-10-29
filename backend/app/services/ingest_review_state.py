"""Keep terminal review facts authoritative for historical upload read models."""

import uuid
from collections.abc import Sequence

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingest import IngestTask
from app.models.review import ReviewTask


def effective_status(task: IngestTask, review: ReviewTask | None = None) -> str:
    if task.cancel_requested or task.status == "cancelled":
        return "cancelled"
    if (
        task.result_asset_id is None
        and review is not None
        and review.status in {"rejected", "cancelled"}
    ):
        return review.status
    return task.status


def require_open_review(status: str) -> None:
    if status in {"rejected", "cancelled", "approved"}:
        message = (
            "该入库申请已被拒绝，请根据审核意见修改后重新上传。"
            if status == "rejected"
            else "该入库申请已取消，请重新上传。"
            if status == "cancelled"
            else "该入库申请已审核通过，不可重复提交。"
        )
        raise HTTPException(
            409, detail={"denied_reason": f"ingest_review_{status}", "message": message}
        )


async def reviews_by_task(
    session: AsyncSession, tasks: Sequence[IngestTask]
) -> dict[uuid.UUID, ReviewTask]:
    if not tasks:
        return {}
    rows = await session.scalars(
        select(ReviewTask).where(ReviewTask.source_ingest_task_id.in_([task.id for task in tasks]))
    )
    return {row.source_ingest_task_id: row for row in rows if row.source_ingest_task_id is not None}
