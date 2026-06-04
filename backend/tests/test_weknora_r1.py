"""R1 WeKnora 底座接入测试（fake client，不打真实网络）。

覆盖：KB 懒创建幂等、confirm 推原文 + 回写 doc id、parse 对账、upload 失败回滚、
内容 hash/409 去重软提示、响应/审计无 weknora_*/api_key 泄露、admin 边界不变。
"""

from __future__ import annotations

import uuid

import httpx
import pytest

import app.services.ingest as ingest_module
from app.main import app
from app.models.knowledge import KnowledgeAssetVersion
from app.services import audit as audit_service
from app.services.weknora_client import (
    WeKnoraClient,
    WeKnoraDuplicateError,
    WeKnoraError,
    get_weknora_client,
)
from app.seed.dev_seed import USER_ADMIN_ONLY, USER_CONSULTANT
from sqlalchemy import select

UPLOAD = "/api/v1/ingest/upload"
MY = "/api/v1/my/knowledge"
_TXT = "WeKnora 接入测试\n第一行标题\n正文内容若干。".encode("utf-8")


def _hdr(user_id, trace=None):
    h = {"X-Dev-User-Id": str(user_id)}
    if trace:
        h["X-Trace-Id"] = trace
    return h


class FakeWeKnora:
    """测试用 fake：可模拟成功 / 重复(409) / 失败；记录建库与上传。"""

    def __init__(self, *, fail: bool = False, duplicate: bool = False) -> None:
        self.fail = fail
        self.duplicate = duplicate
        self.kbs: dict[str, dict] = {}
        self.uploads: list[dict] = []
        self.parse_status: dict[str, str] = {}
        self._kb = 0
        self._doc = 0

    async def create_kb(self, *, name, embedding_model_id, trace_id=None, **_):
        self._kb += 1
        kb_id = f"kb-fake-{self._kb}"
        self.kbs[kb_id] = {"name": name, "embedding_model_id": embedding_model_id}
        return kb_id

    async def get_kb(self, kb_id, *, trace_id=None):
        return self.kbs.get(kb_id, {})

    async def upload_file(self, *, kb_id, content, file_name, mime, metadata=None, channel=None, trace_id=None):
        if self.fail:
            raise WeKnoraError("weknora_down", "底座不可用")
        if self.duplicate:
            raise WeKnoraDuplicateError("doc-existing-1")
        self._doc += 1
        doc_id = f"doc-fake-{self._doc}"
        self.uploads.append({"kb_id": kb_id, "doc_id": doc_id, "file_name": file_name,
                             "content": content, "metadata": metadata, "channel": channel})
        self.parse_status[doc_id] = "processing"
        return {"id": doc_id, "parse_status": "processing", "file_hash": "h"}

    async def get_knowledge(self, knowledge_id, *, trace_id=None):
        return {"id": knowledge_id, "parse_status": self.parse_status.get(knowledge_id, "completed")}

    async def delete_knowledge(self, knowledge_id, *, trace_id=None):
        return None


@pytest.fixture
def weknora(monkeypatch):
    """启用 WeKnora 路径并注入 fake client。"""
    fake = FakeWeKnora()
    monkeypatch.setattr(ingest_module, "weknora_enabled", lambda: True)
    app.dependency_overrides[get_weknora_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_weknora_client, None)


def _install(fake, monkeypatch):
    monkeypatch.setattr(ingest_module, "weknora_enabled", lambda: True)
    app.dependency_overrides[get_weknora_client] = lambda: fake


async def _upload(client, user, file_name="doc.txt", content=_TXT, mime="text/plain"):
    r = await client.post(UPLOAD, headers=_hdr(user), files={"file": (file_name, content, mime)})
    return r.json()["ingest_task_id"]


def _confirm_payload(**over):
    base = {
        "title": "WeKnora 资产", "summary": "摘要", "tags": ["t"],
        "target_scope": "personal", "asset_type": "methodology",
        "confidentiality_level": "L2", "ai_access_level": "A2",
    }
    base.update(over)
    return base


async def _confirm(client, user, task_id, trace=None, **over):
    return await client.post(
        f"/api/v1/ingest/{task_id}/confirm", headers=_hdr(user, trace), json=_confirm_payload(**over)
    )


# ---- WeKnoraClient 单测（无网络） ----
def test_client_rejects_bad_api_key():
    with pytest.raises(WeKnoraError):
        WeKnoraClient(base_url="http://x", api_key="bad-key")


def test_client_unwrap_success_error_and_409():
    ok = httpx.Response(200, json={"success": True, "data": {"id": "kb-1"}})
    assert WeKnoraClient._unwrap(ok)["id"] == "kb-1"

    err = httpx.Response(400, json={"success": False, "error": {"code": "bad", "message": "no"}})
    with pytest.raises(WeKnoraError) as ei:
        WeKnoraClient._unwrap(err)
    assert ei.value.code == "bad"

    dup = httpx.Response(409, json={"data": {"id": "doc-x"}})
    with pytest.raises(WeKnoraDuplicateError) as ed:
        WeKnoraClient._unwrap(dup)
    assert ed.value.existing_knowledge_id == "doc-x"


# ---- confirm 推送 + 回写 ----
async def test_confirm_pushes_and_writes_back(client, weknora, db_session):
    task_id = await _upload(client, USER_CONSULTANT)
    r = await _confirm(client, USER_CONSULTANT, task_id)
    assert r.status_code == 200, r.text
    assert r.json()["parse_status"] == "processing"
    # 原文字节真推进底座，metadata 带安全回链。
    assert len(weknora.uploads) == 1
    up = weknora.uploads[0]
    assert up["content"] == _TXT
    assert up["metadata"]["asset_id"] == r.json()["result_asset_id"]
    assert "confidentiality_level" in up["metadata"]
    # 业务库回写 doc/kb（server-only）。
    asset_id = r.json()["result_asset_id"]
    ver = (await db_session.execute(
        select(KnowledgeAssetVersion).where(
            KnowledgeAssetVersion.asset_id == uuid.UUID(asset_id)
        )
    )).scalar_one()
    assert ver.weknora_doc_id == up["doc_id"]
    assert ver.weknora_kb_id == up["kb_id"]
    assert ver.weknora_parse_status == "processing"


async def test_kb_mapping_idempotent(client, weknora):
    # 同一用户两次 personal 入库 → 只建一个 KB。
    t1 = await _upload(client, USER_CONSULTANT, file_name="a.txt")
    await _confirm(client, USER_CONSULTANT, t1)
    t2 = await _upload(client, USER_CONSULTANT, file_name="b.txt", content=b"different content here")
    await _confirm(client, USER_CONSULTANT, t2, title="第二份")
    assert len(weknora.kbs) == 1  # 懒创建幂等


async def test_weknora_failure_rolls_back_no_hanging_asset(client, monkeypatch):
    fake = FakeWeKnora(fail=True)
    _install(fake, monkeypatch)
    try:
        task_id = await _upload(client, USER_CONSULTANT)
        r = await _confirm(client, USER_CONSULTANT, task_id, trace="trc-wk-fail")
        assert r.status_code == 502
        assert r.json()["detail"]["denied_reason"] == "weknora_upload_failed"
        # 无悬挂资产：个人知识列表不出现该标题。
        my = (await client.get(MY, headers=_hdr(USER_CONSULTANT))).json()
        assert all(i["title"] != "WeKnora 资产" for i in my["items"])
        # 任务标记 failed + 审计 ingest.failed。
        trace = await client.get("/api/v1/admin/audit/trace/trc-wk-fail", headers=_hdr(USER_CONSULTANT))
        # consultant 无审计查询权 → 用治理身份查
        from app.seed.dev_seed import USER_BOSS
        trace = await client.get("/api/v1/admin/audit/trace/trc-wk-fail", headers=_hdr(USER_BOSS))
        actions = {e["action"] for e in trace.json()["items"]}
        assert "ingest.failed" in actions
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_weknora_duplicate_soft(client, monkeypatch):
    fake = FakeWeKnora(duplicate=True)
    _install(fake, monkeypatch)
    try:
        task_id = await _upload(client, USER_CONSULTANT)
        r = await _confirm(client, USER_CONSULTANT, task_id)
        assert r.status_code == 200
        assert r.json()["parse_status"] == "duplicate"  # 复用既有 doc，不算失败
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_refresh_parse_reconciles_status(client, weknora):
    task_id = await _upload(client, USER_CONSULTANT)
    await _confirm(client, USER_CONSULTANT, task_id)
    doc_id = weknora.uploads[0]["doc_id"]
    weknora.parse_status[doc_id] = "completed"  # 底座解析完成
    r = await client.post(f"/api/v1/ingest/{task_id}/refresh-parse", headers=_hdr(USER_CONSULTANT))
    assert r.status_code == 200
    assert r.json()["parse_status"] == "completed"


async def test_no_weknora_leak_in_response_and_audit(client, weknora):
    task_id = await _upload(client, USER_CONSULTANT)
    r = await _confirm(client, USER_CONSULTANT, task_id, trace="trc-wk-leak")
    assert r.status_code == 200
    doc_id = weknora.uploads[0]["doc_id"]
    kb_id = weknora.uploads[0]["kb_id"]
    # confirm 响应不含 kb/doc/file_path。
    for token in [kb_id, doc_id, "weknora_kb_id", "weknora_doc_id", "file_path", "sk-"]:
        assert token not in r.text
    # 审计 trace（治理视图）也不含。
    from app.seed.dev_seed import USER_BOSS
    trace = await client.get("/api/v1/admin/audit/trace/trc-wk-leak", headers=_hdr(USER_BOSS))
    actions = {e["action"] for e in trace.json()["items"]}
    assert "ingest.weknora_indexed" in actions
    for token in [kb_id, doc_id, "file_path", "sk-"]:
        assert token not in trace.text


def test_value_sanitizer_redacts_api_key():
    assert audit_service.sanitize_text("sk-secret-abc123") == "[redacted]"


async def test_admin_business_boundary_unchanged(client, weknora):
    # 纯 admin confirm 仍 403（在 WeKnora 之前）；且未建任何 KB / 上传。
    task_id = await _upload(client, USER_CONSULTANT)
    r = await _confirm(client, USER_ADMIN_ONLY, task_id)
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] in {
        "admin_business_permission_denied", "ingest_confirm_forbidden",
    }
    assert weknora.uploads == []
