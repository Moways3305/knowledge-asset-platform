"""Shared lock policy for personal metadata editors and detail projections."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeAsset
from app.models.review import PersonalKnowledgeSubmission, ReviewTask
from app.schemas.enums import KnowledgeScope, PersonalSubmissionType, ReviewTaskStatus


async def personal_asset_write_locked(session: AsyncSession, asset_id: uuid.UUID) -> bool:
    pending_task = (
        await session.execute(
            select(ReviewTask.id)
            .join(
                PersonalKnowledgeSubmission,
                PersonalKnowledgeSubmission.review_task_id == ReviewTask.id,
            )
            .where(
                PersonalKnowledgeSubmission.source_asset_id == asset_id,
                PersonalKnowledgeSubmission.submission_type
                == PersonalSubmissionType.submit_to_project.value,
                ReviewTask.status.in_(
                    {
                        ReviewTaskStatus.pending_evidence.value,
                        ReviewTaskStatus.pending_reviewer.value,
                        ReviewTaskStatus.approving.value,
                        ReviewTaskStatus.approval_failed.value,
                    }
                ),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if pending_task is not None:
        return True
    project_copy = (
        await session.execute(
            select(KnowledgeAsset.id)
            .where(
                KnowledgeAsset.source_asset_id == asset_id,
                KnowledgeAsset.scope == KnowledgeScope.project.value,
                KnowledgeAsset.asset_status == "active",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return project_copy is not None
