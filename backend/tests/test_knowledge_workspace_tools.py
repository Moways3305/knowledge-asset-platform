"""The shared Agent's evidence tools retain live grants and adopted-version history."""

import json

from test_workspace_tools import caller

from app.models.knowledge import KnowledgeAsset, KnowledgeAssetSummary, KnowledgeAssetVersion
from app.seed.dev_seed import KA_COMPANY_L2, USER_BOSS
from app.services import knowledge_workspace_tools as tools

ASK = "帮我找一份适合制造业客户的访谈提纲，看看有没有新版，给我一份明天能用的。"
PHONE = "13800138000"


async def template(db):
    asset = await db.get(KnowledgeAsset, KA_COMPANY_L2)
    asset.title = "制造业客户访谈提纲"
    first = await db.get(KnowledgeAssetVersion, asset.current_version_id)
    first.version_status = "superseded"
    first.naming_metadata = {"version": "V1"}
    await db.flush()
    current = KnowledgeAssetVersion(
        asset_id=asset.id,
        version_no="V2",
        version_status="active",
        created_by=USER_BOSS,
        supersedes_version_id=first.id,
    )
    db.add(current)
    await db.flush()
    asset.current_version_id = current.id
    for kind in ("redacted_summary", "detailed"):
        db.add(
            KnowledgeAssetSummary(
                asset_id=asset.id,
                version_id=current.id,
                summary_type=kind,
                content="新增产线排程访谈。联系人电话：" + PHONE,
            )
        )
    await db.commit()
    return asset


async def test_adoption_shows_only_visible_old_source_links(db_session):
    old = await template(db_session)
    selected = {"asset_id": str(old.id), "version_id": str(old.current_version_id)}

    def company_asset(title, *, level="L2", source=None):
        return KnowledgeAsset(
            title=title,
            scope="company",
            zone="asset",
            asset_type=old.asset_type,
            owner_user_id=USER_BOSS,
            confidentiality_level=level,
            visibility="public",
            source_asset_id=source,
        )

    new = company_asset("制造业客户访谈提纲（修订）")
    public = company_asset("产线调研附件", source=old.id)
    private = company_asset("保密的合成附件", level="L5", source=old.id)
    db_session.add_all([new, public, private])
    await db_session.flush()
    version = KnowledgeAssetVersion(
        asset_id=new.id, version_no="V3", version_status="active", created_by=USER_BOSS
    )
    db_session.add(version)
    await db_session.flush()
    new.current_version_id = version.id
    old.asset_status, old.replacement_asset_id = "archived", new.id
    await db_session.commit()
    availability, evidence = await tools.evidence(db_session, caller(), "company", selected, ASK)
    result = evidence.model_dump(mode="json")
    assert availability == "changed" and result["asset_id"] == str(new.id)
    assert result["compared_version"] == "V2"
    assert result["old_source_links"] == [{"asset_id": str(public.id), "title": public.title}]
    assert private.title not in str(result)


async def test_current_version_evidence_redacts_and_rechecks_authority(db_session):
    asset = await template(db_session)
    found = await tools.search(db_session, caller(), "company", ASK)
    assert asset.id in [identity for identity, _ in found]
    selected = {"asset_id": str(asset.id), "version_id": str(asset.current_version_id)}
    availability, evidence = await tools.evidence(db_session, caller(), "company", selected, ASK)
    assert availability == "available"
    assert (evidence.version, evidence.compared_version) == ("V2", "V1")
    assert {"制造业", "访谈提纲"} <= set(evidence.matched)
    assert "新增产线排程" in evidence.current_summary
    assert PHONE not in json.dumps(evidence.model_dump(mode="json"), ensure_ascii=False)
    asset.confidentiality_level = "L5"
    await db_session.commit()
    assert await tools.evidence(db_session, caller(), "company", selected, ASK) == (
        "unavailable",
        None,
    )


async def test_summary_match_grounds_recommendation_in_current_projection(db_session):
    asset = await template(db_session)
    selected = {"asset_id": str(asset.id), "version_id": str(asset.current_version_id)}
    _, item = await tools.evidence(
        db_session, caller(), "company", selected, "找一份关于产线排程的访谈提纲"
    )
    assert item.matched == ["访谈提纲"] and item.summary_matched == ["产线排程"]
    assert "产线排程" in item.summary and PHONE not in item.summary
