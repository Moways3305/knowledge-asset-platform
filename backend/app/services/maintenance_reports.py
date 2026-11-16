"""Run-specific reporting, with live permission checks before every projection."""

from sqlalchemy import func, select, update

from app.db.utils import utc_now
from app.models.knowledge import KnowledgeAsset
from app.models.maintenance_agent import MaintenanceRun, MaintenanceRunItem
from app.schemas.maintenance_agent import RunDetail, RunItemOut, RunOut, ScanSettings, ScopeOut
from app.services import maintenance_access as access


async def assess_scope(session, caller, project_id, *, asset_id=None, at=None):
    at = at or utc_now()
    query = select(KnowledgeAsset.asset_status, func.count()).where(
        KnowledgeAsset.scope == ("project" if project_id else "company"),
        KnowledgeAsset.project_id == project_id if project_id else True,
        KnowledgeAsset.deleted_at.is_(None),
        KnowledgeAsset.asset_status != "deleted",
        KnowledgeAsset.created_at <= at,
        access.manager_filter(caller, include_inactive=True),
    )
    if asset_id:
        query = query.where(KnowledgeAsset.id == asset_id)
    counts = dict((await session.execute(query.group_by(KnowledgeAsset.asset_status))).all())
    excluded = {}
    for status, count in counts.items():
        if status not in {"active", "needs_update"}:
            reason = status if status in {"archived", "deprecated", "processing"} else "inactive"
            excluded[reason] = excluded.get(reason, 0) + count
    return ScopeOut(
        assessed_at=at,
        visible_count=sum(counts.values()),
        target_count=sum(counts.get(s, 0) for s in ("active", "needs_update")),
        excluded_counts=excluded,
    )


async def seed_targets(session, run, policy, caller, *, retry_run_id=None):
    """Freeze target membership in the same transaction as run creation."""
    cursor = None
    total = 0
    prior = await session.get(MaintenanceRun, retry_run_id) if retry_run_id else None
    while True:
        query = select(KnowledgeAsset.id).where(
            access.scope_filter(policy.project_id),
            access.manager_filter(caller),
            KnowledgeAsset.created_at <= run.started_at,
        )
        if run.target_asset_id:
            query = query.where(KnowledgeAsset.id == run.target_asset_id)
        if retry_run_id:
            query = query.where(
                KnowledgeAsset.id.in_(
                    select(MaintenanceRunItem.asset_id).where(
                        MaintenanceRunItem.run_id == retry_run_id,
                        MaintenanceRunItem.status.in_(["incomplete", "skipped"]),
                    )
                )
            )
        if cursor:
            query = query.where(KnowledgeAsset.id > cursor)
        ids = (await session.scalars(query.order_by(KnowledgeAsset.id).limit(500))).all()
        if not ids:
            break
        previous = {}
        if prior and prior.policy_revision == run.policy_revision:
            previous = {
                row.asset_id: row.work_state
                for row in (
                    await session.scalars(
                        select(MaintenanceRunItem).where(
                            MaintenanceRunItem.run_id == prior.id,
                            MaintenanceRunItem.asset_id.in_(ids),
                        )
                    )
                ).all()
            }
        for key in ids:
            from copy import deepcopy

            work = deepcopy(previous.get(key))
            if work:
                work["resuming"] = True
                if work.get("quality_result") not in {"complete", "unchanged"}:
                    work["quality_done"] = False
                    work.pop("quality_result", None)
                work.setdefault("progress", {})["retry_attempt"] = 0
            session.add(MaintenanceRunItem(run_id=run.id, asset_id=key, work_state=work))
        await session.flush()
        total += len(ids)
        cursor = ids[-1]
    run.target_count = total
    scope = await assess_scope(
        session, caller, policy.project_id, asset_id=run.target_asset_id, at=run.started_at
    )
    run.scope_snapshot = {
        **scope.model_dump(mode="json"),
        "target_count": total,
        "content_authorized": policy.content_authorized,
        "settings": policy.settings,
    }
    if not total:
        run.status, run.finished_at = "empty", run.started_at
        run.reasons = {"no_eligible_assets": 1}


async def project_detail(session, caller, policy, run, *, page=1, status=None):
    query = (
        select(MaintenanceRunItem, KnowledgeAsset)
        .join(KnowledgeAsset, KnowledgeAsset.id == MaintenanceRunItem.asset_id)
        .where(
            MaintenanceRunItem.run_id == run.id,
            access.manager_filter(caller, include_inactive=True),
            KnowledgeAsset.scope == ("project" if policy.project_id else "company"),
            KnowledgeAsset.project_id == policy.project_id if policy.project_id else True,
            KnowledgeAsset.deleted_at.is_(None),
            KnowledgeAsset.asset_status != "deleted",
        )
    )
    if status:
        query = query.where(MaintenanceRunItem.status == status)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await session.execute(
            query.order_by(MaintenanceRunItem.asset_id).offset((page - 1) * 25).limit(25)
        )
    ).all()
    items = []
    for item, asset in rows:
        # No historical title/body or related-asset identifiers cross this endpoint.
        items.append(
            RunItemOut(
                asset_id=asset.id,
                title=asset.title,
                status=item.status,
                version_id=item.version_id,
                current_version_matches=item.version_id == asset.current_version_id,
                coverage=item.coverage,
                findings=item.findings,
                reasons=item.reasons,
                checked_at=item.checked_at,
                progress={
                    k: int(v)
                    for k, v in (item.work_state or {}).get("progress", {}).items()
                    if k
                    in {
                        "body_checked",
                        "body_total",
                        "comparison_checked",
                        "comparison_total",
                        "segments_checked",
                        "retry_attempt",
                    }
                },
            )
        )
    snapshot = run.scope_snapshot
    return RunDetail(
        **RunOut.model_validate(run, from_attributes=True).model_dump(),
        library_key=policy.library_key,
        historical_details_available=snapshot is not None,
        scope_snapshot=ScopeOut(**snapshot) if snapshot else None,
        current_scope=await assess_scope(
            session, caller, policy.project_id, asset_id=run.target_asset_id
        ),
        content_authorized=snapshot["content_authorized"] if snapshot else None,
        settings=ScanSettings(**snapshot["settings"]) if snapshot else None,
        items=items,
        total=total,
        page=page,
    )


async def cancel_pending(session, run, reason, now):
    result = await session.execute(
        update(MaintenanceRunItem)
        .where(MaintenanceRunItem.run_id == run.id, MaintenanceRunItem.status == "pending")
        .values(status="skipped", reasons=[reason], checked_at=now)
    )
    run.skipped_count += result.rowcount
    run.reasons = {**run.reasons, reason: max(1, result.rowcount)}
