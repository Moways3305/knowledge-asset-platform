"""索引状态可见性 + 失败重试 + 运维面板测试。

覆盖：知识列表/详情返回安全 index_status（无 WeKnora server-only 字段）；owner / 项目 PM /
治理角色可重试 index_failed 资产；无权 / 纯 admin 被拒；重试仍失败保留资产；indexed 重复重试 409；
admin ops 索引面板只回安全计数 + 失败列表（纯 admin 标题隐藏）。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.main import app
from app.models.knowledge import KnowledgeAssetVersion
from app.seed.dev_seed import (
    PROJECT_ALPHA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_PROJECT_MANAGER,
)
from app.services.weknora_client import WeKnoraError, get_weknora_client

UPLOAD = "/api/v1/ingest/upload"
_TXT = "索引重试测试\n标题\n正文内容。".encode()


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


class FakeWK:
    """可切换成功 / 失败的 fake WeKnora（含初始化接口）。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.uploads: list[str] = []
        self._kb = 0
        self._doc = 0

    async def create_kb(self, *, name, embedding_model_id, trace_id=None, **_):
        self._kb += 1
        return f"kb-{self._kb}"

    async def initialize_kb(self, kb_id, **_):
        return None

    async def get_initialization_config(self, kb_id, *, trace_id=None):
        return {}

    async def upload_file(
        self, *, kb_id, content, file_name, mime, metadata=None, channel=None, trace_id=None
    ):
        if self.fail:
            raise WeKnoraError("weknora_down", "底座不可用")
        self._doc += 1
        doc = f"doc-{self._doc}"
        self.uploads.append(doc)
        return {"id": doc, "parse_status": "processing", "file_hash": "h"}

    async def get_knowledge(self, knowledge_id, *, trace_id=None):
        return {"id": knowledge_id, "parse_status": "completed"}

    async def delete_knowledge(self, knowledge_id, *, trace_id=None):
        return None

    async def search(self, **_):
        return []

    async def hybrid_search(self, **_):
        return []


async def _async_return(val):
    return val


def _enable(monkeypatch, fake, *, embedding="test-embed"):
    from app.services.weknora_model_selection import ResolvedModels

    monkeypatch.setattr("app.services.ingest.weknora_enabled", lambda: True)
    monkeypatch.setattr("app.services.knowledge.weknora_enabled", lambda: True)
    # 绕过 DB resolve（测试无需配置 WeknoraDefaultModels 行），直接返回测试用 ResolvedModels。
    _resolved = ResolvedModels(
        embedding_model_id=embedding, explicit_embedding=False, chat_model_id="test-chat"
    )
    monkeypatch.setattr(
        "app.services.indexing.resolve_models_for_kb",
        lambda *_a, **_kw: _async_return(_resolved),
    )
    app.dependency_overrides[get_weknora_client] = lambda: fake


def _set_client(fake):
    app.dependency_overrides[get_weknora_client] = lambda: fake


async def _upload(client, user, *, content=_TXT, file_name="doc.txt"):
    r = await client.post(
        UPLOAD, headers=_hdr(user), files={"file": (file_name, content, "text/plain")}
    )
    return r.json()["ingest_task_id"]


def _payload(scope, project_id, **over):
    base = {
        "title": "索引重试资产",
        "summary": "摘要",
        "tags": ["t"],
        "target_scope": scope,
        "asset_type": "methodology",
        "confidentiality_level": "L2",
        "ai_access_level": "A2",
    }
    if project_id is not None:
        base["target_project_id"] = str(project_id)
    base.update(over)
    return base


async def _confirm(client, user, task_id, *, scope="personal", project_id=None, **over):
    return await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(user),
        json=_payload(scope, project_id, **over),
    )


async def _make_index_failed(
    client,
    monkeypatch,
    user,
    *,
    scope="personal",
    project_id=None,
    content=_TXT,
    title="索引重试资产",
):
    """用失败 fake 走 confirm，生成一个已落库但 index_failed 的资产，返回 asset_id。"""
    _enable(monkeypatch, FakeWK(fail=True))
    task_id = await _upload(client, user, content=content)
    r = await _confirm(client, user, task_id, scope=scope, project_id=project_id, title=title)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["index_status"] == "index_failed"
    return body["result_asset_id"]


# ---------------------------------------------------------------------------
# 列表 / 详情安全索引状态
# ---------------------------------------------------------------------------
async def test_detail_exposes_safe_index_status_no_leak(client, monkeypatch):
    ok = FakeWK()
    _enable(monkeypatch, ok)
    try:
        task_id = await _upload(client, USER_CONSULTANT)
        r = await _confirm(client, USER_CONSULTANT, task_id)
        asset_id = r.json()["result_asset_id"]
        d = await client.get(f"/api/v1/knowledge/{asset_id}", headers=_hdr(USER_CONSULTANT))
        assert d.status_code == 200
        body = d.json()
        assert body["index_status"] == "indexed"
        assert "weknora_parse_status" in body
        # indexed 资产不可重试。
        assert body["access_info"]["can_retry_index"] is False
        # 安全：绝不暴露 WeKnora server-only 字段。
        for token in [
            "weknora_kb_id",
            "weknora_doc_id",
            "kb-",
            "doc-",
            "storage_ref",
            "source_file_ref",
            "sk-",
        ]:
            assert token not in d.text
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_list_shows_index_status(client, monkeypatch):
    asset_id = await _make_index_failed(client, monkeypatch, USER_CONSULTANT)
    try:
        my = await client.get("/api/v1/my/knowledge", headers=_hdr(USER_CONSULTANT))
        item = next(i for i in my.json()["items"] if i["id"] == asset_id)
        assert item["index_status"] == "index_failed"
        assert item["access_info"]["can_retry_index"] is True
        for token in ["weknora_kb_id", "weknora_doc_id", "kb-", "doc-"]:
            assert token not in my.text
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


# ---------------------------------------------------------------------------
# 重试：成功 / 仍失败 / 幂等
# ---------------------------------------------------------------------------
async def test_owner_retry_personal_success(client, db_session, monkeypatch):
    asset_id = await _make_index_failed(client, monkeypatch, USER_CONSULTANT)
    try:
        _set_client(FakeWK())  # 切换为成功 fake
        r = await client.post(
            f"/api/v1/knowledge/{asset_id}/retry-index", headers=_hdr(USER_CONSULTANT)
        )
        assert r.status_code == 200, r.text
        assert r.json()["index_status"] == "indexed"
        ver = (
            await db_session.execute(
                select(KnowledgeAssetVersion).where(
                    KnowledgeAssetVersion.asset_id == uuid.UUID(asset_id)
                )
            )
        ).scalar_one()
        assert ver.index_status == "indexed"
        assert ver.index_error_code is None
        # 注：weknora_parse_status 是安全字段名（允许出现）；只校验真实内部标识不泄露。
        for token in ["weknora_kb_id", "weknora_doc_id", "kb-", "doc-", "sk-"]:
            assert token not in r.text
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_retry_still_failing_keeps_index_failed(client, db_session, monkeypatch):
    asset_id = await _make_index_failed(client, monkeypatch, USER_CONSULTANT)
    try:
        _set_client(FakeWK(fail=True))  # 仍失败
        r = await client.post(
            f"/api/v1/knowledge/{asset_id}/retry-index", headers=_hdr(USER_CONSULTANT)
        )
        assert r.status_code == 200, r.text
        assert r.json()["index_status"] == "index_failed"
        assert r.json()["index_error_code"] == "weknora_call_failed"  # 上游 code 目录化
        ver = (
            await db_session.execute(
                select(KnowledgeAssetVersion).where(
                    KnowledgeAssetVersion.asset_id == uuid.UUID(asset_id)
                )
            )
        ).scalar_one()
        assert ver.index_status == "index_failed"
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_retry_source_file_unreadable_returns_safe_json_not_coroutine(
    client, db_session, monkeypatch
):
    """原文不可读时重试：必须返回正常 JSON（index_failed），不得 500、不得返回未 await 的协程。

    回归锁定：retry 的 source_file_unreadable 分支曾漏写 `await _retry_response(...)`，
    会把协程对象当响应返回（FastAPI 序列化失败 → 500 / 脏数据）。本用例钉住该错误路径。
    """
    from app.models.ingest import IngestTask

    asset_id = await _make_index_failed(client, monkeypatch, USER_CONSULTANT)
    try:
        # 把入库任务的 server-only 原文引用改成"格式合法但文件缺失"，令 read_bytes 抛 OSError。
        task = (
            (
                await db_session.execute(
                    select(IngestTask).where(IngestTask.result_asset_id == uuid.UUID(asset_id))
                )
            )
            .scalars()
            .first()
        )
        task.source_file_ref = "internal://does-not-exist.bin"
        await db_session.commit()

        _set_client(FakeWK())  # OSError 发生在触达底座之前，fake 不会被用到
        r = await client.post(
            f"/api/v1/knowledge/{asset_id}/retry-index", headers=_hdr(USER_CONSULTANT)
        )

        # 不是 500，是正常 JSON。
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["index_status"] == "index_failed"
        assert body["index_error_code"] == "source_file_unreadable"  # 目录化安全 code
        # 不泄露协程对象 / 内部存储引用 / 原文路径 / WeKnora server-only 标识。
        for token in [
            "coroutine",
            "internal://",
            "does-not-exist",
            "storage_ref",
            "source_file_ref",
            "kb-",
            "doc-",
        ]:
            assert token not in r.text

        # DB 落库为 index_failed + 安全错误码（资产保留、可再试）。
        ver = (
            await db_session.execute(
                select(KnowledgeAssetVersion).where(
                    KnowledgeAssetVersion.asset_id == uuid.UUID(asset_id)
                )
            )
        ).scalar_one()
        assert ver.index_status == "index_failed"
        assert ver.index_error_code == "source_file_unreadable"
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_retry_skipped_clears_stale_index_error(client, db_session, monkeypatch):
    """底座未启用时重试：标 skipped 并清理上一轮失败残留（error_code/message/parse_status）。"""
    asset_id = await _make_index_failed(client, monkeypatch, USER_CONSULTANT)
    try:
        # 初始：index_failed + 安全错误码非空。
        ver0 = (
            await db_session.execute(
                select(KnowledgeAssetVersion).where(
                    KnowledgeAssetVersion.asset_id == uuid.UUID(asset_id)
                )
            )
        ).scalar_one()
        assert ver0.index_status == "index_failed"
        assert ver0.index_error_code  # 非空（weknora_down）
        db_session.expunge(ver0)

        # 关闭底座后重试 → skipped，且清理旧失败残留。
        monkeypatch.setattr("app.services.knowledge.weknora_enabled", lambda: False)
        r = await client.post(
            f"/api/v1/knowledge/{asset_id}/retry-index", headers=_hdr(USER_CONSULTANT)
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["index_status"] == "skipped"
        assert body["index_error_code"] is None
        assert body["index_error_message"] is None
        assert body["weknora_parse_status"] is None

        ver = (
            await db_session.execute(
                select(KnowledgeAssetVersion).where(
                    KnowledgeAssetVersion.asset_id == uuid.UUID(asset_id)
                )
            )
        ).scalar_one()
        assert ver.index_status == "skipped"
        assert ver.index_error_code is None
        assert ver.index_error_message is None
        assert ver.weknora_parse_status is None

        # 详情刷新不再返回旧失败文案。
        d = await client.get(f"/api/v1/knowledge/{asset_id}", headers=_hdr(USER_CONSULTANT))
        dbody = d.json()
        assert dbody["index_status"] == "skipped"
        assert dbody["index_error_code"] is None
        assert dbody["index_error_message"] is None
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_retry_indexed_is_409(client, monkeypatch):
    asset_id = await _make_index_failed(client, monkeypatch, USER_CONSULTANT)
    try:
        _set_client(FakeWK())
        r1 = await client.post(
            f"/api/v1/knowledge/{asset_id}/retry-index", headers=_hdr(USER_CONSULTANT)
        )
        assert r1.json()["index_status"] == "indexed"
        # 已索引再次重试 → 409。
        r2 = await client.post(
            f"/api/v1/knowledge/{asset_id}/retry-index", headers=_hdr(USER_CONSULTANT)
        )
        assert r2.status_code == 409
        assert r2.json()["detail"]["denied_reason"] == "knowledge_index_already_indexed"
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


# ---------------------------------------------------------------------------
# 权限边界
# ---------------------------------------------------------------------------
async def test_non_owner_consultant_cannot_retry_personal(client, monkeypatch):
    asset_id = await _make_index_failed(client, monkeypatch, USER_CONSULTANT)
    try:
        _set_client(FakeWK())
        # 他人个人资产不可发现 → 404，不泄露存在性。
        r = await client.post(
            f"/api/v1/knowledge/{asset_id}/retry-index", headers=_hdr(USER_PROJECT_MANAGER)
        )
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_pure_admin_cannot_retry(client, monkeypatch):
    asset_id = await _make_index_failed(client, monkeypatch, USER_CONSULTANT)
    try:
        _set_client(FakeWK())
        r = await client.post(
            f"/api/v1/knowledge/{asset_id}/retry-index", headers=_hdr(USER_ADMIN_ONLY)
        )
        assert r.status_code in (403, 404)
        if r.status_code == 403:
            assert r.json()["detail"]["denied_reason"] == "admin_business_permission_denied"
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_project_pm_retry_and_consultant_forbidden(client, monkeypatch):
    asset_id = await _make_index_failed(
        client,
        monkeypatch,
        USER_PROJECT_MANAGER,
        scope="project",
        project_id=PROJECT_ALPHA,
        content=b"project retry content body",
        title="项目索引重试资产",
    )
    try:
        _set_client(FakeWK())
        # 项目顾问成员（非管理角色）→ 403 forbidden（可发现但无重试权）。
        r_consultant = await client.post(
            f"/api/v1/knowledge/{asset_id}/retry-index", headers=_hdr(USER_CONSULTANT)
        )
        assert r_consultant.status_code == 403
        assert r_consultant.json()["detail"]["denied_reason"] == "knowledge_index_retry_forbidden"
        # 项目经理 → 可重试。
        r_pm = await client.post(
            f"/api/v1/knowledge/{asset_id}/retry-index", headers=_hdr(USER_PROJECT_MANAGER)
        )
        assert r_pm.status_code == 200, r_pm.text
        assert r_pm.json()["index_status"] == "indexed"
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_governance_cannot_retry_project_without_membership(client, monkeypatch):
    asset_id = await _make_index_failed(
        client,
        monkeypatch,
        USER_PROJECT_MANAGER,
        scope="project",
        project_id=PROJECT_ALPHA,
        content=b"governance retry content",
        title="治理重试项目资产",
    )
    try:
        _set_client(FakeWK())
        r = await client.post(f"/api/v1/knowledge/{asset_id}/retry-index", headers=_hdr(USER_BOSS))
        assert r.status_code == 404, r.text
        assert r.json()["detail"]["denied_reason"] == "knowledge_asset_not_found"
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


# ---------------------------------------------------------------------------
# admin ops 索引面板
# ---------------------------------------------------------------------------
async def test_ops_indexing_safe_and_title_boundary(client, monkeypatch):
    asset_id = await _make_index_failed(
        client, monkeypatch, USER_CONSULTANT, title="运维面板失败资产"
    )
    try:
        # 治理角色：可见真实标题。
        gov = await client.get("/admin/ops/indexing", headers=_hdr(USER_BOSS))
        assert gov.status_code == 200
        body = gov.json()
        assert body["counts"]["index_failed"] >= 1
        assert body["title_visible"] is True
        assert any(
            it["asset_id"] == asset_id and it["title"] == "运维面板失败资产"
            for it in body["recent_failed"]
        )
        # 纯 admin：标题隐藏。
        adm = await client.get("/admin/ops/indexing", headers=_hdr(USER_ADMIN_ONLY))
        assert adm.status_code == 200
        abody = adm.json()
        assert abody["title_visible"] is False
        assert all(it["title"] == "（业务资产标题已隐藏）" for it in abody["recent_failed"])
        # 安全：无 WeKnora server-only 字段。
        for token in [
            "weknora_kb_id",
            "weknora_doc_id",
            "kb-",
            "doc-",
            "storage_ref",
            "source_file_ref",
            "sk-",
        ]:
            assert token not in gov.text and token not in adm.text
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_ops_indexing_forbidden_for_consultant(client):
    r = await client.get("/admin/ops/indexing", headers=_hdr(USER_CONSULTANT))
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "ops_viewer_required"
