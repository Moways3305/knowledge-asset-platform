"""Load related card data once after bounded metadata discovery, without leaks."""

import uuid
from collections import Counter

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session
from test_search_api import FakeSearchWeKnora

from app.main import app
from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetSummary,
    KnowledgeAssetTag,
    KnowledgeAssetVersion,
)
from app.seed.dev_seed import USER_CONSULTANT
from app.services import retrieval
from app.services.llm_client import NullLLMClient, get_llm_client
from app.services.weknora_client import get_weknora_client


@pytest.mark.parametrize("mode", ["metadata", "semantic", "overlap", "disjoint"])
async def test_candidate_relationships_loaded_once_after_discovery(
    client, db_session, monkeypatch, mode
):
    monkeypatch.setattr(retrieval, "_METADATA_TOP_K", 2)
    query = "批量候选"
    assets, docs = [], []
    for index in range(8):
        asset_id, version_id = uuid.uuid4(), uuid.uuid4()
        denied = index < 5
        # Denied hits precede permitted metadata hits across several pages.
        title = f"{query} {index:02}" if index < 7 and mode != "semantic" else f"其它资料 {index}"
        asset = KnowledgeAsset(
            id=asset_id,
            title=title,
            scope="company",
            zone="asset",
            asset_type="deliverable",
            owner_user_id=USER_CONSULTANT,
            confidentiality_level="L5" if denied else "L2",
            ai_access_level="A1",
            asset_status="active",
            current_version_id=version_id,
        )
        version = KnowledgeAssetVersion(
            id=version_id,
            asset_id=asset_id,
            version_no="V1",
            version_status="active",
            created_by=USER_CONSULTANT,
            weknora_kb_id="wk-kb-company",
            weknora_doc_id=f"synthetic-doc-{index}",
            index_status="indexed",
        )
        db_session.add_all(
            [
                asset,
                version,
                KnowledgeAssetTag(asset_id=asset_id, tag_name=f"tag-{index}"),
                KnowledgeAssetSummary(
                    asset_id=asset_id,
                    version_id=version_id,
                    summary_type="redacted_summary",
                    content=f"safe-{index}",
                ),
            ]
        )
        assets.append(asset_id)
        if (mode in {"semantic", "overlap"} and index == 5) or (mode == "disjoint" and index == 7):
            docs.append(
                {
                    "knowledge_id": version.weknora_doc_id,
                    "kb_id": "wk-kb-company",
                    "content": "synthetic evidence",
                }
            )
    await db_session.commit()
    app.dependency_overrides[get_weknora_client] = lambda: FakeSearchWeKnora(docs)
    app.dependency_overrides[get_llm_client] = lambda: NullLLMClient()
    statements = Counter()
    summary_assets = set()

    def sql(conn, cursor, statement, parameters, context, executemany):
        for table in ("knowledge_asset_summaries", "knowledge_asset_tags"):
            if statement.lstrip().startswith(f"SELECT {table}."):
                statements[table] += 1

    def loaded(session, instance):
        if isinstance(instance, KnowledgeAssetSummary):
            summary_assets.add(instance.asset_id)

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", sql)
    event.listen(Session, "loaded_as_persistent", loaded)
    try:
        response = await client.post(
            "/api/v1/knowledge/search",
            headers={"X-Dev-User-Id": str(USER_CONSULTANT)},
            json={"query": query, "scope": "company", "intent": "search"},
        )
    finally:
        event.remove(engine, "before_cursor_execute", sql)
        event.remove(Session, "loaded_as_persistent", loaded)
    assert response.status_code == 200
    expected = [5] if mode == "semantic" else [5, 6, 7] if mode == "disjoint" else [5, 6]
    cards = response.json()["cards"]
    assert [card["asset_id"] for card in cards] == [str(assets[i]) for i in expected]
    for card, index in zip(cards, expected, strict=True):
        assert card["tags"] == [f"tag-{index}"]
        assert card["one_liner"] == f"safe-{index}"
        assert card["can_view_original"] is False
    assert summary_assets == {assets[i] for i in expected}
    assert statements == {"knowledge_asset_summaries": 1, "knowledge_asset_tags": 1}
    assert "synthetic-doc" not in response.text
