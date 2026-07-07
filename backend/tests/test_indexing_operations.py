"""索引批量重试 / 显式 reparse / 后台队列测试。

覆盖：批量 retry 入队权限（admin / 治理可，普通业务用户拒）；批量执行多条 index_failed →
indexed；单条失败不影响其他条（completed_with_errors）；indexed 不被批量 retry 选中；
reparse 入队与执行（已进底座但解析异常）；refresh-parse 仍只读不触发重传；job list 不泄露
标题 / 原文 / WeKnora id / storage·source ref；纯 admin 视图不泄露业务标题；审计 extra 安全。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.main import app
from app.models.knowledge import KnowledgeAssetVersion
from app.seed.dev_seed import (
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
)
from app.services.weknora_client import WeKnoraError, get_weknora_client

UPLOAD = "/api/v1/ingest/upload"
RETRY = "/admin/ops/indexing/retry"
REPARSE = "/admin/ops/indexing/reparse"
JOBS = "/admin/ops/indexing/jobs"
_TXT = "批量索引运维测试\n标题\n正文内容。".encode()


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


class FakeWK:
    """可切换成功/失败的 fake WeKnora；记录上传/删除以断言重传行为。"""

    def __init__(self, *, fail: bool = False, fail_marker: bytes | None = None) -> None:
        self.fail = fail
        # 仅当上传内容含该标记时失败（用于"部分失败"测试，不依赖跨 session 改库）。
        self.fail_marker = fail_marker
        self.uploads: list[bytes] = []
        self.deleted: list[str] = []
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
        if self.fail or (self.fail_marker is not None and self.fail_marker in content):
            raise WeKnoraError("weknora_down", "底座不可用")
        self._doc += 1
        self.uploads.append(content)
        return {"id": f"doc-{self._doc}", "parse_status": "processing", "file_hash": "h"}

    async def get_knowledge(self, knowledge_id, *, trace_id=None):
        return {"id": knowledge_id, "parse_status": "completed"}

    async def delete_knowledge(self, knowledge_id, *, trace_id=None):
        self.deleted.append(knowledge_id)
        return None

    async def reparse_knowledge(
        self,
        *,
        kb_id,
        knowledge_id,
        content,
        file_name,
        mime,
        metadata=None,
        channel=None,
        trace_id=None,
    ):
        if knowledge_id:
            await self.delete_knowledge(knowledge_id, trace_id=trace_id)
        return await self.upload_file(
            kb_id=kb_id,
            content=content,
            file_name=file_name,
            mime=mime,
            metadata=metadata,
            channel=channel,
            trace_id=trace_id,
        )

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
    monkeypatch.setattr("app.services.jobs.indexing_operations.weknora_enabled", lambda: True)
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


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.pop(get_weknora_client, None)


async def _upload(client, user, *, content=_TXT, file_name="doc.txt"):
    r = await client.post(
        UPLOAD, headers=_hdr(user), files={"file": (file_name, content, "text/plain")}
    )
    return r.json()["ingest_task_id"]


def _payload(scope, project_id, **over):
    base = {
        "title": "批量索引资产",
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
    title="批量索引资产",
):
    """用失败 fake 走 confirm，生成一个已落库但 index_failed 的资产，返回 asset_id。"""
    _enable(monkeypatch, FakeWK(fail=True))
    task_id = await _upload(client, user, content=content)
    r = await _confirm(client, user, task_id, scope=scope, project_id=project_id, title=title)
    assert r.status_code == 200, r.text
    assert r.json()["index_status"] == "index_failed"
    return r.json()["result_asset_id"]


async def _make_indexed(client, monkeypatch, user, *, content=_TXT, title="已索引资产"):
    """用成功 fake 走 confirm，生成一个 indexed 资产，返回 asset_id。"""
    ok = FakeWK()
    _enable(monkeypatch, ok)
    task_id = await _upload(client, user, content=content)
    r = await _confirm(client, user, task_id, title=title)
    assert r.status_code == 200, r.text
    assert r.json()["index_status"] == "indexed"
    return r.json()["result_asset_id"]


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------
async def test_batch_retry_requires_ops_viewer(client, monkeypatch):
    await _make_index_failed(client, monkeypatch, USER_CONSULTANT)
    # 普通业务用户（顾问）无 ops 权 → 403。
    _set_client(FakeWK())
    r = await client.post(RETRY, headers=_hdr(USER_CONSULTANT), json={"scope": "all"})
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "ops_viewer_required"


async def test_batch_retry_admin_allowed(client, monkeypatch):
    await _make_index_failed(client, monkeypatch, USER_CONSULTANT)
    _set_client(FakeWK())
    r = await client.post(RETRY, headers=_hdr(USER_ADMIN_ONLY), json={"scope": "all"})
    assert r.status_code == 202, r.text


async def test_batch_retry_governance_allowed(client, monkeypatch):
    await _make_index_failed(client, monkeypatch, USER_CONSULTANT)
    _set_client(FakeWK())
    r = await client.post(RETRY, headers=_hdr(USER_BOSS), json={"scope": "all"})
    assert r.status_code == 202, r.text


# ---------------------------------------------------------------------------
# 批量 retry 执行
# ---------------------------------------------------------------------------
async def test_batch_retry_indexes_failed_assets(client, db_session, monkeypatch):
    a1 = await _make_index_failed(
        client, monkeypatch, USER_CONSULTANT, content=b"alpha body one", title="失败资产1"
    )
    a2 = await _make_index_failed(
        client, monkeypatch, USER_CONSULTANT, content=b"beta body two", title="失败资产2"
    )
    # 切换为成功底座，发起批量 retry（eager 内联跑完）。
    ok = FakeWK()
    _enable(monkeypatch, ok)
    r = await client.post(
        RETRY,
        headers=_hdr(USER_ADMIN_ONLY),
        json={"scope": "all", "statuses": ["index_failed"], "limit": 50},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["operation_type"] == "retry_index"
    assert body["status"] == "completed"
    assert body["total_count"] >= 2
    assert body["success_count"] >= 2
    assert body["failed_count"] == 0
    # 两条资产现在均 indexed。
    for aid in (a1, a2):
        v = (
            await db_session.execute(
                select(KnowledgeAssetVersion).where(
                    KnowledgeAssetVersion.asset_id == uuid.UUID(aid)
                )
            )
        ).scalar_one()
        assert v.index_status == "indexed"


async def test_batch_retry_partial_failure_completed_with_errors(client, monkeypatch):
    """一条可重传成功、一条底座仍失败 → completed_with_errors，成功条不受影响。

    注：本测试不取 `db_session` 夹具——内存 SQLite StaticPool 单连接下，额外 session 的
    开放事务会与 job 内 `rollback()` 互相干扰（仅测试态）；改由 job 返回的安全计数与
    单条 retry-index 的 409 / 200 复核最终状态。
    """
    a_ok = await _make_index_failed(
        client, monkeypatch, USER_CONSULTANT, content=b"recoverable body", title="可恢复"
    )
    a_bad = await _make_index_failed(
        client, monkeypatch, USER_CONSULTANT, content=b"FAILME lost body", title="仍失败"
    )

    # 选择性失败 fake：只有含 FAILME 标记的内容上传失败（a_bad），a_ok 正常索引。
    sel = FakeWK(fail_marker=b"FAILME")
    _enable(monkeypatch, sel)
    r = await client.post(RETRY, headers=_hdr(USER_ADMIN_ONLY), json={"scope": "all", "limit": 50})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "completed_with_errors"
    assert body["total_count"] == 2
    assert body["success_count"] >= 1
    assert body["failed_count"] >= 1
    # 复核：a_ok 已 indexed → 再次单条 retry 返回 409；a_bad 仍 index_failed → 单条 retry 可再试（200）。
    r_ok = await client.post(f"/api/v1/knowledge/{a_ok}/retry-index", headers=_hdr(USER_CONSULTANT))
    assert r_ok.status_code == 409
    assert r_ok.json()["detail"]["denied_reason"] == "knowledge_index_already_indexed"
    # a_bad 仍 index_failed（未被 batch 误标）→ 换成功 fake 单条重试可恢复为 indexed。
    _set_client(FakeWK())
    r_bad = await client.post(
        f"/api/v1/knowledge/{a_bad}/retry-index", headers=_hdr(USER_CONSULTANT)
    )
    assert r_bad.status_code == 200
    assert r_bad.json()["index_status"] == "indexed"


async def test_batch_retry_does_not_select_indexed(client, db_session, monkeypatch):
    indexed = await _make_indexed(
        client, monkeypatch, USER_CONSULTANT, content=b"already indexed body"
    )
    # 记录其 doc_id，确认批量 retry 不会动它。
    v0 = (
        await db_session.execute(
            select(KnowledgeAssetVersion).where(
                KnowledgeAssetVersion.asset_id == uuid.UUID(indexed)
            )
        )
    ).scalar_one()
    doc0 = v0.weknora_doc_id
    db_session.expunge(v0)

    ok = FakeWK()
    _enable(monkeypatch, ok)
    r = await client.post(
        RETRY,
        headers=_hdr(USER_ADMIN_ONLY),
        json={"scope": "all", "statuses": ["index_failed", "skipped", "not_indexed"], "limit": 50},
    )
    assert r.status_code == 202, r.text
    # indexed 资产未被重传（doc_id 不变，无新上传命中它）。
    v = (
        await db_session.execute(
            select(KnowledgeAssetVersion).where(
                KnowledgeAssetVersion.asset_id == uuid.UUID(indexed)
            )
        )
    ).scalar_one()
    assert v.index_status == "indexed"
    assert v.weknora_doc_id == doc0


# ---------------------------------------------------------------------------
# 显式 reparse
# ---------------------------------------------------------------------------
async def test_reparse_refreshes_parse_status(client, db_session, monkeypatch):
    indexed = await _make_indexed(
        client, monkeypatch, USER_CONSULTANT, content=b"reparse target body"
    )
    # 人为把解析状态置为 failed（模拟解析异常），doc 仍在底座。
    v = (
        await db_session.execute(
            select(KnowledgeAssetVersion).where(
                KnowledgeAssetVersion.asset_id == uuid.UUID(indexed)
            )
        )
    ).scalar_one()
    old_doc = v.weknora_doc_id
    v.weknora_parse_status = "failed"
    await db_session.commit()
    db_session.expunge(v)

    ok = FakeWK()
    _enable(monkeypatch, ok)
    r = await client.post(
        REPARSE,
        headers=_hdr(USER_ADMIN_ONLY),
        json={"scope": "all", "parse_statuses": ["failed", "pending"], "limit": 50},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["operation_type"] == "reparse"
    assert body["status"] in ("completed", "completed_with_errors")
    assert body["success_count"] >= 1
    # reparse 受控重传：旧 doc 被删、重新上传原文触发解析刷新。
    assert old_doc in ok.deleted
    assert len(ok.uploads) >= 1  # 确实重传了原文
    v2 = (
        await db_session.execute(
            select(KnowledgeAssetVersion).where(
                KnowledgeAssetVersion.asset_id == uuid.UUID(indexed)
            )
        )
    ).scalar_one()
    assert v2.index_status == "indexed"
    # 解析状态已由 failed 刷新为底座新返回的 processing。
    assert v2.weknora_parse_status == "processing"


async def test_reparse_requires_ops_viewer(client, monkeypatch):
    await _make_indexed(client, monkeypatch, USER_CONSULTANT)
    _set_client(FakeWK())
    r = await client.post(REPARSE, headers=_hdr(USER_CONSULTANT), json={"scope": "all"})
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "ops_viewer_required"


# ---------------------------------------------------------------------------
# refresh-parse 仍只读
# ---------------------------------------------------------------------------
async def test_refresh_parse_stays_readonly(client, db_session, monkeypatch):
    """refresh-parse 只读对账底座解析状态，绝不触发删除 / 重传。"""
    from app.models.ingest import IngestTask

    indexed = await _make_indexed(
        client, monkeypatch, USER_CONSULTANT, content=b"refresh parse body"
    )
    task_id = (
        await db_session.execute(
            select(IngestTask.id).where(IngestTask.result_asset_id == uuid.UUID(indexed))
        )
    ).scalar_one()
    # 把解析状态置为 processing（refresh 会去读底座对账）。
    v = (
        await db_session.execute(
            select(KnowledgeAssetVersion).where(
                KnowledgeAssetVersion.asset_id == uuid.UUID(indexed)
            )
        )
    ).scalar_one()
    old_doc = v.weknora_doc_id
    v.weknora_parse_status = "processing"
    await db_session.commit()

    ok = FakeWK()
    _set_client(ok)
    monkeypatch.setattr("app.services.ingest.weknora_enabled", lambda: True)
    r = await client.post(f"/api/v1/ingest/{task_id}/refresh-parse", headers=_hdr(USER_CONSULTANT))
    assert r.status_code == 200, r.text
    # refresh 只读：未触发删除 / 重传。
    assert ok.deleted == []
    assert ok.uploads == []
    v2 = (
        await db_session.execute(
            select(KnowledgeAssetVersion).where(
                KnowledgeAssetVersion.asset_id == uuid.UUID(indexed)
            )
        )
    ).scalar_one()
    assert v2.weknora_doc_id == old_doc


# ---------------------------------------------------------------------------
# job list 安全 / 无泄露
# ---------------------------------------------------------------------------
async def test_jobs_list_no_leak(client, monkeypatch):
    await _make_index_failed(client, monkeypatch, USER_CONSULTANT, title="机密标题不应出现")
    ok = FakeWK()
    _enable(monkeypatch, ok)
    await client.post(RETRY, headers=_hdr(USER_ADMIN_ONLY), json={"scope": "all"})
    r = await client.get(JOBS, headers=_hdr(USER_ADMIN_ONLY))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    job = body["items"][0]
    assert job["operation_type"] == "retry_index"
    assert "status" in job and "total_count" in job
    # 安全：无标题 / 原文 / WeKnora id / 存储引用 / 文件名 / token。
    for token in [
        "机密标题不应出现",
        "weknora_kb_id",
        "weknora_doc_id",
        "kb-",
        "doc-",
        "storage_ref",
        "source_file_ref",
        "download_url",
        "api_key",
        "sk-",
        "cookie",
        "doc.txt",
    ]:
        assert token not in r.text, token


async def test_jobs_list_requires_ops_viewer(client):
    r = await client.get(JOBS, headers=_hdr(USER_CONSULTANT))
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "ops_viewer_required"


async def test_pure_admin_jobs_no_title_leak(client, monkeypatch):
    await _make_index_failed(client, monkeypatch, USER_CONSULTANT, title="纯admin不可见标题")
    ok = FakeWK()
    _enable(monkeypatch, ok)
    await client.post(RETRY, headers=_hdr(USER_ADMIN_ONLY), json={"scope": "all"})
    r = await client.get(JOBS, headers=_hdr(USER_ADMIN_ONLY))
    assert "纯admin不可见标题" not in r.text


# ---------------------------------------------------------------------------
# 审计 extra 安全
# ---------------------------------------------------------------------------
async def test_audit_extra_is_safe(client, db_session, monkeypatch):
    from app.models.audit import AuditEvent

    await _make_index_failed(client, monkeypatch, USER_CONSULTANT, title="审计标题不应出现")
    ok = FakeWK()
    _enable(monkeypatch, ok)
    await client.post(RETRY, headers=_hdr(USER_ADMIN_ONLY), json={"scope": "all"})
    logs = (await db_session.execute(select(AuditEvent))).scalars().all()
    batch = [lg for lg in logs if lg.action and lg.action.startswith("knowledge.index_batch")]
    assert batch, "应有批量 retry 审计"
    import json as _json

    blob = _json.dumps([lg.extra for lg in batch], ensure_ascii=False)
    for token in [
        "审计标题不应出现",
        "weknora_kb_id",
        "weknora_doc_id",
        "kb-",
        "doc-",
        "storage_ref",
        "source_file_ref",
        "sk-",
    ]:
        assert token not in blob, token
    # extra 含安全 job_id / counts。
    completed = [lg for lg in batch if lg.action == "knowledge.index_batch_retry_completed"]
    assert completed
    assert "job_id" in (completed[0].extra or {})
    assert "success" in (completed[0].extra or {})
