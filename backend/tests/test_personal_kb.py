"""个人知识库管理测试。

覆盖三个端点（POST/GET/PUT /api/v1/my/knowledge-base）的：
- 创建正常流 + 幂等（已 active 不重复建、不改名）；
- 创建命中 init_failed 时重试初始化；
- 改名同步底座；改名时底座同步失败降级（平台侧不回滚 + weknora_sync_failed 标记）；
- owner-only：业务用户只能管自己的 KB；纯 admin 被拒；
- GET 状态（资产计数 + index 分布 + 安全 embedding_model_ref，绝不含 raw id / kb id）；
- 无泄漏：响应与审计不含 weknora_kb_id / raw embedding id / api_key / storage / chunking。
"""

from __future__ import annotations

from sqlalchemy import select

from app.main import app
from app.models.audit import AuditEvent
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.weknora import WeknoraKbMapping
from app.seed.dev_seed import USER_ADMIN_ONLY, USER_CONSULTANT, USER_PROJECT_MANAGER
from app.services import weknora_models
from app.services.weknora_client import WeKnoraError, get_weknora_client

MYKB = "/api/v1/my/knowledge-base"

# 哨兵：底座返回的 kb id 与 raw embedding id 绝不应出现在响应/审计中。
_SECRET_KB_ID = "wk-secret-personal-kb-001"
_RAW_EMBED = "raw-embed-model-xyz"

_LEAK = [
    _SECRET_KB_ID,
    _RAW_EMBED,
    "weknora_kb_id",
    "kb_id",
    "api_key",
    "sk-",
    "storage",
    "chunking",
    "embedding_model_id",
]


def _hdr(uid):
    return {"X-Dev-User-Id": str(uid)}


def _assert_no_leak(text: str) -> None:
    for t in _LEAK:
        assert t not in text, f"不应泄露 {t}：{text}"


class _FakeWeKnora:
    """记录 create/initialize/update_kb 调用；可配置失败点。"""

    def __init__(self, *, init_fail_times: int = 0, update_fail: bool = False) -> None:
        self.init_fail_times = init_fail_times
        self.update_fail = update_fail
        self.created: list[str] = []
        self.create_names: list[str] = []
        self.initialized: list[str] = []
        self.updated: list[tuple[str, str | None]] = []
        self._init_calls = 0

    async def create_kb(self, *, name, embedding_model_id, trace_id=None, **_):
        self.created.append(_SECRET_KB_ID)
        self.create_names.append(name)
        return _SECRET_KB_ID

    async def initialize_kb(self, kb_id, **_):
        self._init_calls += 1
        if self._init_calls <= self.init_fail_times:
            raise WeKnoraError("weknora_init_failed", "初始化失败")
        self.initialized.append(kb_id)

    async def update_kb(self, kb_id, *, name=None, description=None, trace_id=None):
        if self.update_fail:
            raise WeKnoraError("weknora_update_failed", "底座改名失败")
        self.updated.append((kb_id, name))
        return {"id": kb_id, "name": name}


def _enable_weknora(monkeypatch, fake: _FakeWeKnora) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr("app.services.weknora_client.weknora_enabled", lambda: True)
    monkeypatch.setattr("app.services.weknora_kb.weknora_enabled", lambda: True, raising=False)
    monkeypatch.setattr(get_settings(), "weknora_embedding_model_id", _RAW_EMBED)
    app.dependency_overrides[get_weknora_client] = lambda: fake


def _disable_override() -> None:
    app.dependency_overrides.pop(get_weknora_client, None)


async def _personal_mapping(db_session, owner) -> WeknoraKbMapping | None:
    return (
        await db_session.execute(
            select(WeknoraKbMapping)
            .where(WeknoraKbMapping.scope == "personal")
            .where(WeknoraKbMapping.owner_user_id == owner)
        )
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# 创建
# ---------------------------------------------------------------------------
async def test_create_personal_kb_happy(client, db_session, monkeypatch):
    fake = _FakeWeKnora()
    _enable_weknora(monkeypatch, fake)
    try:
        r = await client.post(
            MYKB, headers=_hdr(USER_CONSULTANT), json={"display_name": "我的研究库"}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["exists"] is True
        assert body["display_name"] == "我的研究库"
        assert body["status"] == "active"
        # 底座 create 用 display_name（可读），不是 slug。
        assert fake.create_names == ["我的研究库"]
        _assert_no_leak(r.text)
    finally:
        _disable_override()


async def test_create_defaults_name_when_absent(client, monkeypatch):
    fake = _FakeWeKnora()
    _enable_weknora(monkeypatch, fake)
    try:
        r = await client.post(MYKB, headers=_hdr(USER_CONSULTANT), json={})
        assert r.status_code == 200, r.text
        assert r.json()["display_name"] == "我的知识库"
    finally:
        _disable_override()


async def test_create_is_idempotent(client, db_session, monkeypatch):
    fake = _FakeWeKnora()
    _enable_weknora(monkeypatch, fake)
    try:
        r1 = await client.post(MYKB, headers=_hdr(USER_CONSULTANT), json={"display_name": "第一次"})
        assert r1.status_code == 200, r1.text
        # 第二次创建（即便带不同名）→ 返回现有，不重复建、不改名。
        r2 = await client.post(MYKB, headers=_hdr(USER_CONSULTANT), json={"display_name": "第二次"})
        assert r2.status_code == 200, r2.text
        assert r2.json()["display_name"] == "第一次"
        assert len(fake.created) == 1, "已 active 不应重复建库"
        mappings = list(
            (
                await db_session.execute(
                    select(WeknoraKbMapping)
                    .where(WeknoraKbMapping.scope == "personal")
                    .where(WeknoraKbMapping.owner_user_id == USER_CONSULTANT)
                )
            )
            .scalars()
            .all()
        )
        assert len(mappings) == 1
    finally:
        _disable_override()


async def test_create_retries_init_failed(client, db_session, monkeypatch):
    # 首次初始化失败 → 映射 init_failed；再次创建 → 重试初始化成功 → active。
    fake = _FakeWeKnora(init_fail_times=1)
    _enable_weknora(monkeypatch, fake)
    try:
        r1 = await client.post(MYKB, headers=_hdr(USER_CONSULTANT), json={"display_name": "重试库"})
        assert r1.status_code == 200, r1.text
        assert r1.json()["status"] == "init_failed"

        r2 = await client.post(MYKB, headers=_hdr(USER_CONSULTANT), json={})
        assert r2.status_code == 200, r2.text
        assert r2.json()["status"] == "active"
        # 没有重复建库（复用既有 init_failed 映射），只重试初始化。
        assert len(fake.created) == 1
        mapping = await _personal_mapping(db_session, USER_CONSULTANT)
        assert mapping.status == "active"
        assert mapping.display_name == "重试库"  # 重试不覆盖名称
    finally:
        _disable_override()


# ---------------------------------------------------------------------------
# 查看
# ---------------------------------------------------------------------------
async def test_get_returns_exists_false_when_no_kb(client):
    r = await client.get(MYKB, headers=_hdr(USER_CONSULTANT))
    assert r.status_code == 200, r.text
    assert r.json() == {"exists": False} or r.json().get("exists") is False


async def test_get_returns_status_counts_and_safe_ref(client, db_session, monkeypatch):
    fake = _FakeWeKnora()
    _enable_weknora(monkeypatch, fake)
    try:
        await client.post(MYKB, headers=_hdr(USER_CONSULTANT), json={"display_name": "状态库"})
        # 标记顾问的个人资产版本索引状态分布。
        versions = list(
            (
                await db_session.execute(
                    select(KnowledgeAssetVersion)
                    .join(KnowledgeAsset, KnowledgeAssetVersion.asset_id == KnowledgeAsset.id)
                    .where(KnowledgeAsset.scope == "personal")
                    .where(KnowledgeAsset.owner_user_id == USER_CONSULTANT)
                    .where(KnowledgeAssetVersion.version_status == "active")
                )
            )
            .scalars()
            .all()
        )
        assert versions, "顾问应有个人资产版本"
        versions[0].index_status = "index_failed"
        await db_session.commit()

        r = await client.get(MYKB, headers=_hdr(USER_CONSULTANT))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["exists"] is True
        assert body["display_name"] == "状态库"
        assert body["status"] == "active"
        assert body["knowledge_count"] >= 1
        assert body["index_distribution"].get("index_failed", 0) >= 1
        # embedding_model_ref 是安全 HMAC 映射，非 raw id。
        assert body["embedding_model_ref"] == weknora_models._model_ref(_RAW_EMBED)
        assert body["embedding_model_ref"] != _RAW_EMBED
        _assert_no_leak(r.text)
    finally:
        _disable_override()


# ---------------------------------------------------------------------------
# 改名
# ---------------------------------------------------------------------------
async def test_rename_syncs_weknora(client, db_session, monkeypatch):
    fake = _FakeWeKnora()
    _enable_weknora(monkeypatch, fake)
    try:
        await client.post(MYKB, headers=_hdr(USER_CONSULTANT), json={"display_name": "旧名"})
        r = await client.put(MYKB, headers=_hdr(USER_CONSULTANT), json={"display_name": "新名"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["display_name"] == "新名"
        assert body["weknora_sync_failed"] is False
        # 底座 update_kb 被调用，name=新名。
        assert fake.updated and fake.updated[-1][1] == "新名"
        mapping = await _personal_mapping(db_session, USER_CONSULTANT)
        assert mapping.display_name == "新名"
        # 审计 config.personal_kb_updated，extra 含前后名 + sync_ok，无 kb_id。
        events = list(
            (
                await db_session.execute(
                    select(AuditEvent).where(AuditEvent.action == "config.personal_kb_updated")
                )
            )
            .scalars()
            .all()
        )
        assert events
        extra = events[-1].extra or {}
        assert extra.get("weknora_sync_ok") is True
        assert "kb_id" not in str(extra)
        _assert_no_leak(r.text)
    finally:
        _disable_override()


async def test_rename_weknora_failure_degrades(client, db_session, monkeypatch):
    fake = _FakeWeKnora(update_fail=True)
    _enable_weknora(monkeypatch, fake)
    try:
        await client.post(MYKB, headers=_hdr(USER_CONSULTANT), json={"display_name": "旧名"})
        r = await client.put(MYKB, headers=_hdr(USER_CONSULTANT), json={"display_name": "新名降级"})
        assert r.status_code == 200, r.text
        body = r.json()
        # 平台侧不回滚：名称已保存；底座同步失败标记 true。
        assert body["display_name"] == "新名降级"
        assert body["weknora_sync_failed"] is True
        mapping = await _personal_mapping(db_session, USER_CONSULTANT)
        assert mapping.display_name == "新名降级"
        events = list(
            (
                await db_session.execute(
                    select(AuditEvent).where(AuditEvent.action == "config.personal_kb_updated")
                )
            )
            .scalars()
            .all()
        )
        assert (events[-1].extra or {}).get("weknora_sync_ok") is False
    finally:
        _disable_override()


async def test_rename_requires_existing_kb(client, monkeypatch):
    fake = _FakeWeKnora()
    _enable_weknora(monkeypatch, fake)
    try:
        r = await client.put(MYKB, headers=_hdr(USER_CONSULTANT), json={"display_name": "无库改名"})
        assert r.status_code == 404
        assert r.json()["detail"]["denied_reason"] == "personal_kb_not_found"
    finally:
        _disable_override()


async def test_rename_rejects_blank_name(client, monkeypatch):
    fake = _FakeWeKnora()
    _enable_weknora(monkeypatch, fake)
    try:
        await client.post(MYKB, headers=_hdr(USER_CONSULTANT), json={"display_name": "x"})
        r = await client.put(MYKB, headers=_hdr(USER_CONSULTANT), json={"display_name": "   "})
        assert r.status_code == 422
    finally:
        _disable_override()


# ---------------------------------------------------------------------------
# owner-only / admin 拒绝
# ---------------------------------------------------------------------------
async def test_pure_admin_denied_on_all_endpoints(client, monkeypatch):
    fake = _FakeWeKnora()
    _enable_weknora(monkeypatch, fake)
    try:
        for method, payload in (("post", {}), ("put", {"display_name": "x"})):
            r = await getattr(client, method)(MYKB, headers=_hdr(USER_ADMIN_ONLY), json=payload)
            assert r.status_code == 403, f"{method}: {r.text}"
            assert r.json()["detail"]["denied_reason"] == "personal_kb_forbidden"
        rg = await client.get(MYKB, headers=_hdr(USER_ADMIN_ONLY))
        assert rg.status_code == 403
    finally:
        _disable_override()


async def test_owner_only_isolation_between_users(client, db_session, monkeypatch):
    fake = _FakeWeKnora()
    _enable_weknora(monkeypatch, fake)
    try:
        # 顾问建库。
        await client.post(MYKB, headers=_hdr(USER_CONSULTANT), json={"display_name": "顾问库"})
        # 另一业务用户（项目经理）GET → 看到的是自己的（不存在），绝不串到顾问的库。
        r = await client.get(MYKB, headers=_hdr(USER_PROJECT_MANAGER))
        assert r.status_code == 200, r.text
        assert r.json().get("exists") is False
    finally:
        _disable_override()


# ---------------------------------------------------------------------------
# 未配置底座降级
# ---------------------------------------------------------------------------
async def test_create_when_weknora_unconfigured_is_safe(client, db_session):
    # 不启用 WeKnora（默认 NullWeKnoraClient）→ 创建 fail-closed 安全错误，不假成功、不泄漏。
    r = await client.post(MYKB, headers=_hdr(USER_CONSULTANT), json={"display_name": "本地库"})
    assert r.status_code in (503, 409, 422), r.text
    assert "denied_reason" in r.json()["detail"]
    _assert_no_leak(r.text)
    mapping = await _personal_mapping(db_session, USER_CONSULTANT)
    assert mapping is None, "未配置底座不应留下个人 KB 映射"
