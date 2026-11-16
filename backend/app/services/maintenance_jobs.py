"""Durable single-flight scans with fenced leases and short DB transactions."""

import asyncio
import time
import uuid
from datetime import timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import aliased

from app.db.utils import utc_now
from app.models.knowledge import KnowledgeAsset
from app.models.maintenance_agent import (
    MaintenanceCheck,
    MaintenanceDigest,
    MaintenanceIssue,
    MaintenanceIssueEvent,
    MaintenancePolicy,
    MaintenanceRun,
    MaintenanceRunItem,
)
from app.schemas.enums import AuditLogType
from app.schemas.maintenance_agent import ScanSettings
from app.services import audit, domain_events
from app.services import maintenance_access as access
from app.services.generation_models import resolve_generation_llm_client
from app.services.llm_client import NullLLMClient
from app.services.maintenance_reports import seed_targets
from app.services.maintenance_rules import analyze, deterministic, digest, finding
from app.services.maintenance_snapshots import capture
from app.services.storage import get_storage

BEIJING = timezone(timedelta(hours=8))
ACTIVE = {"open", "in_progress", "awaiting_recheck"}
TECHNICAL_FAILURES = {
    "file_unavailable",
    "parse_failed",
    "index_failed",
    "model_unavailable",
    "model_response_incomplete",
    "model_evidence_invalid",
    "body_unavailable",
    "check_incomplete",
}


async def start_run(session, policy, *, kind="full", asset_id=None):
    """Caller holds the policy row lock; repeated requests share its active run."""
    active = await session.scalar(
        select(MaintenanceRun)
        .where(
            MaintenanceRun.policy_id == policy.id, MaintenanceRun.status.in_(["queued", "running"])
        )
        .order_by(MaintenanceRun.started_at)
        .limit(1)
    )
    if active and asset_id is None:
        return active
    if active and asset_id:
        queued = await session.scalar(
            select(MaintenanceRun)
            .where(
                MaintenanceRun.policy_id == policy.id,
                MaintenanceRun.target_asset_id == asset_id,
                MaintenanceRun.status == "queued",
            )
            .limit(1)
        )
        if queued:
            return queued
        pending = await session.scalar(
            select(func.count())
            .select_from(MaintenanceRun)
            .where(
                MaintenanceRun.policy_id == policy.id,
                MaintenanceRun.status.in_(["queued", "running"]),
            )
        )
        if pending >= 100:
            raise access.reject(409, "待复检队列已满，请稍后重试")
    caller = await access.actor_context(session, policy.authorized_by, policy.authorized_role)
    if not caller or not access.library_allowed(caller, policy.project_id):
        policy.last_error = "authorization_expired"
        return None
    now = utc_now()
    clauses = [
        access.scope_filter(policy.project_id),
        access.manager_filter(caller),
        KnowledgeAsset.created_at <= now,
    ]
    if asset_id:
        clauses.append(KnowledgeAsset.id == asset_id)
    count = await session.scalar(select(func.count()).select_from(KnowledgeAsset).where(*clauses))
    row = MaintenanceRun(
        policy_id=policy.id,
        policy_revision=policy.revision,
        kind=kind,
        target_asset_id=asset_id,
        target_count=count,
        started_at=now,
        includes_l5=caller.can_discover_l5,
    )
    session.add(row)
    policy.last_error = None
    await session.flush()
    await seed_targets(session, row, policy, caller)
    return row


async def schedule(session, now=None):
    now = now or utc_now()
    local = now.astimezone(BEIJING)
    policies = (
        await session.scalars(
            select(MaintenancePolicy)
            .where(
                MaintenancePolicy.enabled.is_(True),
                or_(
                    MaintenancePolicy.last_scheduled_day.is_(None),
                    MaintenancePolicy.last_scheduled_day != local.date().isoformat(),
                ),
            )
            .order_by(
                MaintenancePolicy.schedule_checked_at.asc().nullsfirst(), MaintenancePolicy.id
            )
            .limit(30)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for policy in policies:
        policy.schedule_checked_at = now
        settings = ScanSettings(**policy.settings)
        if local.hour < settings.daily_hour:
            continue
        full = (
            not policy.last_full_at
            or (local.date() - access.stamp(policy.last_full_at).astimezone(BEIJING).date()).days
            >= 7
            or local.weekday() == settings.weekly_day
        )
        run = await start_run(session, policy, kind="full" if full else "incremental")
        if run:
            policy.last_scheduled_day = local.date().isoformat()
    await session.commit()


async def _digest(session, issue, recipient_id, settings, now):
    day = now.astimezone(BEIJING).date().isoformat()
    due_at = now.astimezone(BEIJING).replace(
        hour=settings.digest_hour, minute=0, second=0, microsecond=0
    )
    row = await session.scalar(
        select(MaintenanceDigest)
        .where(MaintenanceDigest.recipient_id == recipient_id, MaintenanceDigest.day == day)
        .with_for_update()
    )
    if row is None:
        # Different library runs may reach the same recipient concurrently.
        dialect = session.bind.dialect.name
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        await session.execute(
            insert(MaintenanceDigest)
            .values(
                id=uuid.uuid4(),
                recipient_id=recipient_id,
                day=day,
                issue_ids=[],
                created_at=now,
                due_at=due_at,
            )
            .on_conflict_do_nothing(index_elements=["recipient_id", "day"])
        )
        row = await session.scalar(
            select(MaintenanceDigest)
            .where(MaintenanceDigest.recipient_id == recipient_id, MaintenanceDigest.day == day)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    row.due_at = max(access.stamp(row.due_at), due_at)
    # The notification is a generic daily hint, with live task visibility on read.
    if str(issue.id) not in row.issue_ids and len(row.issue_ids) < 500:
        row.issue_ids = [*row.issue_ids, str(issue.id)]


async def _publish_digest(session, row, now):
    if not row.issue_ids:
        return
    await domain_events.publish(
        session,
        domain_events.DomainEvent(
            event_type=domain_events.MAINTENANCE_DIGEST_READY,
            aggregate_type="maintenance_digest",
            aggregate_id=row.id,
            payload={"recipient_id": str(row.recipient_id)},
            idempotency_key=f"maintenance.digest:{row.id}",
        ),
    )
    row.published_at = now


async def flush_digests(session, now=None):
    now = now or utc_now()
    rows = (
        await session.scalars(
            select(MaintenanceDigest)
            .where(MaintenanceDigest.published_at.is_(None), MaintenanceDigest.due_at <= now)
            .order_by(MaintenanceDigest.created_at)
            .limit(50)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for row in rows:
        issues = (
            await session.scalars(
                select(MaintenanceIssue).where(
                    MaintenanceIssue.id.in_([uuid.UUID(x) for x in row.issue_ids])
                )
            )
        ).all()
        policies = (
            await session.scalars(
                select(MaintenancePolicy).where(
                    MaintenancePolicy.id.in_({i.policy_id for i in issues})
                )
            )
        ).all()
        hour = max((ScanSettings(**p.settings).digest_hour for p in policies), default=9)
        if (
            row.day < now.astimezone(BEIJING).date().isoformat()
            or now.astimezone(BEIJING).hour >= hour
        ):
            await _publish_digest(session, row, now)
    await session.commit()


async def persist_findings(session, policy, asset, snapshot, findings, now):
    existing = (
        await session.scalars(
            select(MaintenanceIssue)
            .where(MaintenanceIssue.policy_id == policy.id, MaintenanceIssue.asset_id == asset.id)
            .with_for_update()
        )
    ).all()
    by_key = {(i.rule, i.related_key): i for i in existing}
    seen = set()
    settings = ScanSettings(**policy.settings)
    for fact in findings:
        key = (fact["rule"], fact["related_key"])
        if key in seen:
            continue
        seen.add(key)
        # Content decisions apply only to the exact checked revision/fact.
        related = next((c for c in snapshot["candidates"] if c["id"] == fact["related_key"]), None)
        if related:
            fact["evidence"] = {**fact["evidence"], "related_version_id": related["version_id"]}
        fingerprint = digest(
            [
                fact["fingerprint"],
                str(asset.current_version_id),
                [snapshot["body"], snapshot["summary"]] if fact["suspected"] else None,
                related,
            ]
        )
        row = by_key.get(key)
        if row is None:
            row = MaintenanceIssue(
                id=uuid.uuid4(),
                policy_id=policy.id,
                asset_id=asset.id,
                version_id=asset.current_version_id,
                related_asset_id=uuid.UUID(fact["related_key"]) if fact["related_key"] else None,
                fingerprint=fingerprint,
                first_seen_at=now,
                last_seen_at=now,
                updated_at=now,
                status="open",
                **{k: v for k, v in fact.items() if k != "fingerprint"},
            )
            session.add(row)
            existing.append(row)
            session.add(MaintenanceIssueEvent(issue_id=row.id, action="detected"))
        else:
            changed = row.fingerprint != fingerprint
            reopen = (
                changed
                or row.status in {"not_applicable", "awaiting_recheck"}
                or (row.status == "resolved" and not row.suspected)
                or (row.status == "snoozed" and access.stamp(row.snooze_until) <= now)
            )
            if reopen:
                row.status, row.snooze_until = "open", None
                session.add(MaintenanceIssueEvent(issue_id=row.id, action="reopened"))
                row.updated_at = now
            row.fingerprint, row.evidence, row.version_id = (
                fingerprint,
                fact["evidence"],
                asset.current_version_id,
            )
            row.last_seen_at = now
    for row in existing:
        if row.status == "awaiting_recheck" and snapshot["coverage"].get(row.category) not in {
            "complete",
            "unchanged",
        }:
            row.status, row.updated_at = "open", now
            session.add(
                MaintenanceIssueEvent(
                    issue_id=row.id,
                    action="recheck_incomplete",
                    reason="本次复检未完成，请查看巡检记录并重试。",
                )
            )
        if row.status == "snoozed" and access.stamp(row.snooze_until) <= now:
            row.status, row.snooze_until, row.updated_at = "open", None, now
            session.add(MaintenanceIssueEvent(issue_id=row.id, action="reopened"))
        if (
            (row.rule, row.related_key) not in seen
            and snapshot["coverage"].get(row.category) == "complete"
            and row.status not in {"false_positive", "resolved", "not_applicable"}
        ):
            row.status, row.updated_at, row.snooze_until = "resolved", now, None
            session.add(MaintenanceIssueEvent(issue_id=row.id, action="recheck_passed"))
        if row.status in ACTIVE:
            for recipient in snapshot["responsible"]:
                await _digest(session, row, uuid.UUID(recipient["id"]), settings, now)
    check = await session.scalar(
        select(MaintenanceCheck).where(
            MaintenanceCheck.policy_id == policy.id, MaintenanceCheck.asset_id == asset.id
        )
    )
    if check is None:
        check = MaintenanceCheck(policy_id=policy.id, asset_id=asset.id)
        session.add(check)
    check.fingerprint, check.policy_revision, check.coverage, check.checked_at = (
        snapshot["fingerprint"],
        policy.revision,
        {k: "complete" if v == "unchanged" else v for k, v in snapshot["coverage"].items()},
        now,
    )


def inspect_files(storage, refs):
    if not refs:
        return False
    for ref in refs:
        try:
            if not storage.inspect(ref).available:
                return False
            with storage.resolve_path(ref).open("rb") as source:
                if not source.read(1):
                    return False
        except Exception:
            return False
    return True


async def process_one(maker, *, storage=None, client=None):
    """One asset per claim. The run cursor advances with the issues in one commit."""
    now, token = utc_now(), str(uuid.uuid4())
    async with maker() as session:
        other_run = aliased(MaintenanceRun)
        run = await session.scalar(
            select(MaintenanceRun)
            .where(
                MaintenanceRun.status.in_(["queued", "running"]),
                or_(MaintenanceRun.lease_until.is_(None), MaintenanceRun.lease_until < now),
                ~select(other_run.id)
                .where(
                    other_run.policy_id == MaintenanceRun.policy_id,
                    other_run.id != MaintenanceRun.id,
                    other_run.status == "running",
                    other_run.lease_until >= now,
                )
                .exists(),
            )
            .order_by(MaintenanceRun.last_progress_at, MaintenanceRun.started_at)
            .limit(1)
        )
        if not run:
            return False
        policy = await session.scalar(
            select(MaintenancePolicy)
            .where(MaintenancePolicy.id == run.policy_id)
            .with_for_update(skip_locked=True)
        )
        if not policy:
            return False
        run = await session.scalar(
            select(MaintenanceRun)
            .where(MaintenanceRun.id == run.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if run.status not in {"queued", "running"} or (
            run.lease_until and access.stamp(run.lease_until) >= now
        ):
            return False
        if await session.scalar(
            select(MaintenanceRun.id)
            .where(
                MaintenanceRun.policy_id == policy.id,
                MaintenanceRun.id != run.id,
                MaintenanceRun.status == "running",
                MaintenanceRun.lease_until >= now,
            )
            .limit(1)
        ):
            return False
        run.last_progress_at = now
        caller = await access.actor_context(session, policy.authorized_by, policy.authorized_role)
        if (
            policy.revision != run.policy_revision
            or not caller
            or not access.library_allowed(caller, policy.project_id)
        ):
            run.status, run.finished_at, run.reasons = (
                "cancelled",
                now,
                {"authorization_changed": 1},
            )
            policy.last_error = (
                "authorization_expired" if policy.revision == run.policy_revision else None
            )
            await session.commit()
            return True
        if run.scope_snapshot is not None:
            query = (
                select(KnowledgeAsset)
                .join(MaintenanceRunItem, MaintenanceRunItem.asset_id == KnowledgeAsset.id)
                .where(MaintenanceRunItem.run_id == run.id, MaintenanceRunItem.status == "pending")
            )
        else:
            # An in-flight run from the previous release keeps its old cursor semantics.
            query = select(KnowledgeAsset).where(
                access.scope_filter(policy.project_id),
                access.manager_filter(caller),
                KnowledgeAsset.created_at <= run.started_at,
            )
            if run.cursor:
                query = query.where(KnowledgeAsset.id > run.cursor)
            if run.target_asset_id:
                query = query.where(KnowledgeAsset.id == run.target_asset_id)
        asset = await session.scalar(query.order_by(KnowledgeAsset.id).limit(1))
        if asset is None:
            run.status = "partial" if run.incomplete_count or run.skipped_count else "completed"
            run.finished_at = now
            run.skipped_count = max(
                0, run.target_count - run.completed_count - run.incomplete_count
            )
            if run.skipped_count:
                run.reasons = {**run.reasons, "asset_out_of_scope": run.skipped_count}
                run.status = "partial"
            if run.target_count == 0:
                run.status = "empty"
                run.reasons = {**run.reasons, "no_eligible_assets": 1}
            if run.kind == "full":
                policy.last_full_at = now
            if TECHNICAL_FAILURES.intersection(run.reasons):
                await domain_events.publish(
                    session,
                    domain_events.DomainEvent(
                        event_type=domain_events.MAINTENANCE_OPS_READY,
                        aggregate_type="maintenance_run",
                        aggregate_id=run.id,
                        payload={"status": run.status},
                        idempotency_key=f"maintenance.ops:{run.id}",
                    ),
                )
            await session.commit()
            return True
        run.claim_token, run.lease_until, run.status = token, now + timedelta(minutes=3), "running"
        settings = ScanSettings(**policy.settings)
        snapshot, error = await capture(session, policy, asset, settings, now)
        run_id, asset_id, kind = run.id, asset.id, run.kind
        llm = client or await resolve_generation_llm_client(session, model_ref=settings.model_ref)
        if snapshot and snapshot["allowed"]:
            await audit.record_system_event(
                session,
                log_type=AuditLogType.operation,
                action="maintenance.content_check_requested",
                trace_id=str(run.id),
                target_type="knowledge_asset",
                target_id=asset.id,
                risk_level="high" if asset.confidentiality_level == "L5" else None,
                extra={
                    "policy_id": str(policy.id),
                    "authorized_by": str(policy.authorized_by),
                    "version_id": str(asset.current_version_id),
                },
            )
        await session.commit()
    # No connection/transaction is held during disk or model calls.
    findings = []
    if snapshot:
        findings = deterministic(snapshot, settings, now)
        if snapshot["allowed"] and snapshot["coverage"]["availability"] != "file_limit":
            readable = await asyncio.to_thread(
                inspect_files, storage or get_storage(), snapshot["refs"]
            )
            if not readable:
                findings.append(finding("file_unavailable"))
        if snapshot["coverage"]["quality"] == "complete":
            if isinstance(llm, NullLLMClient):
                snapshot["coverage"]["quality"] = "model_unavailable"
            elif kind == "incremental" and snapshot["unchanged"]:
                snapshot["coverage"]["quality"] = "unchanged"
            else:
                quality, reason = await analyze(snapshot, settings, llm)
                findings.extend(quality)
                if reason:
                    snapshot["coverage"]["quality"] = reason
    async with maker() as session:
        run_reference = await session.get(MaintenanceRun, run_id)
        if not run_reference:
            return True
        policy = await session.scalar(
            select(MaintenancePolicy)
            .where(MaintenancePolicy.id == run_reference.policy_id)
            .with_for_update()
        )
        run = await session.scalar(
            select(MaintenanceRun)
            .where(
                MaintenanceRun.id == run_id,
                MaintenanceRun.claim_token == token,
                MaintenanceRun.status == "running",
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not run or access.stamp(run.lease_until) < utc_now():
            return True
        asset = await session.scalar(
            select(KnowledgeAsset).where(KnowledgeAsset.id == asset_id).with_for_update()
        )
        fresh, fresh_error = await capture(session, policy, asset, settings, now)
        if policy.revision != run.policy_revision or (
            snapshot
            and (
                not fresh
                or fresh["fingerprint"] != snapshot["fingerprint"]
                or fresh["candidate_fingerprint"] != snapshot["candidate_fingerprint"]
            )
        ):
            error = fresh_error or "asset_changed_during_check"
            snapshot = None
        item = await session.scalar(
            select(MaintenanceRunItem).where(
                MaintenanceRunItem.run_id == run.id, MaintenanceRunItem.asset_id == asset_id
            )
        )
        if snapshot:
            await persist_findings(session, policy, asset, snapshot, findings, now)
            technical = {
                f["rule"]
                for f in findings
                if f["rule"] in {"file_unavailable", "parse_failed", "index_failed"}
            }
            run.reasons = {**run.reasons, **{r: run.reasons.get(r, 0) + 1 for r in technical}}
            reasons = sorted(
                set(x for x in snapshot["coverage"].values() if x not in {"complete", "unchanged"})
            )
            if reasons:
                run.incomplete_count += 1
                run.reasons = {**run.reasons, **{r: run.reasons.get(r, 0) + 1 for r in reasons}}
            else:
                run.completed_count += 1
            if item:
                item.status = "incomplete" if reasons else "completed"
                item.version_id = uuid.UUID(snapshot["facts"]["version_id"])
                item.coverage = snapshot["coverage"]
                item.findings = {
                    rule: sum(f["rule"] == rule for f in findings)
                    for rule in {f["rule"] for f in findings}
                }
                item.reasons = reasons
            if snapshot["allowed"]:
                await audit.record_system_event(
                    session,
                    log_type=AuditLogType.operation,
                    action="maintenance.content_checked",
                    trace_id=str(run.id),
                    target_type="knowledge_asset",
                    target_id=asset.id,
                    extra={
                        "policy_id": str(policy.id),
                        "authorized_by": str(policy.authorized_by),
                        "version_id": str(asset.current_version_id),
                    },
                )
        else:
            reason = error or fresh_error or "check_incomplete"
            if reason == "asset_out_of_scope":
                run.skipped_count += 1
            else:
                run.incomplete_count += 1
            run.reasons = {**run.reasons, reason: run.reasons.get(reason, 0) + 1}
            if item:
                item.status = "skipped" if reason == "asset_out_of_scope" else "incomplete"
                item.reasons = [reason]
        if item:
            item.checked_at = utc_now()
        run.cursor, run.claim_token, run.lease_until = asset_id, None, None
        run.last_progress_at = utc_now()
        await session.commit()
    return True


async def tick(maker):
    async with maker() as session:
        await retire_unavailable(session)
        await schedule(session)
        await flush_digests(session)
    started = time.monotonic()
    for _ in range(8):
        if not await process_one(maker) or time.monotonic() - started > 45:
            break


async def retire_unavailable(session):
    rows = (
        await session.scalars(
            select(MaintenanceIssue)
            .join(KnowledgeAsset, MaintenanceIssue.asset_id == KnowledgeAsset.id)
            .join(MaintenancePolicy, MaintenanceIssue.policy_id == MaintenancePolicy.id)
            .where(
                MaintenanceIssue.status != "not_applicable",
                or_(
                    KnowledgeAsset.deleted_at.is_not(None),
                    KnowledgeAsset.scope.notin_(["company", "project"]),
                    KnowledgeAsset.asset_status.notin_(["active", "needs_update"]),
                    (KnowledgeAsset.scope == "project")
                    & KnowledgeAsset.project_id.is_distinct_from(MaintenancePolicy.project_id),
                    (KnowledgeAsset.scope == "company") & MaintenancePolicy.project_id.is_not(None),
                ),
            )
            .order_by(MaintenanceIssue.id)
            .limit(100)
            .with_for_update(of=MaintenanceIssue, skip_locked=True)
        )
    ).all()
    for issue in rows:
        issue.status, issue.updated_at = "not_applicable", utc_now()
        session.add(MaintenanceIssueEvent(issue_id=issue.id, action="not_applicable"))
    await session.commit()
