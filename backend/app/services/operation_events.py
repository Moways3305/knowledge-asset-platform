"""Content-free Outbox events for operations jobs and bounded alert signals."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.indexing_job import IndexingOperationJob
from app.services import domain_events


async def publish_job_finished(session: AsyncSession, job: IndexingOperationJob) -> None:
    await domain_events.publish(
        session,
        domain_events.DomainEvent(
            event_type=domain_events.OPERATION_JOB_FINISHED,
            aggregate_type="indexing_operation_job",
            aggregate_id=job.id,
            payload=domain_events.safe_payload(
                job_id=job.id,
                status=job.status,
                operation_type=job.operation_type,
            ),
            idempotency_key=f"operation-job-finished:{job.id}:{job.status}",
        ),
    )


async def publish_ops_signal(
    session: AsyncSession,
    *,
    signal: str,
    count: int,
    hour_bucket: str,
    audit_event_id: uuid.UUID,
    alert_rule_id: uuid.UUID,
) -> None:
    aggregate_id = uuid.uuid5(uuid.NAMESPACE_URL, f"kap:ops:{signal}")
    await domain_events.publish(
        session,
        domain_events.DomainEvent(
            event_type=domain_events.OPS_SIGNAL_RAISED,
            aggregate_type="ops_signal",
            aggregate_id=aggregate_id,
            payload=domain_events.safe_payload(
                signal=signal,
                count=str(count),
                hour_bucket=hour_bucket,
                audit_event_id=audit_event_id,
                alert_rule_id=alert_rule_id,
            ),
            idempotency_key=f"ops-signal:{signal}:{hour_bucket}",
        ),
    )


async def publish_local_notification(
    session: AsyncSession,
    *,
    notice_type: str,
    recipient_id: uuid.UUID,
    asset_id: uuid.UUID,
    audit_event_id: uuid.UUID,
) -> None:
    await domain_events.publish(
        session,
        domain_events.DomainEvent(
            event_type=domain_events.LOCAL_NOTIFICATION_REQUESTED,
            aggregate_type="knowledge_asset",
            aggregate_id=asset_id,
            payload=domain_events.safe_payload(
                notice_type=notice_type,
                recipient_id=recipient_id,
                asset_id=asset_id,
                audit_event_id=audit_event_id,
            ),
            idempotency_key=(f"local-notification:{notice_type}:{audit_event_id}:{recipient_id}"),
        ),
    )
