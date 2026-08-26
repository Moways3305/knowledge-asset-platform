"""Commands for creating the review boundary of a project ingest submission."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import ProjectMember
from app.models.ingest import IngestTask
from app.models.review import ReviewTask
from app.schemas.enums import (
    AuditAction,
    AuditLogType,
    KnowledgeScope,
    MemberStatus,
    ProjectRole,
    ReviewTaskStatus,
    ReviewType,
)
from app.schemas.ingest import IngestConfirmRequest
from app.schemas.permission import CallerContext
from app.services import audit as audit_service
from app.services import domain_events
from app.worker.enqueue import enqueue_outbox_delivery


async def create_or_get_project_ingest_review(
    session: AsyncSession,
    caller: CallerContext,
    ingest_task: IngestTask,
    request: IngestConfirmRequest,
    trace_id: str,
) -> ReviewTask:
    """Idempotently turn a validated submission into an actionable review fact."""
    existing = (
        await session.execute(
            select(ReviewTask).where(ReviewTask.source_ingest_task_id == ingest_task.id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    if request.target_project_id is None:
        raise RuntimeError("project ingest review requires target_project_id")
    reviewer_id = (
        (
            await session.execute(
                select(ProjectMember.user_id).where(
                    ProjectMember.project_id == request.target_project_id,
                    ProjectMember.project_role == ProjectRole.project_manager.value,
                    ProjectMember.status == MemberStatus.active.value,
                )
            )
        )
        .scalars()
        .first()
    )
    review = ReviewTask(
        review_type=ReviewType.project_ingest_approval.value,
        trigger_source="ingest_confirm",
        source_ingest_task_id=ingest_task.id,
        confirmation_snapshot=request.model_dump(mode="json"),
        target_project_id=request.target_project_id,
        target_scope=KnowledgeScope.project.value,
        status=ReviewTaskStatus.pending_reviewer.value,
        reviewer_user_id=reviewer_id,
        submitted_by=caller.user_id,
    )
    session.add(review)
    ingest_task.status = "waiting_review"
    ingest_task.target_scope = KnowledgeScope.project.value
    ingest_task.target_project_id = request.target_project_id
    ingest_task.target_zone = request.target_zone.value
    if ingest_task.ai_result is not None:
        ingest_task.ai_result.human_corrected = True
        ingest_task.ai_result.corrected_title = request.title
        ingest_task.ai_result.corrected_summary = request.summary
        ingest_task.ai_result.corrected_tags = request.tags
    await session.flush()
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.review_created.value,
        trace_id=trace_id,
        target_type="review_task",
        target_id=review.id,
        after={
            "review_type": review.review_type,
            "status": review.status,
            "target_scope": review.target_scope,
        },
        project_id=request.target_project_id,
    )
    await domain_events.publish(
        session,
        domain_events.DomainEvent(
            event_type=domain_events.REVIEW_ACTION_REQUIRED,
            aggregate_type="review",
            aggregate_id=review.id,
            payload=domain_events.safe_payload(
                review_id=review.id,
                project_id=review.target_project_id,
                review_type=review.review_type,
                status=review.status,
            ),
            idempotency_key=f"review-action-required:{review.id}:{review.status}",
        ),
    )
    review_id = review.id
    await session.commit()
    await enqueue_outbox_delivery(session)
    persisted = await session.get(ReviewTask, review_id)
    if persisted is None:  # pragma: no cover - committed primary key invariant
        raise RuntimeError("committed review task is missing")
    return persisted
