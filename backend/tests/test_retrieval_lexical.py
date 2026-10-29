"""Literal body recall must work without semantic candidates and retain access gates."""

from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.dialects import postgresql

from app.db.utils import utc_now
from app.main import app
from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetChunk,
    KnowledgeAssetFileObject,
    KnowledgeAssetSummary,
    KnowledgeAssetVersion,
)
from app.models.original_access import AccessGrant
from app.schemas.permission import AccessChannel, CallerContext
from app.seed.dev_seed import (
    KA_PROJECT_ALPHA,
    KA_PROJECT_BETA_L3,
    PROJECT_ALPHA,
    PROJECT_BETA,
    USER_BOSS,
    USER_CONSULTANT,
)
from app.services import retrieval, retrieval_lexical
from app.services.chunking import rebuild_version_chunks
from app.services.generation_models import get_search_llm_client
from app.services.llm_client import NullLLMClient
from app.services.weknora_client import get_weknora_client

MARKER = "BONUS-NEW-1807"


class EmptySemanticRecall:
    async def search(self, **_):
        return []


@pytest.fixture(autouse=True)
def isolated_retrieval():
    app.dependency_overrides[get_weknora_client] = EmptySemanticRecall
    app.dependency_overrides[get_search_llm_client] = NullLLMClient
    yield
    app.dependency_overrides.pop(get_weknora_client, None)
    app.dependency_overrides.pop(get_search_llm_client, None)


async def _body_marker(session, asset_id=KA_PROJECT_ALPHA, text=None):
    asset = await session.get(KnowledgeAsset, asset_id)
    await rebuild_version_chunks(
        session,
        asset_id=asset.id,
        version_id=asset.current_version_id,
        governance_text=text or f"# Synthetic retrieval fixture\nBody-only identifier: {MARKER}.\n",
    )
    await session.commit()
    return asset


async def _canonical_source(session, storage, asset, text):
    content = text.encode("utf-8")
    record = KnowledgeAssetFileObject(
        asset_id=asset.id,
        version_id=asset.current_version_id,
        file_variant="canonical_markdown",
        file_name="synthetic.canonical.md",
        file_mime_type="text/markdown",
        file_size=len(content),
        file_hash=hashlib.sha256(content).hexdigest(),
        storage_ref=storage.save(content, original_name="synthetic.canonical.md"),
        confidentiality_level=asset.confidentiality_level,
    )
    session.add(record)
    await session.commit()
    return record


@pytest.fixture
def controlled_lexical_storage(client, monkeypatch):
    storage = client._kap_storage
    monkeypatch.setattr(retrieval_lexical, "get_storage", lambda: storage, raising=False)
    return storage


async def _search(client, query=MARKER, project_id=PROJECT_ALPHA, **filters):
    return await client.post(
        "/api/v1/knowledge/search",
        headers={"X-Dev-User-Id": str(USER_CONSULTANT)},
        json={
            "query": query,
            "scope": "project",
            "intent": "search",
            "filters": {"project_id": str(project_id), **filters},
        },
    )


async def test_body_identifier_survives_empty_semantic_recall(client, db_session):
    asset = await _body_marker(db_session)
    response = await client.post(
        "/api/v1/knowledge/search",
        headers={"X-Dev-User-Id": str(USER_CONSULTANT)},
        json={
            "query": MARKER,
            "scope": "project",
            "intent": "search",
            "filters": {"project_id": str(PROJECT_ALPHA)},
        },
    )
    assert response.status_code == 200
    assert [card["asset_id"] for card in response.json()["cards"]] == [str(asset.id)]
    assert MARKER not in response.text
    assert "wk-doc" not in response.text


@pytest.mark.parametrize(
    "query,body,found",
    [
        (MARKER.lower(), f"编号{MARKER}已生效", True),
        ("BONUS_NEW_1807", "编号BONUS_NEW_1807已生效", True),
        ("红队-BONUS_1807", "使用红队-BONUS_1807作为编号。", True),
        (MARKER, "BONUS-NEW-18070", False),
        (MARKER, "X-BONUS-NEW-1807", False),
        ("BONUS_NEW_1807", "BONUSXNEWX1807", False),
        (MARKER, "BONUS NEW 1807", False),
    ],
)
async def test_identifier_keeps_case_insensitive_literal_and_boundaries(
    client, db_session, query, body, found
):
    asset = await _body_marker(db_session, text=body)
    response = await _search(client, query)
    assert response.status_code == 200
    assert (str(asset.id) in {c["asset_id"] for c in response.json()["cards"]}) is found


@pytest.mark.parametrize(
    "marker,cut",
    [(MARKER, 1), (MARKER, 5), (MARKER, len(MARKER) - 1), ("CODE1234", 1), ("CODE1234", 5)],
)
async def test_existing_hard_cut_chunks_recall_complete_identifier(
    client, db_session, marker, cut, controlled_lexical_storage
):
    text = "甲" * (512 - cut) + marker + "乙" * 600
    asset = await _body_marker(db_session, text=text)
    await _canonical_source(db_session, controlled_lexical_storage, asset, text)
    chunks = list(
        (
            await db_session.scalars(
                select(KnowledgeAssetChunk)
                .where(KnowledgeAssetChunk.version_id == asset.current_version_id)
                .order_by(KnowledgeAssetChunk.chunk_index)
            )
        ).all()
    )
    assert len(chunks) >= 2
    assert not any(marker in chunk.content_text for chunk in chunks)
    response = await _search(client, marker.lower())
    assert response.status_code == 200
    assert [card["asset_id"] for card in response.json()["cards"]] == [str(asset.id)]


@pytest.mark.parametrize("separator", ["\n", "\n\n"])
async def test_cross_chunk_literal_never_invents_identifier_across_source_lines(
    client, db_session, controlled_lexical_storage, separator
):
    text = "甲" * 507 + "BONUS" + separator + "-NEW-1807" + "乙" * 600
    asset = await _body_marker(db_session, text=text)
    await _canonical_source(db_session, controlled_lexical_storage, asset, text)
    assert not retrieval_lexical.literal_in_text(MARKER, text)
    assert (await _search(client)).json()["cards"] == []


@pytest.mark.parametrize("recorded_size", [True, False])
async def test_trimmed_hard_cut_prefix_still_recalls_proven_source_literal(
    client, db_session, controlled_lexical_storage, recorded_size
):
    text = " " + "甲" * 506 + MARKER + "乙" * 600
    asset = await _body_marker(db_session, text=text)
    source = await _canonical_source(db_session, controlled_lexical_storage, asset, text)
    if not recorded_size:
        # ingest_persistence historically persists canonical objects without size.
        source.file_size = None
        await db_session.commit()
    assert [card["asset_id"] for card in (await _search(client)).json()["cards"]] == [str(asset.id)]
    if not recorded_size:
        await db_session.refresh(source)
        assert source.file_size is None


async def test_cross_chunk_without_controlled_source_is_not_guessed(
    client, db_session, controlled_lexical_storage
):
    await _body_marker(db_session, text="甲" * 507 + MARKER + "乙" * 600)
    assert (await _search(client)).json()["cards"] == []


@pytest.mark.parametrize(
    "invalid", ["hash", "size", "missing", "invalid_ref", "version", "asset", "oversized"]
)
async def test_cross_chunk_requires_exact_controlled_version_bytes(
    client, db_session, controlled_lexical_storage, invalid
):
    text = "甲" * 507 + MARKER + "乙" * 600
    asset = await _body_marker(db_session, text=text)
    source = await _canonical_source(db_session, controlled_lexical_storage, asset, text)
    if invalid == "hash":
        source.file_hash = "0" * 64
    elif invalid == "size":
        source.file_size -= 1
    elif invalid == "missing":
        source.storage_ref = "internal://missing.md"
    elif invalid == "invalid_ref":
        source.storage_ref = "https://example.invalid/private.md"
    elif invalid == "version":
        other = await db_session.get(KnowledgeAsset, KA_PROJECT_BETA_L3)
        source.version_id = other.current_version_id
    elif invalid == "asset":
        source.asset_id = KA_PROJECT_BETA_L3
    elif invalid == "oversized":
        source.file_size = retrieval_lexical._MAX_SOURCE_BYTES + 1
    await db_session.commit()
    assert (await _search(client)).json()["cards"] == []


async def test_cross_chunk_read_budget_is_checked_before_io(
    client, db_session, controlled_lexical_storage, monkeypatch
):
    text = "甲" * 507 + MARKER + "乙" * 600
    asset = await _body_marker(db_session, text=text)
    await _canonical_source(db_session, controlled_lexical_storage, asset, text)
    monkeypatch.setattr(retrieval_lexical, "_SOURCE_READ_BUDGET", len(text.encode("utf-8")))

    def no_read(*_):
        pytest.fail("The exhausted budget must reject before opening a file")

    monkeypatch.setattr(retrieval_lexical, "_source_contains_literal", no_read)
    assert (await _search(client)).json()["cards"] == []


async def test_cross_chunk_summary_only_permission_never_reads_source(
    client, db_session, controlled_lexical_storage, monkeypatch
):
    text = "甲" * 507 + MARKER + "乙" * 600
    asset = await _body_marker(db_session, asset_id=KA_PROJECT_BETA_L3, text=text)
    await _canonical_source(db_session, controlled_lexical_storage, asset, text)

    def no_storage():
        pytest.fail("Original permission must pass before source access")

    monkeypatch.setattr(retrieval_lexical, "get_storage", no_storage)
    assert (await _search(client, project_id=PROJECT_BETA)).json()["cards"] == []


async def test_single_chunk_exact_match_does_not_read_source(client, db_session, monkeypatch):
    asset = await _body_marker(db_session)

    def no_storage():
        pytest.fail("A complete single-chunk literal needs no file IO")

    monkeypatch.setattr(retrieval_lexical, "get_storage", no_storage)
    assert [card["asset_id"] for card in (await _search(client)).json()["cards"]] == [str(asset.id)]


@pytest.mark.parametrize(
    "invalid", ["left_invalid", "right_invalid", "gap", "page", "section", "longer"]
)
async def test_cross_chunk_identifier_does_not_join_invalid_or_unrelated_text(
    client, db_session, invalid, controlled_lexical_storage
):
    marker = MARKER + "0" if invalid == "longer" else MARKER
    text = "甲" * 507 + marker + "乙" * 600
    asset = await _body_marker(db_session, text=text)
    await _canonical_source(db_session, controlled_lexical_storage, asset, text)
    chunks = list(
        (
            await db_session.scalars(
                select(KnowledgeAssetChunk)
                .where(KnowledgeAssetChunk.version_id == asset.current_version_id)
                .order_by(KnowledgeAssetChunk.chunk_index)
            )
        ).all()
    )
    if invalid == "left_invalid":
        chunks[0].chunk_status = "invalid"
    elif invalid == "right_invalid":
        chunks[1].chunk_status = "superseded"
    elif invalid == "gap":
        chunks[1].chunk_index = 10
    elif invalid == "page":
        chunks[1].source_page = 2
    elif invalid == "section":
        chunks[1].source_section = "different section"
    await db_session.commit()
    _semantic_chunk(asset)
    response = await _search(client)
    assert response.status_code == 200
    assert response.json()["cards"] == []


@pytest.mark.parametrize("upstream", [False, True])
async def test_cross_project_body_marker_cannot_reveal_a_summary_only_asset(
    client, db_session, upstream
):
    asset = await _body_marker(db_session, asset_id=KA_PROJECT_BETA_L3)
    if upstream:
        _semantic_chunk(asset)
    response = await _search(client, project_id=PROJECT_BETA)
    assert response.status_code == 200
    assert response.json()["cards"] == []
    assert MARKER not in response.text
    assert str(asset.id) not in response.text


def _semantic_chunk(asset, content=MARKER):
    class ExactSemanticRecall:
        async def search(self, **_):
            return [
                {"knowledge_id": f"wk-doc-{asset.id}", "content": content, "score": 0.9, "seq": 0}
            ]

    app.dependency_overrides[get_weknora_client] = ExactSemanticRecall


@pytest.mark.parametrize("safe", [False, True])
async def test_only_current_authorized_summary_can_keep_cross_project_identifier_hit(
    client, db_session, safe
):
    asset = await _body_marker(db_session, asset_id=KA_PROJECT_BETA_L3)
    summary = (
        await db_session.scalars(
            select(KnowledgeAssetSummary).where(
                KnowledgeAssetSummary.asset_id == asset.id,
                KnowledgeAssetSummary.version_id == asset.current_version_id,
                KnowledgeAssetSummary.summary_type == ("redacted_summary" if safe else "detailed"),
            )
        )
    ).first()
    if summary is None:
        summary = KnowledgeAssetSummary(
            asset_id=asset.id,
            version_id=asset.current_version_id,
            summary_type="redacted_summary" if safe else "detailed",
        )
        db_session.add(summary)
    summary.content = f"Synthetic summary {MARKER}"
    await db_session.commit()
    _semantic_chunk(asset)
    response = await _search(client, project_id=PROJECT_BETA)
    assert response.status_code == 200
    cards = response.json()["cards"]
    assert bool(cards) is safe
    if safe:
        assert cards[0]["can_view_original"] is False
        assert cards[0]["detailed"] == summary.content
    else:
        assert MARKER not in response.text


@pytest.mark.parametrize("status", ["active", "revoked", "expired"])
async def test_original_grant_is_checked_live_for_literal_body(client, db_session, status):
    asset = await _body_marker(db_session, asset_id=KA_PROJECT_BETA_L3)
    db_session.add(
        AccessGrant(
            asset_id=asset.id,
            grantee_user_id=USER_CONSULTANT,
            granted_by_user_id=USER_BOSS,
            expires_at=utc_now() + timedelta(days=-1 if status == "expired" else 1),
            status="revoked" if status == "revoked" else "active",
        )
    )
    await db_session.commit()
    response = await _search(client, project_id=PROJECT_BETA)
    assert response.status_code == 200
    assert bool(response.json()["cards"]) is (status == "active")


@pytest.mark.parametrize(
    "invalid",
    [
        "archived",
        "stale",
        "inactive_version",
        "index_failed",
        "pending",
        "other_kb",
        "missing_current",
        "invalid_chunk",
        "superseded_chunk",
    ],
)
async def test_literal_body_retains_current_version_and_chunk_gates(client, db_session, invalid):
    asset = await _body_marker(db_session)
    version = await db_session.get(KnowledgeAssetVersion, asset.current_version_id)
    if invalid == "archived":
        asset.asset_status = "archived"
    elif invalid == "stale":
        asset.current_version_id = uuid.uuid4()
    elif invalid == "missing_current":
        asset.current_version_id = None
    elif invalid == "inactive_version":
        version.version_status = "superseded"
    elif invalid == "index_failed":
        version.index_status = "index_failed"
    elif invalid == "pending":
        version.directory_key = "personal.pending"
    elif invalid == "other_kb":
        version.weknora_kb_id = "unrelated-kb"
    else:
        await db_session.execute(
            update(KnowledgeAssetChunk)
            .where(KnowledgeAssetChunk.version_id == version.id)
            .values(chunk_status="invalid" if invalid == "invalid_chunk" else "superseded")
        )
        # A stale upstream chunk must not revive an invalid local body.
        _semantic_chunk(asset)
    await db_session.commit()
    response = await _search(client)
    assert response.status_code == 200
    assert response.json()["cards"] == []


async def test_literal_body_honors_directory_and_tag_constraints(client, db_session):
    await _body_marker(db_session)
    response = await _search(client, tags=["not-present-on-fixture"])
    assert response.status_code == 200
    assert response.json()["cards"] == []


async def test_identifier_does_not_use_model_generated_replacements(db_session):
    await _body_marker(db_session)
    calls = []

    class RecordingRecall:
        async def search(self, **kwargs):
            calls.append(kwargs["query"])
            return []

    caller = CallerContext(
        user_id=USER_CONSULTANT,
        is_active=True,
        active_company_roles={"consultant"},
        active_project_ids={PROJECT_ALPHA},
    )
    found = await retrieval.recall_assets(
        db_session,
        caller,
        RecordingRecall(),
        query=MARKER,
        kb_ids=[f"wk-kb-proj-{PROJECT_ALPHA}"],
        channel=AccessChannel.human,
        search_queries=["unrelated concept", "rewritten number 1808"],
    )
    assert [r.asset.id for r in found] == [KA_PROJECT_ALPHA]
    assert calls == [MARKER]


@pytest.mark.parametrize("channel", [AccessChannel.agent, AccessChannel.human])
async def test_agent_a4_boundary_does_not_disclose_private_identifier(db_session, channel):
    asset = await _body_marker(db_session)
    asset.ai_access_level = "A4"
    await db_session.commit()
    caller = CallerContext(
        user_id=USER_CONSULTANT,
        is_active=True,
        active_company_roles={"consultant"},
        active_project_ids={PROJECT_ALPHA},
    )
    found = await retrieval.recall_assets(
        db_session,
        caller,
        EmptySemanticRecall(),
        query=MARKER,
        kb_ids=[f"wk-kb-proj-{PROJECT_ALPHA}"],
        channel=channel,
    )
    assert bool(found) is (channel == AccessChannel.human)


async def test_current_version_switch_does_not_recall_old_identifier(client, db_session):
    asset = await _body_marker(db_session)
    old_id = asset.current_version_id
    old_version = await db_session.get(KnowledgeAssetVersion, old_id)
    old_version.version_status = "superseded"
    await db_session.flush()
    replacement = KnowledgeAssetVersion(
        asset_id=asset.id,
        version_no="v2",
        version_status="active",
        index_status="indexed",
        weknora_kb_id=f"wk-kb-proj-{PROJECT_ALPHA}",
        weknora_doc_id="new-current-doc",
        created_by=USER_CONSULTANT,
    )
    db_session.add(replacement)
    await db_session.flush()
    asset.current_version_id = replacement.id
    await rebuild_version_chunks(
        db_session,
        asset_id=asset.id,
        version_id=replacement.id,
        governance_text="The current synthetic version has no old identifier.",
    )
    await db_session.commit()
    assert old_id != asset.current_version_id
    _semantic_chunk(asset)
    response = await _search(client)
    assert response.status_code == 200
    assert response.json()["cards"] == []


async def test_semantic_result_from_a_different_kb_is_not_a_literal_fallback(client, db_session):
    asset = await db_session.get(KnowledgeAsset, KA_PROJECT_ALPHA)
    version = await db_session.get(KnowledgeAssetVersion, asset.current_version_id)
    version.weknora_kb_id = "outside-requested-kb"
    await db_session.commit()
    _semantic_chunk(asset)
    response = await _search(client)
    assert response.status_code == 200
    assert response.json()["cards"] == []


def test_postgres_literal_query_uses_index_expression_and_bound_parameters():
    statement = retrieval_lexical.literal_body_statement(
        MARKER, ["fixture-kb"], None, postgresql=True
    )
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "to_tsvector('simple'::regconfig" in sql
    assert "regexp_replace(knowledge_asset_chunks.content_text, '[^A-Za-z0-9]+', ' ', 'g')" in sql
    assert "@@ plainto_tsquery" in sql
    assert MARKER not in sql


@pytest.mark.parametrize(
    "query",
    [
        "1807",
        "2026-10-29",
        "奖金规则",
        "BONUS",
        "bonus new 1807",
        "%1807_",
        "本月L3制度",
        "ISO9001制度说明",
        "x" * 129 + "1807",
    ],
)
def test_ordinary_queries_do_not_scan_local_body(query):
    assert retrieval_lexical.literal_identifier(query) is None
