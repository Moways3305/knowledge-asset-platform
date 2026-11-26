"""Exercise actual delegate, history, version, correction and recovery boundaries."""

import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from test_maintenance_agent import configure, headers

from app.db.utils import utc_now
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetSummary, KnowledgeAssetVersion
from app.models.knowledge_task import KnowledgeTask
from app.seed.dev_seed import KA_COMPANY_L2, USER_ADMIN_ONLY, USER_BOSS, USER_CONSULTANT
from app.services import knowledge_tasks

URL = "/api/v1/maintenance-agent/libraries/company/tasks"
ASK = "帮我找一份适合制造业客户的访谈提纲，看看有没有新版，给我一份明天能用的。"
PHONE = "13800138000"
CONSULTANT = headers(USER_CONSULTANT)


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


async def submit(client, instruction=ASK, key=None):
    body = {"request_id": str(key or uuid.uuid4()), "instruction": instruction}
    started = await client.post(URL, headers=CONSULTANT, json=body)
    assert started.status_code == 202, started.text
    route = URL + "/" + started.json()["id"]
    response = await client.get(route, headers=CONSULTANT)
    assert response.status_code == 200, response.text
    return route, response.json()


async def test_consultant_delegation_and_correction(client, db_session):
    asset = await template(db_session)
    key = uuid.uuid4()
    route, result = await submit(client, ASK + " 电话：" + PHONE, key)
    assert result["status"] == "ready", result
    evidence = result["evidence"]
    assert (evidence["version"], evidence["compared_version"]) == ("V2", "V1")
    assert {"制造业", "访谈提纲"} <= set(evidence["matched"])
    assert "新增产线排程" in evidence["current_summary"]
    assert PHONE not in json.dumps(result, ensure_ascii=False)
    assert evidence["correction_status"] is None
    report = await client.post(
        f"/api/v1/knowledge/{asset.id}/trust/corrections",
        headers=CONSULTANT,
        json={"reason": "请核对新增产线排程一节。", "expected_updated_at": evidence["updated_at"]},
    )
    assert report.status_code == 200, report.text
    _, again = await submit(client, ASK + " 电话：" + PHONE, key)
    assert again["evidence"]["correction_status"] == "open"
    history = (await client.get(URL, headers=CONSULTANT)).json()
    assert len(history) == 1 and PHONE not in str(history)
    assert (await client.get(route, headers=headers(USER_BOSS))).status_code == 404
    assert (await client.get(URL, headers=headers(USER_ADMIN_ONLY))).status_code == 403
    await db_session.refresh(asset)
    asset.confidentiality_level = "L5"
    await db_session.commit()
    hidden = (await client.get(route, headers=CONSULTANT)).json()
    assert hidden["evidence"] is None and hidden["availability"] == "unavailable"


@pytest.mark.parametrize("action", ["valid", "invalid", "abstain"])
async def test_opaque_model_tools(client, db_session, monkeypatch, action):
    await template(db_session)
    await configure(client, content=True)
    prompts = []

    class Planner:
        async def chat_completion(self, messages, **kwargs):
            prompts.append(messages[-1]["content"])
            if action == "invalid":
                return '{"action":"recommend","index":9001}'
            if action == "abstain":
                return '{"action":"abstain"}'
            return json.dumps(
                {"action": "inspect" if len(prompts) == 1 else "recommend", "index": 0}
            )

    async def resolve(*args, **kwargs):
        return Planner()

    monkeypatch.setattr(knowledge_tasks, "resolve_generation_llm_client", resolve)
    _, task = await submit(client)
    assert task["status"] == ("empty" if action == "abstain" else "ready")
    assert task["mode"] == ("model_unavailable" if action == "invalid" else "model")
    for raw in prompts:
        assert all(
            private not in raw for private in ("制造业", "访谈", "产线", PHONE, str(KA_COMPANY_L2))
        )
    if action == "valid":
        assert len(prompts) == 2 and json.loads(prompts[1])["version_checks"]["0"]["current"]


async def test_empty_scope_stale_and_recovery(client, db_session, sessionmaker_fixture):
    asset = await template(db_session)
    _, empty = await submit(client, "找一份量子设备手册")
    assert empty["status"] == "empty" and empty["evidence"] is None
    assert (
        await client.get(URL.replace("company", "project:" + str(uuid.uuid4())), headers=CONSULTANT)
    ).status_code == 404
    route, old = await submit(client)
    assert old["status"] == "ready"
    row = await db_session.scalar(
        select(KnowledgeTask).where(KnowledgeTask.id == uuid.UUID(old["id"]))
    )
    row.status = "checking"
    row.claim = uuid.uuid4()
    row.lease_until = utc_now() - timedelta(minutes=5)
    await db_session.commit()
    await knowledge_tasks.recover(sessionmaker_fixture)
    await db_session.refresh(row)
    assert row.status == "ready" and row.claim is None
    version = await db_session.get(KnowledgeAssetVersion, asset.current_version_id)
    version.version_status = "superseded"
    await db_session.flush()
    v3 = KnowledgeAssetVersion(
        asset_id=asset.id,
        version_no="V3",
        version_status="active",
        created_by=USER_BOSS,
        supersedes_version_id=version.id,
    )
    db_session.add(v3)
    await db_session.flush()
    asset.current_version_id = v3.id
    await db_session.commit()
    changed = (await client.get(route, headers=CONSULTANT)).json()
    assert changed["availability"] == "changed"
    assert changed["evidence"]["version"] == "V3"
    assert changed["evidence"]["compared_version"] == "V2"


async def test_adoption_shows_only_visible_old_source_links(client, db_session):
    old = await template(db_session)
    route, _ = await submit(client)

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
    result = (await client.get(route, headers=CONSULTANT)).json()
    assert result["availability"] == "changed" and result["evidence"]["asset_id"] == str(new.id)
    assert result["evidence"]["compared_version"] == "V2"
    assert result["evidence"]["old_source_links"] == [
        {"asset_id": str(public.id), "title": public.title}
    ]
    assert private.title not in str(result)


async def test_grounds_industry_match_in_visible_summary(client, db_session):
    await template(db_session)
    _, result = await submit(client, "找一份关于产线排程的访谈提纲")
    item = result["evidence"]
    assert item["matched"] == ["访谈提纲"] and item["summary_matched"] == ["产线排程"]
    assert "产线排程" in item["summary"] and PHONE not in item["summary"]
