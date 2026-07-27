"""WeKnora 底座接入测试（fake client，不打真实网络）。

覆盖：KB 懒创建幂等、confirm 推原文 + 回写 doc id、parse 对账、upload 失败回滚、
内容 hash/409 去重软提示、响应/审计无 weknora_*/api_key 泄露、admin 边界不变。
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import select

import app.services.ingest as ingest_module
from app.main import app
from app.models.knowledge import KnowledgeAssetVersion
from app.seed.dev_seed import USER_ADMIN_ONLY, USER_CONSULTANT
from app.services import audit as audit_service
from app.services.weknora_client import (
    WeKnoraClient,
    WeKnoraDuplicateError,
    WeKnoraError,
    get_weknora_client,
)

UPLOAD = "/api/v1/ingest/upload"
MY = "/api/v1/my/knowledge"
_TXT = "WeKnora 接入测试\n第一行标题\n正文内容若干。".encode()


def _hdr(user_id, trace=None):
    h = {"X-Dev-User-Id": str(user_id)}
    if trace:
        h["X-Trace-Id"] = trace
    return h


class FakeWeKnora:
    """测试用 fake：可模拟成功 / 重复(409) / 上传失败 / 初始化失败；记录建库、初始化与上传。"""

    def __init__(
        self, *, fail: bool = False, duplicate: bool = False, init_fail: bool = False
    ) -> None:
        self.fail = fail
        self.duplicate = duplicate
        self.init_fail = init_fail
        self.kbs: dict[str, dict] = {}
        self.initialized: list[dict] = []  # 记录初始化调用
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

    async def initialize_kb(
        self,
        kb_id,
        *,
        llm_source=None,
        llm_model_name=None,
        embedding_source=None,
        embedding_model_name=None,
        chunk_size=None,
        chunk_overlap=None,
        separators=None,
        trace_id=None,
    ):
        if self.init_fail:
            raise WeKnoraError("weknora_init_failed", "初始化失败")
        self.initialized.append(
            {
                "kb_id": kb_id,
                "llm_source": llm_source,
                "llm_model_name": llm_model_name,
                "embedding_source": embedding_source,
                "embedding_model_name": embedding_model_name,
                "chunk_size": chunk_size,
                "separators": separators,
            }
        )

    async def get_initialization_config(self, kb_id, *, trace_id=None):
        return {"embedding_model_id": self.kbs.get(kb_id, {}).get("embedding_model_id")}

    async def upload_file(
        self, *, kb_id, content, file_name, mime, metadata=None, channel=None, trace_id=None
    ):
        if self.fail:
            raise WeKnoraError("weknora_down", "底座不可用")
        if self.duplicate:
            raise WeKnoraDuplicateError("doc-existing-1")
        self._doc += 1
        doc_id = f"doc-fake-{self._doc}"
        self.uploads.append(
            {
                "kb_id": kb_id,
                "doc_id": doc_id,
                "file_name": file_name,
                "content": content,
                "metadata": metadata,
                "channel": channel,
            }
        )
        self.parse_status[doc_id] = "processing"
        return {"id": doc_id, "parse_status": "processing", "file_hash": "h"}

    async def get_knowledge(self, knowledge_id, *, trace_id=None):
        return {
            "id": knowledge_id,
            "parse_status": self.parse_status.get(knowledge_id, "completed"),
        }

    async def delete_knowledge(self, knowledge_id, *, trace_id=None):
        return None


def _enable_weknora(monkeypatch, *, embedding: str = "test-embed"):
    """启用 WeKnora 路径。PBC-38：embedding 非空 → resolver 返回该模型；空 → 不配默认，fail-closed。"""
    from conftest import patch_default_model

    monkeypatch.setattr(ingest_module, "weknora_enabled", lambda: True)
    if embedding:
        patch_default_model(monkeypatch, embedding=embedding)


@pytest.fixture
def weknora(monkeypatch):
    """启用 WeKnora 路径并注入 fake client。"""
    fake = FakeWeKnora()
    _enable_weknora(monkeypatch)
    app.dependency_overrides[get_weknora_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_weknora_client, None)


def _install(fake, monkeypatch, *, embedding: str = "test-embed"):
    _enable_weknora(monkeypatch, embedding=embedding)
    app.dependency_overrides[get_weknora_client] = lambda: fake


async def _upload(client, user, file_name="doc.txt", content=_TXT, mime="text/plain"):
    r = await client.post(UPLOAD, headers=_hdr(user), files={"file": (file_name, content, mime)})
    return r.json()["ingest_task_id"]


def _confirm_payload(**over):
    base = {
        "title": "WeKnora 资产",
        "summary": "摘要",
        "tags": ["t"],
        "target_scope": "personal",
        "asset_type": "methodology",
        "confidentiality_level": "L2",
        "ai_access_level": "A2",
    }
    base.update(over)
    return base


async def _confirm(client, user, task_id, trace=None, **over):
    return await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(user, trace),
        json=_confirm_payload(**over),
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


async def test_initialize_kb_requires_current_contract():
    c = WeKnoraClient(base_url="http://x", api_key="sk-test")
    with pytest.raises(WeKnoraError) as ei:
        await c.initialize_kb("kb-1")
    assert ei.value.code == "weknora_init_contract_incomplete"


async def test_initialize_kb_sends_current_weknora_contract(monkeypatch):
    sent: dict = {}

    class _FakeAsyncClient:
        def __init__(self, *_, **__):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, url, json, headers):
            sent["url"] = url
            sent["json"] = json
            sent["headers"] = headers
            return httpx.Response(200, json={"success": True, "data": {}})

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    c = WeKnoraClient(base_url="http://wk", api_key="sk-test")
    await c.initialize_kb(
        "kb-secret",
        llm_source="remote",
        llm_model_name="deepseek-v4-flash",
        embedding_source="remote",
        embedding_model_name="embedding-3",
        trace_id="trc-init",
    )

    assert sent["url"] == "http://wk/api/v1/initialization/initialize/kb-secret"
    assert sent["headers"]["X-Request-ID"] == "trc-init"
    assert sent["json"] == {
        "llm": {"source": "remote", "modelName": "deepseek-v4-flash"},
        "embedding": {"source": "remote", "modelName": "embedding-3"},
        "documentSplitting": {
            "chunkSize": 512,
            "chunkOverlap": 80,
            "separators": ["\n\n", "\n", "。", "！", "？", ";", "；"],
        },
    }
    assert "embedding_model_id" not in str(sent["json"])
    assert "chat_model_id" not in str(sent["json"])


async def test_model_check_uses_weknora_stored_model_contract(monkeypatch):
    """Existing-model checks must send modelId/modelName, never credentials."""
    sent: dict = {}

    class _FakeAsyncClient:
        def __init__(self, *_, **__):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def request(self, method, url, json, headers):
            sent.update({"method": method, "url": url, "json": json, "headers": headers})
            return httpx.Response(200, json={"success": True, "data": {"success": True}})

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    c = WeKnoraClient(base_url="http://wk", api_key="sk-test")

    await c.test_embedding_model(model_id="model-internal", model="embedding-3", trace_id="trace")

    assert sent["method"] == "POST"
    assert sent["url"] == "http://wk/api/v1/initialization/embedding/test"
    assert sent["json"] == {"modelId": "model-internal", "modelName": "embedding-3"}
    assert "api_key" not in sent["json"] and "api_url" not in sent["json"]


async def test_update_initialization_config_sends_current_complete_contract(monkeypatch):
    sent: dict = {}

    async def _call(method, path, *, json=None, trace_id=None):
        sent.update(method=method, path=path, json=json, trace_id=trace_id)
        return {"updated": True}

    client = WeKnoraClient(base_url="http://wk", api_key="sk-test")
    monkeypatch.setattr(client, "_call", _call)
    config = {
        "llmModelId": "server-chat",
        "embeddingModelId": "server-embedding",
        "documentSplitting": {
            "chunkSize": 512,
            "chunkOverlap": 80,
            "separators": ["\n\n", "\n"],
        },
        "multimodal": {"enabled": False},
        "nodeExtract": {"enabled": False},
    }

    await client.update_initialization_config("server-kb", config=config, trace_id="trace-update")

    assert sent == {
        "method": "PUT",
        "path": "/initialization/config/server-kb",
        "json": config,
        "trace_id": "trace-update",
    }
    assert not any(key.endswith("_model_id") for key in sent["json"])


async def test_update_initialization_config_rejects_legacy_contract():
    client = WeKnoraClient(base_url="http://wk", api_key="sk-test")
    with pytest.raises(WeKnoraError) as exc:
        await client.update_initialization_config(
            "server-kb",
            config={"llmModelId": "server-chat", "embedding_model_id": "legacy"},
        )
    assert exc.value.code == "weknora_kb_update_contract_invalid"


def test_initialize_unwrap_error_redacts():
    # 初始化失败经 _unwrap 抛结构化 WeKnoraError（只带 code/message，不含 api_key）。
    err = httpx.Response(
        400,
        json={"success": False, "error": {"code": "weknora_init_failed", "message": "no model"}},
    )
    with pytest.raises(WeKnoraError) as ei:
        WeKnoraClient._unwrap(err)
    assert ei.value.code == "weknora_init_failed"
    assert "sk-" not in str(ei.value)


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
    ver = (
        await db_session.execute(
            select(KnowledgeAssetVersion).where(
                KnowledgeAssetVersion.asset_id == uuid.UUID(asset_id)
            )
        )
    ).scalar_one()
    assert ver.weknora_doc_id == up["doc_id"]
    assert ver.weknora_kb_id == up["kb_id"]
    assert ver.weknora_parse_status == "processing"
    # 索引成功标 indexed；建库后执行了初始化。
    assert r.json()["index_status"] == "indexed"
    assert ver.index_status == "indexed"
    assert len(weknora.initialized) == 1


async def test_kb_mapping_idempotent(client, weknora):
    # 同一用户两次 personal 入库 → 只建一个 KB。
    t1 = await _upload(client, USER_CONSULTANT, file_name="a.txt")
    await _confirm(client, USER_CONSULTANT, t1)
    t2 = await _upload(
        client, USER_CONSULTANT, file_name="b.txt", content=b"different content here"
    )
    await _confirm(client, USER_CONSULTANT, t2, title="第二份")
    assert len(weknora.kbs) == 1  # 懒创建幂等


async def test_weknora_upload_failure_keeps_asset_index_failed(client, db_session, monkeypatch):
    """底座上传失败不再整单回滚——资产保留、人工校正不丢、标 index_failed 可重试。"""
    fake = FakeWeKnora(fail=True)
    _install(fake, monkeypatch)
    try:
        task_id = await _upload(client, USER_CONSULTANT)
        r = await _confirm(client, USER_CONSULTANT, task_id, trace="trc-wk-fail")
        # 不再 502：人工确认成功，资产落库。
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "completed"
        assert body["index_status"] == "index_failed"
        asset_id = body["result_asset_id"]
        # 资产仍可见（落库未回滚）：个人知识列表出现该标题。
        my = (await client.get(MY, headers=_hdr(USER_CONSULTANT))).json()
        assert any(i["title"] == "WeKnora 资产" for i in my["items"])
        # 版本标 index_failed + 安全 error_code；无悬挂上传。
        ver = (
            await db_session.execute(
                select(KnowledgeAssetVersion).where(
                    KnowledgeAssetVersion.asset_id == uuid.UUID(asset_id)
                )
            )
        ).scalar_one()
        assert ver.index_status == "index_failed"
        assert ver.index_error_code == "weknora_call_failed"  # 上游 code 目录化
        assert fake.uploads == []
        # 审计：ingest.confirmed（落库成功）+ ingest.index_failed（索引失败，exception）。
        from app.seed.dev_seed import USER_BOSS

        trace = await client.get("/api/v1/admin/audit/trace/trc-wk-fail", headers=_hdr(USER_BOSS))
        actions = {e["action"] for e in trace.json()["items"]}
        assert "ingest.confirmed" in actions
        assert "ingest.index_failed" in actions
        assert "ingest.failed" not in actions  # 旧"整单失败"语义不再出现
        # 不泄露 kb/doc/key。
        for token in ["kb-fake", "doc-fake", "file_path", "sk-"]:
            assert token not in trace.text
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_embedding_model_missing_keeps_asset_index_failed(client, db_session, monkeypatch):
    """底座启用但 embedding 未配 → 不建 KB / 不写 active，资产保留标 index_failed。"""
    from app.models.weknora import WeknoraKbMapping

    fake = FakeWeKnora()
    _install(fake, monkeypatch, embedding="")  # 启用底座但 embedding 为空
    try:
        task_id = await _upload(client, USER_CONSULTANT)
        r = await _confirm(client, USER_CONSULTANT, task_id)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "completed"
        assert body["index_status"] == "index_failed"
        # 未建 KB、未上传、未写任何 personal 映射（不产生 active 假成功）。
        assert fake.kbs == {} and fake.uploads == []
        ver = (
            await db_session.execute(
                select(KnowledgeAssetVersion).where(
                    KnowledgeAssetVersion.asset_id == uuid.UUID(body["result_asset_id"])
                )
            )
        ).scalar_one()
        assert ver.index_status == "index_failed"
        # PBC-38：embedding 缺失 = 平台默认模型未配置（不再读 WEKNORA_EMBEDDING_MODEL_ID）。
        assert ver.index_error_code == "weknora_default_model_not_configured"
        mapping = (
            await db_session.execute(
                select(WeknoraKbMapping).where(
                    WeknoraKbMapping.scope == "personal",
                    WeknoraKbMapping.owner_user_id == USER_CONSULTANT,
                )
            )
        ).scalar_one_or_none()
        assert mapping is None
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_weknora_init_failure_keeps_asset_index_failed(client, db_session, monkeypatch):
    """建库成功但初始化失败：不写 active 假成功——资产保留、index_failed，映射置 init_failed。"""
    from app.models.weknora import WeknoraKbMapping

    fake = FakeWeKnora(init_fail=True)
    _install(fake, monkeypatch)
    try:
        task_id = await _upload(client, USER_CONSULTANT)
        r = await _confirm(client, USER_CONSULTANT, task_id)
        assert r.status_code == 200, r.text
        assert r.json()["index_status"] == "index_failed"
        # KB 已建，但映射不是 active（init_failed），未上传原文。
        assert len(fake.kbs) == 1
        assert fake.uploads == []
        mapping = (
            await db_session.execute(
                select(WeknoraKbMapping).where(
                    WeknoraKbMapping.scope == "personal",
                    WeknoraKbMapping.owner_user_id == USER_CONSULTANT,
                )
            )
        ).scalar_one()
        assert mapping.status == "init_failed"
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_weknora_init_retry_recovers(client, db_session, monkeypatch):
    """init_failed 后重试入库：ensure-initialized 重新初始化既有 KB，成功翻 active 并索引。"""
    from app.models.weknora import WeknoraKbMapping

    fail_fake = FakeWeKnora(init_fail=True)
    _install(fail_fake, monkeypatch)
    try:
        t1 = await _upload(client, USER_CONSULTANT, file_name="a.txt")
        r1 = await _confirm(client, USER_CONSULTANT, t1)
        assert r1.json()["index_status"] == "index_failed"
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)

    ok_fake = FakeWeKnora()
    _install(ok_fake, monkeypatch)
    try:
        t2 = await _upload(
            client, USER_CONSULTANT, file_name="b.txt", content=b"second content body"
        )
        r2 = await _confirm(client, USER_CONSULTANT, t2, title="第二份")
        assert r2.json()["index_status"] == "indexed"
        # 复用既有 KB（未再建新库），映射翻 active。
        assert ok_fake.kbs == {}  # 未新建 KB（命中既有 init_failed 映射）
        assert len(ok_fake.initialized) == 1  # 仅做了一次 ensure-initialized
        mapping = (
            await db_session.execute(
                select(WeknoraKbMapping).where(
                    WeknoraKbMapping.scope == "personal",
                    WeknoraKbMapping.owner_user_id == USER_CONSULTANT,
                )
            )
        ).scalar_one()
        assert mapping.status == "active"
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
        "admin_business_permission_denied",
        "ingest_confirm_forbidden",
    }
    assert weknora.uploads == []


# ---- delete_kb（整库删除 + 降级逐 doc 清理） ----
class _RecordingAsyncClient:
    """记录 delete/get 请求的 fake httpx.AsyncClient（无网络）。"""

    def __init__(self, *, delete_status=204, list_data=None, list_status=200):
        self.delete_status = delete_status
        self.list_data = list_data
        self.list_status = list_status
        self.deleted_kbs: list[str] = []
        self.deleted_docs: list[str] = []
        self.listed_kbs: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def delete(self, url, headers):
        # /knowledge-bases/{kb_id} 或 /knowledge/{doc_id}
        if "/knowledge-bases/" in url:
            self.deleted_kbs.append(url.rsplit("/", 1)[-1])
            return httpx.Response(self.delete_status, json={"success": True, "data": {}})
        # doc 删除
        self.deleted_docs.append(url.rsplit("/", 1)[-1])
        return httpx.Response(204, json={"success": True, "data": {}})

    async def get(self, url, headers):
        self.listed_kbs.append(url.split("/knowledge-bases/")[1].split("/")[0])
        return httpx.Response(
            self.list_status,
            json={"success": True, "data": self.list_data or []},
        )


async def test_delete_kb_calls_whole_kb_delete_endpoint(monkeypatch):
    fake = _RecordingAsyncClient(delete_status=204)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *_, **__: fake)
    c = WeKnoraClient(base_url="http://wk", api_key="sk-test")
    await c.delete_kb("kb-secret-1", trace_id="trc-del")
    assert fake.deleted_kbs == ["kb-secret-1"]
    # 整库删除成功 → 不走降级路径，不拉 doc 列表。
    assert fake.listed_kbs == []
    assert fake.deleted_docs == []


async def test_delete_kb_falls_back_to_per_doc_when_endpoint_unavailable(monkeypatch):
    docs = [
        {"id": "doc-1"},
        {"id": "doc-2"},
    ]
    fake = _RecordingAsyncClient(delete_status=405, list_data=docs)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *_, **__: fake)
    c = WeKnoraClient(base_url="http://wk", api_key="sk-test")
    await c.delete_kb("kb-secret-2", trace_id="trc-del")
    # 整库删除尝试过（405）→ 降级逐 doc 删除。
    assert fake.deleted_kbs == ["kb-secret-2"]
    assert fake.listed_kbs == ["kb-secret-2"]
    assert fake.deleted_docs == ["doc-1", "doc-2"]


async def test_delete_kb_fallback_tolerates_doc_list_failure(monkeypatch):
    # 库已不存在：list 接口返回错误 → 视为清理完成，不抛。
    fake = _RecordingAsyncClient(delete_status=404, list_data=None, list_status=404)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *_, **__: fake)
    c = WeKnoraClient(base_url="http://wk", api_key="sk-test")
    # 不应抛错。
    await c.delete_kb("kb-gone", trace_id="trc-del")
    assert fake.deleted_kbs == ["kb-gone"]
    assert fake.deleted_docs == []
