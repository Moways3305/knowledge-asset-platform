"""PBC-38 模型 model_ref 穿透集成测试。

验证请求层 embedding_model_ref / rerank_model_ref 经真实 resolver 穿透到建库 / 索引链路：
- confirm 不传 → 用平台默认；显式传 → 用该模型；缺默认 → fail closed；伪造 ref → 安全错误；
- retry-index 默认不误伤已有 KB；显式冲突 → 自动切换知识库嵌入模型并更新绑定；
- personal KB create 默认 / 显式。
全程响应 / 审计不出现真实 model_id（emb-*）。

说明：WeCom Path A 与本地上传**共用**同一 `POST /ingest/{id}/confirm` 端点与同一索引代码路径，
模型穿透逻辑与来源无关；故 Path A 由 confirm 用例（默认 / 显式）等价覆盖，不另造 wecom fixture。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.main import app
from app.models.knowledge import KnowledgeAssetVersion
from app.models.weknora import WeknoraKbMapping
from app.seed.dev_seed import USER_CONSULTANT
from app.services import weknora_defaults
from app.services.weknora_client import WeKnoraError, get_weknora_client
from app.services.weknora_models import _model_ref

UPLOAD = "/api/v1/ingest/upload"
MYKB = "/api/v1/my/knowledge-base"
_TXT = "模型穿透测试\n标题\n正文内容。".encode()
_RAW_IDS = ["emb-A", "emb-B", "rr-1", "chat-1"]


def _hdr(uid):
    return {"X-Dev-User-Id": str(uid)}


class FullFakeWK:
    """记录 create_kb 实际 embedding_model_id；list_models 供 ref 解析；upload 可切换失败。"""

    def __init__(self, *, upload_fail: bool = False) -> None:
        self.upload_fail = upload_fail
        self.create_kb_calls: list[str] = []
        self._embedding = "emb-A"
        self._kb = 0
        self._doc = 0

    async def list_models(self, *, trace_id=None):
        return [
            {
                "id": "emb-A",
                "name": "embedding-a",
                "type": "Embedding",
                "source": "remote",
                "status": "active",
            },
            {
                "id": "emb-B",
                "name": "embedding-b",
                "type": "Embedding",
                "source": "remote",
                "status": "active",
            },
            {
                "id": "rr-1",
                "name": "rerank-1",
                "type": "Rerank",
                "source": "remote",
                "status": "active",
            },
            {
                "id": "chat-1",
                "name": "qwen-plus",
                "type": "KnowledgeQA",
                "source": "remote",
                "status": "active",
            },
        ]

    async def create_kb(self, *, name, embedding_model_id, trace_id=None, **_):
        self.create_kb_calls.append(embedding_model_id)
        self._kb += 1
        return f"kb-{self._kb}"

    async def initialize_kb(self, kb_id, **_):
        return None

    async def get_initialization_config(self, kb_id, *, trace_id=None):
        return {}

    async def get_kb(self, kb_id, *, trace_id=None):
        return {
            "summary_model_id": "chat-1",
            "embedding_model_id": self._embedding,
            "chunking_config": {},
            "vlm_config": {},
            "asr_config": {},
            "storage_provider_config": {},
            "extract_config": {},
            "question_generation_config": {},
        }

    async def update_initialization_config(self, kb_id, *, config, trace_id=None):
        self._embedding = config["embeddingModelId"]
        return {"success": True}

    async def upload_file(
        self, *, kb_id, content, file_name, mime, metadata=None, channel=None, trace_id=None
    ):
        if self.upload_fail:
            raise WeKnoraError("weknora_down", "底座不可用")
        self._doc += 1
        return {"id": f"doc-{self._doc}", "parse_status": "processing", "file_hash": "h"}


def _enable_real(monkeypatch, fake: FullFakeWK) -> None:
    """启用底座但**不**绕过 resolver（用真实 resolve_models_for_kb 读 DB 默认 + 解析 ref）。"""
    monkeypatch.setattr("app.services.ingest.weknora_enabled", lambda: True)
    monkeypatch.setattr("app.services.knowledge.weknora_enabled", lambda: True)
    app.dependency_overrides[get_weknora_client] = lambda: fake


def _disable() -> None:
    app.dependency_overrides.pop(get_weknora_client, None)


async def _set_default(db_session, *, embedding="emb-A", rerank=None, chat="chat-1") -> None:
    await weknora_defaults.set_defaults(
        db_session,
        embedding_model_id=embedding,
        rerank_model_id=rerank,
        chat_model_id=chat,
        multimodal_id=None,
        updated_by=None,
    )
    await db_session.commit()


async def _upload(client, user, *, content=_TXT):
    r = await client.post(
        UPLOAD, headers=_hdr(user), files={"file": ("doc.txt", content, "text/plain")}
    )
    return r.json()["ingest_task_id"]


def _payload(**over):
    base = {
        "title": "穿透资产",
        "summary": "摘要",
        "tags": ["t"],
        "target_scope": "personal",
        "confidentiality_level": "L2",
    }
    base.update(over)
    return base


async def _confirm(client, user, task_id, **over):
    return await client.post(
        f"/api/v1/ingest/{task_id}/confirm", headers=_hdr(user), json=_payload(**over)
    )


async def _version_for(db_session, asset_id):
    return (
        await db_session.execute(
            select(KnowledgeAssetVersion).where(
                KnowledgeAssetVersion.asset_id == uuid.UUID(str(asset_id))
            )
        )
    ).scalar_one()


def _assert_no_raw_id(text: str) -> None:
    for t in _RAW_IDS + ["kb-", "doc-"]:
        assert t not in text, f"不应泄露 {t}"


# ---------------------------------------------------------------------------
# confirm：默认 / 显式
# ---------------------------------------------------------------------------
async def test_confirm_uses_platform_default_when_no_ref(client, db_session, monkeypatch):
    fake = FullFakeWK()
    await _set_default(db_session, embedding="emb-A")
    _enable_real(monkeypatch, fake)
    try:
        task = await _upload(client, USER_CONSULTANT)
        r = await _confirm(client, USER_CONSULTANT, task)
        assert r.status_code == 200, r.text
        assert r.json()["index_status"] == "indexing"
        assert fake.create_kb_calls == ["emb-A"]  # 用平台默认
        _assert_no_raw_id(r.text)
    finally:
        _disable()


async def test_confirm_uses_explicit_embedding_ref(client, db_session, monkeypatch):
    fake = FullFakeWK()
    await _set_default(db_session, embedding="emb-A")  # 默认 A，但显式选 B
    _enable_real(monkeypatch, fake)
    try:
        task = await _upload(client, USER_CONSULTANT)
        r = await _confirm(client, USER_CONSULTANT, task, embedding_model_ref=_model_ref("emb-B"))
        assert r.status_code == 200, r.text
        assert r.json()["index_status"] == "indexing"
        assert fake.create_kb_calls == ["emb-B"]  # 用显式选择，而非默认 A
        _assert_no_raw_id(r.text)
    finally:
        _disable()


async def test_confirm_fail_closed_when_no_default(client, db_session, monkeypatch):
    fake = FullFakeWK()
    # 不配置任何默认。
    _enable_real(monkeypatch, fake)
    try:
        task = await _upload(client, USER_CONSULTANT)
        r = await _confirm(client, USER_CONSULTANT, task)
        assert r.status_code == 200, r.text
        assert r.json()["index_status"] == "index_failed"  # fail closed，不假成功
        assert fake.create_kb_calls == []  # 没建库
        ver = await _version_for(db_session, r.json()["result_asset_id"])
        assert ver.index_error_code == "weknora_default_model_not_configured"
        _assert_no_raw_id(r.text)
    finally:
        _disable()


async def test_confirm_fake_ref_safe_error(client, db_session, monkeypatch):
    fake = FullFakeWK()
    await _set_default(db_session, embedding="emb-A")
    _enable_real(monkeypatch, fake)
    try:
        task = await _upload(client, USER_CONSULTANT)
        r = await _confirm(client, USER_CONSULTANT, task, embedding_model_ref="bogus-ref")
        assert r.status_code == 200, r.text
        assert r.json()["index_status"] == "index_failed"
        ver = await _version_for(db_session, r.json()["result_asset_id"])
        assert ver.index_error_code == "weknora_model_not_found"
    finally:
        _disable()


# ---------------------------------------------------------------------------
# retry-index：默认不误伤 / 显式冲突锁定
# ---------------------------------------------------------------------------
async def test_retry_default_does_not_falsetrip_lock(client, db_session, monkeypatch):
    fake = FullFakeWK(upload_fail=True)  # 先让 upload 失败 → index_failed（KB 已绑定 emb-A）
    await _set_default(db_session, embedding="emb-A")
    _enable_real(monkeypatch, fake)
    try:
        task = await _upload(client, USER_CONSULTANT)
        r = await _confirm(client, USER_CONSULTANT, task)
        assert r.json()["index_status"] == "index_failed"
        asset_id = r.json()["result_asset_id"]
        # 切换成功，默认重试（不传 ref）→ 沿用已绑定 emb-A，不锁定，索引成功。
        fake.upload_fail = False
        rr = await client.post(
            f"/api/v1/knowledge/{asset_id}/retry-index", headers=_hdr(USER_CONSULTANT)
        )
        assert rr.status_code == 200, rr.text
        assert rr.json()["index_status"] == "indexing"
        assert fake.create_kb_calls == ["emb-A"]  # 未重建、未切换
    finally:
        _disable()


async def test_retry_explicit_conflict_switches_kb_embedding(client, db_session, monkeypatch):
    fake = FullFakeWK(upload_fail=True)
    await _set_default(db_session, embedding="emb-A")
    _enable_real(monkeypatch, fake)
    try:
        task = await _upload(client, USER_CONSULTANT)
        r = await _confirm(client, USER_CONSULTANT, task)
        assert r.json()["index_status"] == "index_failed"
        asset_id = r.json()["result_asset_id"]
        fake.upload_fail = False
        # 已绑定 emb-A 的 KB，显式重试要求 emb-B → 自动切换底座配置并更新绑定后索引成功。
        rr = await client.post(
            f"/api/v1/knowledge/{asset_id}/retry-index",
            headers=_hdr(USER_CONSULTANT),
            json={"embedding_model_ref": _model_ref("emb-B")},
        )
        assert rr.status_code == 200, rr.text
        assert rr.json()["index_status"] == "indexing"
        assert fake.create_kb_calls == ["emb-A"]  # 复用既有 KB，未重建
        mapping = (
            await db_session.execute(
                select(WeknoraKbMapping)
                .where(WeknoraKbMapping.scope == "personal")
                .where(WeknoraKbMapping.owner_user_id == USER_CONSULTANT)
            )
        ).scalar_one()
        assert mapping.embedding_model_id == "emb-B"
        _assert_no_raw_id(rr.text)
    finally:
        _disable()


# ---------------------------------------------------------------------------
# personal KB create：默认 / 显式
# ---------------------------------------------------------------------------
async def test_personal_create_uses_default(client, db_session, monkeypatch):
    fake = FullFakeWK()
    await _set_default(db_session, embedding="emb-A")
    _enable_real(monkeypatch, fake)
    try:
        r = await client.post(MYKB, headers=_hdr(USER_CONSULTANT), json={"display_name": "默认库"})
        assert r.status_code == 200, r.text
        assert r.json()["embedding_model_ref"] == _model_ref("emb-A")
        assert r.json()["embedding_model_ref"] != "emb-A"
        mapping = (
            await db_session.execute(
                select(WeknoraKbMapping)
                .where(WeknoraKbMapping.scope == "personal")
                .where(WeknoraKbMapping.owner_user_id == USER_CONSULTANT)
            )
        ).scalar_one()
        assert mapping.embedding_model_id == "emb-A"
        _assert_no_raw_id(r.text)
    finally:
        _disable()


async def test_personal_create_uses_explicit_ref(client, db_session, monkeypatch):
    fake = FullFakeWK()
    await _set_default(db_session, embedding="emb-A")  # 默认 A，显式选 B
    _enable_real(monkeypatch, fake)
    try:
        r = await client.post(
            MYKB,
            headers=_hdr(USER_CONSULTANT),
            json={"display_name": "显式库", "embedding_model_ref": _model_ref("emb-B")},
        )
        assert r.status_code == 200, r.text
        assert r.json()["embedding_model_ref"] == _model_ref("emb-B")
        mapping = (
            await db_session.execute(
                select(WeknoraKbMapping)
                .where(WeknoraKbMapping.scope == "personal")
                .where(WeknoraKbMapping.owner_user_id == USER_CONSULTANT)
            )
        ).scalar_one()
        assert mapping.embedding_model_id == "emb-B"
        assert fake.create_kb_calls == ["emb-B"]
        _assert_no_raw_id(r.text)
    finally:
        _disable()
