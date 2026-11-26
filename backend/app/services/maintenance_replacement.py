"""Continue outstanding findings when an approved replacement archives its source."""

from sqlalchemy import and_, delete, or_, select, update

from app.db.utils import utc_now
from app.models.knowledge import KnowledgeAsset
from app.models.maintenance_agent import (
    MaintenanceDigestIssue,
    MaintenanceIssue,
    MaintenanceIssueAlias,
    MaintenanceIssueEvent,
    MaintenancePolicy,
)
from app.services.maintenance_jobs import start_run
from app.services.maintenance_rules import ACTIVE, RETIRED


async def lock_policy(session, asset_id):
    # Same order as worker finalization and manual recheck: policy, assets, issues.
    return await session.scalar(
        select(MaintenancePolicy)
        .join(
            KnowledgeAsset,
            or_(
                and_(KnowledgeAsset.scope == "company", MaintenancePolicy.project_id.is_(None)),
                and_(
                    KnowledgeAsset.scope == "project",
                    MaintenancePolicy.project_id == KnowledgeAsset.project_id,
                ),
            ),
        )
        .where(KnowledgeAsset.id == asset_id)
        .with_for_update(of=MaintenancePolicy)
    )


async def _merge(session, original, duplicate):
    # A candidate may already have been inspected before the manager adopts it.
    # Preserve both sets of events, old detail links and all daily reminders.
    await session.execute(
        update(MaintenanceIssueEvent)
        .where(MaintenanceIssueEvent.issue_id == duplicate.id)
        .values(issue_id=original.id)
    )
    await session.execute(
        update(MaintenanceIssueAlias)
        .where(MaintenanceIssueAlias.issue_id == duplicate.id)
        .values(issue_id=original.id)
    )
    links = MaintenanceDigestIssue
    await session.execute(
        delete(links)
        .where(
            links.issue_id == duplicate.id,
            links.digest_id.in_(select(links.digest_id).where(links.issue_id == original.id)),
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(links).where(links.issue_id == duplicate.id).values(issue_id=original.id)
    )
    session.add(MaintenanceIssueAlias(id=duplicate.id, issue_id=original.id))
    original.first_seen_at = min(original.first_seen_at, duplicate.first_seen_at)
    await session.delete(duplicate)
    await session.flush()


async def continue_on_replacement(session, policy, source, target, *, historical=False):
    if policy is None:
        return
    rows = list(
        await session.scalars(
            select(MaintenanceIssue)
            .where(
                MaintenanceIssue.policy_id == policy.id,
                MaintenanceIssue.asset_id == source.id
                if historical
                else or_(
                    MaintenanceIssue.asset_id == source.id,
                    MaintenanceIssue.related_asset_id == source.id,
                ),
                (MaintenanceIssue.status == "not_applicable") & MaintenanceIssue.requires_recheck
                if historical
                else MaintenanceIssue.status.in_(ACTIVE | {"snoozed"}),
                MaintenanceIssue.rule.notin_(RETIRED),
            )
            .order_by(MaintenanceIssue.asset_id == source.id, MaintenanceIssue.id)
            .with_for_update()
        )
    )
    affected = set()
    for row in rows:
        asset_id = target.id if row.asset_id == source.id else row.asset_id
        related_id = target.id if row.related_asset_id == source.id else row.related_asset_id
        related_key = str(related_id) if related_id else ""
        duplicate = await session.scalar(
            select(MaintenanceIssue)
            .where(
                MaintenanceIssue.policy_id == policy.id,
                MaintenanceIssue.asset_id == asset_id,
                MaintenanceIssue.rule == row.rule,
                MaintenanceIssue.related_key == related_key,
            )
            .with_for_update()
        )
        if historical and duplicate:
            # The successor may have passed a real recheck since the old rollout.
            # Preserve its current decision, evidence, and links to both records.
            await _merge(session, duplicate, row)
            session.add(MaintenanceIssueEvent(issue_id=duplicate.id, action="history_linked"))
            if duplicate.status in ACTIVE | {"snoozed"}:
                duplicate.requires_recheck = True
                affected.add(asset_id)
            continue
        if duplicate:
            await _merge(session, row, duplicate)
        row.asset_id, row.related_asset_id, row.related_key = asset_id, related_id, related_key
        row.requires_recheck = True
        row.version_id, row.evidence = None, {}
        row.status, row.snooze_until, row.updated_at = "awaiting_recheck", None, utc_now()
        session.add(MaintenanceIssueEvent(issue_id=row.id, action="version_replaced"))
        affected.add(asset_id)
        await session.flush()
    for asset_id in sorted(affected):
        run = await start_run(session, policy, kind="recheck", asset_id=asset_id, replacement=True)
        if not run or not run.target_count:
            pending = await session.scalars(
                select(MaintenanceIssue).where(
                    MaintenanceIssue.asset_id == asset_id,
                    MaintenanceIssue.policy_id == policy.id,
                    MaintenanceIssue.requires_recheck.is_(True),
                    MaintenanceIssue.status == "awaiting_recheck",
                )
            )
            for item in pending:
                item.status, item.updated_at = "open", utc_now()
                session.add(
                    MaintenanceIssueEvent(
                        issue_id=item.id,
                        action="recheck_incomplete",
                        reason="暂时无法复检，请核对巡检授权与资料范围后重试。",
                    )
                )


async def recover_archived_replacements(session):
    # Consume migration-marked records in bounded transactions on normal worker ticks.
    pending = (
        select(MaintenanceIssue.asset_id)
        .join(KnowledgeAsset, KnowledgeAsset.id == MaintenanceIssue.asset_id)
        .where(
            MaintenanceIssue.status == "not_applicable",
            MaintenanceIssue.requires_recheck.is_(True),
            KnowledgeAsset.asset_status == "archived",
            KnowledgeAsset.replacement_asset_id.is_not(None),
        )
        .distinct()
        .order_by(MaintenanceIssue.asset_id)
        .limit(10)
    )
    for asset_id in list(await session.scalars(pending)):
        policy = await lock_policy(session, asset_id)
        source = await session.get(KnowledgeAsset, asset_id, with_for_update=True)
        target = source
        visited = {source.id}
        while target.replacement_asset_id and target.replacement_asset_id not in visited:
            successor = await session.get(
                KnowledgeAsset, target.replacement_asset_id, with_for_update=True
            )
            if (
                not successor
                or successor.deleted_at
                or (successor.scope, successor.project_id, successor.confidentiality_level)
                != (source.scope, source.project_id, source.confidentiality_level)
            ):
                break
            target = successor
            visited.add(target.id)
        if (
            policy
            and not source.deleted_at
            and target.asset_status in {"active", "needs_update"}
            and not target.replacement_asset_id
        ):
            await continue_on_replacement(session, policy, source, target, historical=True)
        else:
            await session.execute(
                update(MaintenanceIssue)
                .where(
                    MaintenanceIssue.asset_id == source.id,
                    MaintenanceIssue.status == "not_applicable",
                )
                .values(requires_recheck=False)
            )
        await session.commit()
