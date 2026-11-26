"""Reconcile inexpensive objective facts inside the asset write transaction.

No LLM, external file access, new scan or invented content verdict. Findings and
notifications all keep their original audit identity; only satisfied facts close.
"""

from datetime import timedelta

from sqlalchemy import select

from app.db.utils import utc_now
from app.models.knowledge import KnowledgeAssetSummary, KnowledgeAssetTag, KnowledgeAssetVersion
from app.models.knowledge_correction import KnowledgeCorrection
from app.models.maintenance_agent import MaintenanceIssue, MaintenanceIssueEvent, MaintenancePolicy
from app.services.maintenance_rules import RETIRED


async def reconcile_asset(session, asset):
    from app.services.maintenance_access import recipients, stamp

    rows = (
        await session.scalars(
            select(MaintenanceIssue)
            .where(
                MaintenanceIssue.asset_id == asset.id,
                MaintenanceIssue.status.notin_(["resolved", "false_positive", "not_applicable"]),
            )
            .with_for_update()
        )
    ).all()
    if not rows:
        return
    now = utc_now()
    version = (
        await session.get(KnowledgeAssetVersion, asset.current_version_id)
        if asset.current_version_id
        else None
    )
    tags = set(
        await session.scalars(
            select(KnowledgeAssetTag.tag_name).where(KnowledgeAssetTag.asset_id == asset.id)
        )
    )
    summaries = list(
        await session.scalars(
            select(KnowledgeAssetSummary.content).where(
                KnowledgeAssetSummary.asset_id == asset.id,
                KnowledgeAssetSummary.version_id == asset.current_version_id,
                KnowledgeAssetSummary.summary_type.in_(
                    [
                        "one_liner",
                        "detailed",
                        "summary",
                        "detailed_summary",
                        "safe_summary",
                        "redacted_summary",
                    ]
                ),
            )
        )
    )
    responsible = await recipients(session, asset)
    policies = {
        p.id: p
        for p in await session.scalars(
            select(MaintenancePolicy).where(
                MaintenancePolicy.id.in_({row.policy_id for row in rows})
            )
        )
    }
    for row in rows:
        settings = policies[row.policy_id].settings
        overdue = int(settings.get("overdue_days", 7))
        closed = row.rule in RETIRED
        if asset.deleted_at or asset.asset_status not in {"active", "needs_update"}:
            closed = True
        elif row.requires_recheck:
            continue
        elif row.rule == "missing_summary":
            closed = any(s and s.strip() for s in summaries)
        elif row.rule == "missing_directory":
            closed = bool(version and version.directory_key)
        elif row.rule == "missing_tags":
            closed = not (set(settings.get("required_tags", [])) - tags)
        elif row.rule == "missing_maintainer":
            closed = bool(responsible)
        elif row.rule == "review_overdue":
            closed = asset.review_due_at is None or stamp(asset.review_due_at) > now
        elif row.rule == "correction_overdue":
            closed = not await session.scalar(
                select(KnowledgeCorrection.id)
                .where(
                    KnowledgeCorrection.asset_id == asset.id,
                    KnowledgeCorrection.status == "open",
                    KnowledgeCorrection.updated_at <= now - timedelta(days=overdue),
                )
                .limit(1)
            )
        elif row.rule == "update_overdue":
            closed = asset.asset_status != "needs_update"
        if closed:
            row.status = (
                "not_applicable"
                if row.rule in RETIRED or asset.asset_status not in {"active", "needs_update"}
                else "resolved"
            )
            row.updated_at, row.snooze_until = now, None
            row.requires_recheck = False
            session.add(
                MaintenanceIssueEvent(
                    issue_id=row.id,
                    action="fact_reconciled",
                    reason="资料状态已更新，相关检查项自动同步。",
                )
            )
