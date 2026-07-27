from __future__ import annotations

from sqlalchemy import select

from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetSummary,
    KnowledgeAssetVersion,
)
from app.seed.dev_seed import USER_CONSULTANT
from app.services.authorized_summary_backfill import backfill_authorized_summaries


async def _seed_truncated_l3(db_session) -> tuple[KnowledgeAsset, KnowledgeAssetVersion, str]:
    sensitive_customer = "历史敏感客户"
    sensitive_email = "legacy@example.com"
    safe_tail = "BACKFILL-COMPLETE-END"
    detailed = (
        f"客户名称：{sensitive_customer}，联系邮箱 {sensitive_email}。"
        + "这是历史详细摘要中允许在脱敏后完整展示的安全业务说明。" * 18
        + safe_tail
    )
    asset = KnowledgeAsset(
        title="待回填完整脱敏摘要",
        scope="personal",
        zone="material",
        asset_type="methodology",
        owner_user_id=USER_CONSULTANT,
        visibility="private",
        confidentiality_level="L3",
        ai_access_level="A3",
        asset_status="active",
    )
    version = KnowledgeAssetVersion(
        asset=asset,
        version_no="v1",
        version_status="active",
        created_by=USER_CONSULTANT,
    )
    db_session.add_all([asset, version])
    await db_session.flush()
    asset.current_version_id = version.id
    db_session.add_all(
        [
            KnowledgeAssetSummary(
                asset_id=asset.id,
                version_id=version.id,
                summary_type="one_liner",
                content=f"客户名称：{sensitive_customer}的历史摘要",
            ),
            KnowledgeAssetSummary(
                asset_id=asset.id,
                version_id=version.id,
                summary_type="detailed",
                content=detailed,
            ),
            KnowledgeAssetSummary(
                asset_id=asset.id,
                version_id=version.id,
                summary_type="redacted_summary",
                content="（脱敏）" + detailed[:200],
            ),
        ]
    )
    await db_session.commit()
    return asset, version, safe_tail


async def _summary_map(db_session, asset_id, version_id) -> dict[str, str | None]:
    rows = (
        await db_session.execute(
            select(KnowledgeAssetSummary).where(
                KnowledgeAssetSummary.asset_id == asset_id,
                KnowledgeAssetSummary.version_id == version_id,
            )
        )
    ).scalars()
    return {row.summary_type: row.content for row in rows}


async def test_backfill_is_dry_run_first_complete_and_idempotent(db_session):
    asset, version, safe_tail = await _seed_truncated_l3(db_session)
    before = await _summary_map(db_session, asset.id, version.id)

    dry_run = await backfill_authorized_summaries(db_session, dry_run=True)
    after_dry_run = await _summary_map(db_session, asset.id, version.id)
    assert dry_run.dry_run is True
    assert dry_run.regenerated >= 1
    assert dry_run.evidence
    assert before == after_dry_run

    applied = await backfill_authorized_summaries(db_session, dry_run=False)
    after_apply = await _summary_map(db_session, asset.id, version.id)
    assert applied.dry_run is False
    assert applied.regenerated >= 1
    assert after_apply["redacted_summary"].endswith(safe_tail)
    assert len(after_apply["redacted_summary"]) > 200
    assert after_apply["redacted_one_liner"] != after_apply["redacted_summary"]
    assert "历史敏感客户" not in after_apply["redacted_summary"]
    assert "legacy@example.com" not in after_apply["redacted_summary"]

    repeated = await backfill_authorized_summaries(db_session, dry_run=False)
    assert repeated.regenerated == 0
    assert repeated.created_rows == 0
    assert repeated.updated_rows == 0
    assert repeated.cleared_pending_markers == 0


async def test_backfill_marks_missing_source_pending_without_fabricating(db_session):
    asset = KnowledgeAsset(
        title="缺少普通详细摘要",
        scope="personal",
        zone="material",
        asset_type="methodology",
        owner_user_id=USER_CONSULTANT,
        visibility="private",
        confidentiality_level="L4",
        ai_access_level="A4",
        asset_status="active",
    )
    version = KnowledgeAssetVersion(
        asset=asset,
        version_no="v1",
        version_status="active",
        created_by=USER_CONSULTANT,
    )
    db_session.add_all([asset, version])
    await db_session.flush()
    asset.current_version_id = version.id
    await db_session.commit()

    report = await backfill_authorized_summaries(db_session, dry_run=False)
    summaries = await _summary_map(db_session, asset.id, version.id)
    assert report.pending >= 1
    assert summaries["redacted_summary_pending"] == "source_summary_missing"
    assert "redacted_summary" not in summaries

    repeated = await backfill_authorized_summaries(db_session, dry_run=False)
    assert repeated.created_rows == 0
    assert repeated.updated_rows == 0
