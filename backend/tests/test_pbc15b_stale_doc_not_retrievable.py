"""PBC-15 residual：index_failed 残留旧 doc 不得被语义召回 / 原文取件。

纵深防御：即使 WeKnora 旧 doc 仍在且被 search 返回，只要平台 version 的
`index_status != "indexed"`（index_failed / not_indexed / skipped），就不得映射回资产、
不得作为有效索引参与召回或单资产原文 chunk 取件。

覆盖：
1. 批量语义召回不映射 index_failed 旧 doc（不出现在 cards）；
2. 单资产原文 chunk 不读取 index_failed 旧 doc（available=False，安全降级）；
3. reparse 失败（删旧 doc 失败被吞 + 重传失败）残留旧 doc 场景：资产不被召回、原文不可用、
   job 仍按 PBC-15 语义统计失败；全程不泄露 doc/kb/storage/source id。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.main import app
from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetSummary,
    KnowledgeAssetTag,
    KnowledgeAssetVersion,
)
from app.services.llm_client import get_llm_client
from app.services.weknora_client import WeKnoraError, get_weknora_client
from app.seed.dev_seed import PROJECT_ALPHA, USER_ADMIN_ONLY, USER_CONSULTANT

SEARCH = "/api/v1/knowledge/search"
UPLOAD = "/api/v1/ingest/upload"
REPARSE = "/admin/ops/indexing/reparse"
_ALPHA_KB = f"wk-kb-proj-{PROJECT_ALPHA}"
_STALE_DOC = "wk-doc-stale-index-failed"
_LEAK_TOKENS = ["wk-kb", "wk-doc", "kb_id", "doc_id", "chunk_id", "api_key", "sk-", "storage_ref", "source_file_ref"]


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


def _assert_no_leak(text):
    for t in _LEAK_TOKENS:
        assert t not in text, f"响应不应泄露 {t}"


class FakeSearchWK:
    """按 kb/knowledge 过滤返回 chunk；reparse 时删旧 doc 失败（被吞）+ 上传失败。"""

    def __init__(self, docs, *, reparse_delete_fail=False, upload_fail=False):
        self.docs = docs
        self.reparse_delete_fail = reparse_delete_fail
        self.upload_fail = upload_fail
        self.deleted: list[str] = []
        self.uploads: list[bytes] = []
        self._kb = 0
        self._doc = 0

    async def search(self, *, query, kb_ids, knowledge_ids=None, top_k=20, trace_id=None):
        out = []
        for i, d in enumerate(self.docs):
            if d["kb_id"] not in kb_ids:
                continue
            if knowledge_ids and d["knowledge_id"] not in knowledge_ids:
                continue
            out.append({
                "content": d["content"], "knowledge_id": d["knowledge_id"],
                "chunk_index": 0, "score": round(1.0 - i * 0.01, 4), "seq": 0,
            })
        return out

    async def hybrid_search(self, **_):
        return []

    async def create_kb(self, *, name, embedding_model_id, trace_id=None, **_):
        self._kb += 1
        return f"kb-{self._kb}"

    async def initialize_kb(self, kb_id, **_):
        return None

    async def get_initialization_config(self, kb_id, *, trace_id=None):
        return {}

    async def upload_file(self, *, kb_id, content, file_name, mime, metadata=None, channel=None, trace_id=None):
        if self.upload_fail:
            raise WeKnoraError("weknora_down", "底座不可用")
        self._doc += 1
        self.uploads.append(content)
        return {"id": f"doc-{self._doc}", "parse_status": "processing", "file_hash": "h"}

    async def get_knowledge(self, knowledge_id, *, trace_id=None):
        return {"id": knowledge_id, "parse_status": "completed"}

    async def delete_knowledge(self, knowledge_id, *, trace_id=None):
        if self.reparse_delete_fail:
            raise WeKnoraError("weknora_down", "删除失败")
        self.deleted.append(knowledge_id)
        return None

    async def reparse_knowledge(self, *, kb_id, knowledge_id, content, file_name, mime, metadata=None, channel=None, trace_id=None):
        if knowledge_id:
            try:
                await self.delete_knowledge(knowledge_id, trace_id=trace_id)
            except WeKnoraError:
                pass  # 删除失败被吞（按设计不阻断），继续重传
        return await self.upload_file(
            kb_id=kb_id, content=content, file_name=file_name, mime=mime,
            metadata=metadata, channel=channel, trace_id=trace_id,
        )


class FakeScrubLLM:
    provider = "deepseek"
    model = "deepseek-chat"

    async def chat_completion(self, messages, *, temperature=0.2, model=None, json_object=True, trace_id=None):
        system = messages[0]["content"] if messages else ""
        if "脱敏" in system:
            return (messages[1]["content"] if len(messages) > 1 else "").replace("敏感", "【脱敏】")
        return "【答案】"


def _install(weknora, llm=None):
    app.dependency_overrides[get_weknora_client] = lambda: weknora
    app.dependency_overrides[get_llm_client] = lambda: llm or FakeScrubLLM()


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.pop(get_weknora_client, None)
    app.dependency_overrides.pop(get_llm_client, None)


async def _insert_stale_failed_asset(db_session, *, index_status="index_failed", doc_id=_STALE_DOC):
    """插入一个 active 项目 Alpha 资产，其 version 残留 weknora_doc_id 但 index_status 非 indexed。"""
    asset_id = uuid.uuid4()
    asset = KnowledgeAsset(
        id=asset_id, title="残留旧doc的失败资产", scope="project", zone="material",
        asset_type="deliverable", owner_user_id=USER_CONSULTANT, maintainer_user_id=USER_CONSULTANT,
        project_id=PROJECT_ALPHA, visibility="project_only", confidentiality_level="L2",
        ai_access_level="A2", asset_status="active", lifecycle_phase_key="交付",
    )
    version = KnowledgeAssetVersion(
        asset_id=asset_id, version_no="v1", version_status="active", created_by=USER_CONSULTANT,
        weknora_kb_id=_ALPHA_KB, weknora_doc_id=doc_id, weknora_parse_status="failed",
        index_status=index_status,  # 残留 doc 但未成功索引
    )
    asset.versions.append(version)
    asset.current_version_id = version.id
    s = KnowledgeAssetSummary(summary_type="detailed", content="失败资产摘要。")
    s.version = version
    asset.summaries.append(s)
    asset.tags.append(KnowledgeAssetTag(tag_name="交付物"))
    db_session.add(asset)
    await db_session.commit()
    return str(asset_id)


# ---------------------------------------------------------------------------
# 1. 批量召回不映射 index_failed 旧 doc
# ---------------------------------------------------------------------------
async def test_recall_skips_index_failed_stale_doc(client, db_session):
    asset_id = await _insert_stale_failed_asset(db_session)
    docs = [{"knowledge_id": _STALE_DOC, "kb_id": _ALPHA_KB, "content": "残留旧doc敏感内容"}]
    _install(FakeSearchWK(docs))
    resp = await client.post(SEARCH, headers=_hdr(USER_CONSULTANT), json={"query": "交付", "scope": "project"})
    assert resp.status_code == 200, resp.text
    ids = {c["asset_id"] for c in resp.json()["cards"]}
    # index_failed 资产即使底座旧 doc 被 search 返回，也不映射回资产、不出现在卡片。
    assert asset_id not in ids
    _assert_no_leak(resp.text)


async def test_recall_includes_when_indexed(client, db_session):
    """对照：同样的资产若 index_status=indexed，则正常召回——证明过滤项是 index_status 而非别的。"""
    asset_id = await _insert_stale_failed_asset(db_session, index_status="indexed", doc_id="wk-doc-ok-indexed")
    docs = [{"knowledge_id": "wk-doc-ok-indexed", "kb_id": _ALPHA_KB, "content": "已索引内容"}]
    _install(FakeSearchWK(docs))
    resp = await client.post(SEARCH, headers=_hdr(USER_CONSULTANT), json={"query": "交付", "scope": "project"})
    assert resp.status_code == 200, resp.text
    ids = {c["asset_id"] for c in resp.json()["cards"]}
    assert asset_id in ids


# ---------------------------------------------------------------------------
# 2. 单资产原文 chunk 不读取 index_failed 旧 doc
# ---------------------------------------------------------------------------
async def test_stage2_original_unavailable_for_index_failed(client, db_session):
    asset_id = await _insert_stale_failed_asset(db_session)
    docs = [{"knowledge_id": _STALE_DOC, "kb_id": _ALPHA_KB, "content": "残留旧doc敏感原文"}]
    wk = FakeSearchWK(docs)
    _install(wk)
    resp = await client.post(SEARCH, headers=_hdr(USER_CONSULTANT), json={
        "query": "交付", "scope": "project", "want_original": True, "asset_id": asset_id,
    })
    assert resp.status_code == 200, resp.text
    original = resp.json()["original"]
    # index_failed → 即使有 server-only doc id，也按未索引降级，不读取底座旧 doc。
    assert original["available"] is False
    assert original["chunks"] == []
    assert original["degraded_reason"] == "original_unindexed"
    # 未对该资产的旧 doc 发起底座 search 取件（fake 未被以该 doc 调用）。
    assert "残留旧doc敏感原文" not in resp.text
    _assert_no_leak(resp.text)


# ---------------------------------------------------------------------------
# 3. reparse 失败残留旧 doc 全链路回归
# ---------------------------------------------------------------------------
async def _upload_and_confirm_indexed(client, db_session, ok_wk):
    """用成功 fake 走 upload+confirm 得到 indexed 资产，返回 asset_id 与其 doc_id。"""
    app.dependency_overrides[get_weknora_client] = lambda: ok_wk
    r = await client.post(UPLOAD, headers=_hdr(USER_CONSULTANT), files={"file": ("d.txt", b"reparse stale body", "text/plain")})
    task_id = r.json()["ingest_task_id"]
    r2 = await client.post(f"/api/v1/ingest/{task_id}/confirm", headers=_hdr(USER_CONSULTANT), json={
        "title": "reparse残留资产", "summary": "摘要", "tags": ["t"], "target_scope": "project",
        "target_project_id": str(PROJECT_ALPHA), "asset_type": "methodology",
        "confidentiality_level": "L2", "ai_access_level": "A2",
    })
    assert r2.status_code == 200, r2.text
    assert r2.json()["index_status"] == "indexed"
    asset_id = r2.json()["result_asset_id"]
    v = (await db_session.execute(
        select(KnowledgeAssetVersion).where(KnowledgeAssetVersion.asset_id == uuid.UUID(asset_id))
    )).scalar_one()
    return asset_id, v.weknora_doc_id


def _enable_weknora(monkeypatch, embedding="test-embed"):
    from app.core.config import get_settings

    monkeypatch.setattr("app.services.ingest.weknora_enabled", lambda: True)
    monkeypatch.setattr("app.services.knowledge.weknora_enabled", lambda: True)
    monkeypatch.setattr("app.services.jobs.indexing_operations.weknora_enabled", lambda: True)
    monkeypatch.setattr(get_settings(), "weknora_embedding_model_id", embedding)


async def test_reparse_failure_leaves_stale_doc_not_retrievable(client, db_session, monkeypatch):
    _enable_weknora(monkeypatch)
    # 1) 先得到一个 indexed 资产（doc-old）。
    ok = FakeSearchWK([])
    asset_id, doc_old = await _upload_and_confirm_indexed(client, db_session, ok)
    assert doc_old

    # 2) 人为把解析状态置为 failed（reparse 选取条件），doc 仍在。
    v = (await db_session.execute(
        select(KnowledgeAssetVersion).where(KnowledgeAssetVersion.asset_id == uuid.UUID(asset_id))
    )).scalar_one()
    v.weknora_parse_status = "failed"
    await db_session.commit()

    # 3) reparse：删旧 doc 失败（被吞）+ 重传失败 → version 变 index_failed，可能仍残留 doc-old。
    bad = FakeSearchWK([], reparse_delete_fail=True, upload_fail=True)
    app.dependency_overrides[get_weknora_client] = lambda: bad
    rj = await client.post(REPARSE, headers=_hdr(USER_ADMIN_ONLY), json={
        "scope": "project", "project_id": str(PROJECT_ALPHA), "parse_statuses": ["failed"], "limit": 50,
    })
    assert rj.status_code == 202, rj.text
    body = rj.json()
    # job 仍按 PBC-15 语义统计失败。
    assert body["total_count"] >= 1
    assert body["failed_count"] >= 1
    assert body["status"] in ("completed_with_errors", "failed")

    # 作业在独立 session 提交 index_failed；清掉本 session 身份映射缓存以读到最新值。
    db_session.expire_all()
    v2 = (await db_session.execute(
        select(KnowledgeAssetVersion).where(KnowledgeAssetVersion.asset_id == uuid.UUID(asset_id))
    )).scalar_one()
    assert v2.index_status == "index_failed"

    # 4) 现在 fake search 仍能返回残留旧 doc——但平台不得召回 / 不得给原文。
    docs = [{"knowledge_id": v2.weknora_doc_id or doc_old, "kb_id": v2.weknora_kb_id or _ALPHA_KB, "content": "残留旧doc内容"}]
    _install(FakeSearchWK(docs))
    r_search = await client.post(SEARCH, headers=_hdr(USER_CONSULTANT), json={"query": "reparse", "scope": "project"})
    ids = {c["asset_id"] for c in r_search.json()["cards"]}
    assert asset_id not in ids
    r_orig = await client.post(SEARCH, headers=_hdr(USER_CONSULTANT), json={
        "query": "reparse", "scope": "project", "want_original": True, "asset_id": asset_id,
    })
    orig = r_orig.json()["original"]
    assert orig["available"] is False
    assert orig["chunks"] == []
    _assert_no_leak(r_search.text)
    _assert_no_leak(r_orig.text)
