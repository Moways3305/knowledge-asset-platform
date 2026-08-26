"""Review event publication; payloads are stable and content-free."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.review import ReviewTask
from app.services import domain_events


async def publish_action_required(session: AsyncSession, task: ReviewTask) -> None:
    await domain_events.publish(
        session,
        domain_events.DomainEvent(
            event_type=domain_events.REVIEW_ACTION_REQUIRED,
            aggregate_type="review",
            aggregate_id=task.id,
            payload=domain_events.safe_payload(
                review_id=task.id,
                project_id=task.target_project_id,
                review_type=task.review_type,
                status=task.status,
            ),
            idempotency_key=f"review-action-required:{task.id}:{task.status}",
        ),
    )


async def publish_decided(session: AsyncSession, task: ReviewTask) -> None:
    await domain_events.publish(
        session,
        domain_events.DomainEvent(
            event_type=domain_events.REVIEW_DECIDED,
            aggregate_type="review",
            aggregate_id=task.id,
            payload=domain_events.safe_payload(
                review_id=task.id,
                project_id=task.target_project_id,
                decision=task.status,
                status=task.status,
            ),
            idempotency_key=f"review-decided:{task.id}:{task.status}",
        ),
    )
