"""L2–L4 summary variants must never fall back to ordinary summary content."""

import uuid

import pytest

from app.models.knowledge import KnowledgeAsset, KnowledgeAssetSummary
from app.services.ingest_persistence import build_summaries
from app.services.knowledge_projection import _select_summary_text
from app.services.retrieval import _card_summary_fields, needs_desensitization


@pytest.mark.parametrize("level", ["L2", "L3", "L4"])
def test_protected_summary_persistence_and_projections(level):
    raw = "联系人：张三，合同金额：350000，预算50万元。"
    rows = build_summaries(level, one_liner=raw, detailed=raw, key_points=[raw])
    smap = {row.summary_type: row.content for row in rows}
    assert smap["detailed"] == raw  # retained original summary is not overwritten
    assert "张三" not in smap["redacted_summary"]
    assert "350000" not in smap["redacted_summary"]
    assert _select_summary_text(level, smap) == smap["redacted_one_liner"]
    asset = KnowledgeAsset(confidentiality_level=level, summaries=rows)
    one, detailed, points = _card_summary_fields(asset, True)
    assert detailed == smap["redacted_summary"]
    assert points == []
    assert "张三" not in one
    assert _card_summary_fields(asset, False) == (None, None, [])


@pytest.mark.parametrize("level", ["L2", "L3", "L4"])
def test_missing_safe_variant_returns_empty_not_raw(level):
    raw = "UNREDACTED-SECRET"
    assert _select_summary_text(level, {"detailed": raw, "one_liner": raw}) is None
    asset = KnowledgeAsset(
        confidentiality_level=level,
        summaries=[KnowledgeAssetSummary(summary_type="detailed", content=raw)],
    )
    assert _card_summary_fields(asset, True) == (None, None, [])


@pytest.mark.parametrize("level", ["L1", "L5"])
def test_l1_and_l5_summary_policy_is_unchanged(level):
    rows = build_summaries(level, one_liner="public", detailed="detail", key_points=["point"])
    assert not any(row.summary_type.startswith("redacted") for row in rows)
    # L5 access is still enforced by permission.decide, not this formatter.
    assert _card_summary_fields(
        KnowledgeAsset(confidentiality_level=level, summaries=rows), False
    ) == (None, None, [])


def test_original_chunk_policy_is_not_expanded():
    assert not needs_desensitization(KnowledgeAsset(confidentiality_level="L2"))
    assert needs_desensitization(KnowledgeAsset(confidentiality_level="L5"))


async def test_l2_detail_no_raw_fallback_then_backfill(client, db_session):
    from app.models.knowledge import KnowledgeAssetVersion
    from app.seed.dev_seed import USER_CONSULTANT
    from app.services.authorized_summary_backfill import backfill_authorized_summaries

    asset = KnowledgeAsset(
        id=uuid.uuid4(),
        title="L2 summary regression",
        scope="personal",
        zone="material",
        asset_type="methodology",
        owner_user_id=USER_CONSULTANT,
        visibility="private",
        confidentiality_level="L2",
        ai_access_level="A3",
        asset_status="active",
    )
    version = KnowledgeAssetVersion(
        asset=asset, version_no="v1", version_status="active", created_by=USER_CONSULTANT
    )
    db_session.add_all([asset, version])
    await db_session.flush()
    asset.current_version_id = version.id
    db_session.add(
        KnowledgeAssetSummary(
            asset_id=asset.id,
            version_id=version.id,
            summary_type="detailed",
            content="联系人：张三，预算50万元。",
        )
    )
    await db_session.commit()
    url = f"/api/v1/knowledge/{asset.id}"
    before = await client.get(url, headers={"X-Dev-User-Id": str(USER_CONSULTANT)})
    assert before.status_code == 200
    assert before.json()["summary"]["detailed"] is None
    await backfill_authorized_summaries(db_session, dry_run=False)
    after = await client.get(url, headers={"X-Dev-User-Id": str(USER_CONSULTANT)})
    assert after.status_code == 200
    assert after.json()["summary"]["detailed"].startswith("（脱敏）")
    assert "张三" not in after.text and "50万元" not in after.text
    assert before.json()["access_info"]["original"] == after.json()["access_info"]["original"]
