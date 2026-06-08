"""PBC-11F：错误提示与诊断分层测试。

覆盖：用户态文案（详情 / retry-index）；运营态诊断（/admin/ops/indexing）；上游 leaky 错误
不外显；历史脏 index_error_message 按 code 重新派生；WeCom 扫描错误目录化；纯 admin 标题边界。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.main import app
from app.models.audit import AuditEvent
from app.models.knowledge import KnowledgeAssetVersion
from app.services import error_catalog
from app.services.weknora_client import WeKnoraError, get_weknora_client
from app.seed.dev_seed import KA_PERSONAL, USER_ADMIN_ONLY, USER_BOSS, USER_CONSULTANT

KN = "/api/v1/knowledge"
OPS = "/admin/ops/indexing"
UPLOAD = "/api/v1/ingest/upload"
_LEAK_SECRET = "sk-secret-xyz mid-chat wk-kb-company wk-doc-1 https://host/v1 api_key base_url storage_ref source_file_ref"
# 任何响应/审计都不得出现的真实敏感值（注意：配置项名如 WEKNORA_EMBEDDING_MODEL_ID 是允许的）。
_FORBIDDEN = ["sk-", "mid-chat", "wk-kb", "wk-doc", "https://host", "storage_ref", "source_file_ref", "download_url"]


def _hdr(u):
    return {"X-Dev-User-Id": str(u)}


async def _set_index_failed(db_session, asset_id, *, code, dirty_message):
    """把某资产 active 版本置 index_failed + 指定 code + 模拟历史脏文案（含 secret）。"""
    ver = (await db_session.execute(
        select(KnowledgeAssetVersion)
        .where(KnowledgeAssetVersion.asset_id == asset_id)
        .where(KnowledgeAssetVersion.version_status == "active")
    )).scalar_one()
    ver.index_status = "index_failed"
    ver.index_error_code = code
    ver.index_error_message = dirty_message  # 脏：含 secret / 上游 message
    await db_session.commit()
    return ver.id


# ---------------------------------------------------------------------------
# 1. 中央目录单元
# ---------------------------------------------------------------------------
def test_catalog_known_and_unknown():
    for code in ("weknora_not_configured", "weknora_embedding_model_missing", "source_file_unreadable",
                 "weknora_call_failed", "wecom_scan_failed"):
        info = error_catalog.get_error(code)
        assert info.user_message and info.operator_message and info.remediation_hint
        assert info.severity in ("info", "warning", "error", "critical")
    # 别名归类。
    assert error_catalog.get_error("weknora_down").user_message == error_catalog.get_error("weknora_call_failed").user_message
    assert error_catalog.get_error("http_500").operator_message == error_catalog.get_error("weknora_call_failed").operator_message
    assert error_catalog.get_error("wecom_token_expired").operator_message == error_catalog.get_error("wecom_scan_failed").operator_message
    # 未知降级。
    unk = error_catalog.get_error("some_totally_unknown_code")
    assert unk.user_message == error_catalog.get_error("unknown").user_message


def test_safe_code_allowlist_and_alias():
    # PBC-11F residual：safe_code 是 allowlist/alias，而非正则放行。
    assert error_catalog.safe_code("weknora_embedding_model_missing") == "weknora_embedding_model_missing"
    assert error_catalog.safe_code("weknora_down") == "weknora_call_failed"
    assert error_catalog.safe_code("weknora_upload_failed") == "weknora_call_failed"
    assert error_catalog.safe_code("http_500") == "weknora_call_failed"
    assert error_catalog.safe_code("wecom_token_expired") == "wecom_scan_failed"
    assert error_catalog.safe_code("some_totally_unknown_code") == "unknown"
    # 长得像普通标识符但含敏感语义的 code 也不放行（落到 weknora 分类或 unknown，绝不原样）。
    leaky = "mid_chat_sk_secret_wk_kb_company"
    assert error_catalog.safe_code(leaky) == "unknown"
    assert error_catalog.safe_code(leaky) != leaky


# ---------------------------------------------------------------------------
# 2. 用户态：详情 index_error_message 按 code 重新派生（历史脏文案不外显）
# ---------------------------------------------------------------------------
async def test_detail_user_message_rederived_no_dirty(client, db_session):
    await _set_index_failed(db_session, KA_PERSONAL, code="source_file_unreadable", dirty_message=_LEAK_SECRET)
    r = await client.get(f"{KN}/{KA_PERSONAL}", headers=_hdr(USER_CONSULTANT))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["index_status"] == "index_failed"
    assert body["index_error_message"] == error_catalog.user_message("source_file_unreadable")
    # 历史脏文案 / secret 不外显；用户态不含配置项名。
    for token in _FORBIDDEN + ["WEKNORA_EMBEDDING_MODEL_ID", "WEKNORA_BASE_URL"]:
        assert token not in r.text


async def test_detail_unknown_code_user_message(client, db_session):
    await _set_index_failed(db_session, KA_PERSONAL, code="weird_internal_thing", dirty_message="raw upstream sk-leak")
    r = await client.get(f"{KN}/{KA_PERSONAL}", headers=_hdr(USER_CONSULTANT))
    assert r.json()["index_error_message"] == error_catalog.user_message("unknown")
    assert "sk-" not in r.text


# ---------------------------------------------------------------------------
# 3. 运营态：/admin/ops/indexing 三层诊断 + 标题边界
# ---------------------------------------------------------------------------
async def test_ops_operator_diagnostics_and_boundary(client, db_session):
    await _set_index_failed(db_session, KA_PERSONAL, code="weknora_embedding_model_missing", dirty_message=_LEAK_SECRET)
    # 治理角色：可见真实标题 + 运营诊断。
    gov = await client.get(OPS, headers=_hdr(USER_BOSS))
    assert gov.status_code == 200
    item = next(i for i in gov.json()["recent_failed"] if i["asset_id"] == str(KA_PERSONAL))
    assert item["index_error_message"] == error_catalog.user_message("weknora_embedding_model_missing")
    assert item["operator_error_message"] == error_catalog.get_error("weknora_embedding_model_missing").operator_message
    assert item["remediation_hint"]
    assert item["severity"] == "error"
    # 运营态允许配置项名，但不含值 / 内部 id / secret。
    assert "WEKNORA_EMBEDDING_MODEL_ID" in gov.text  # 配置项名（允许）
    for token in _FORBIDDEN:
        assert token not in gov.text
    # 纯 admin：标题隐藏（PBC-11C 边界不破坏）。
    adm = await client.get(OPS, headers=_hdr(USER_ADMIN_ONLY))
    assert adm.json()["title_visible"] is False
    aitem = next(i for i in adm.json()["recent_failed"] if i["asset_id"] == str(KA_PERSONAL))
    assert aitem["title"] == "（业务资产标题已隐藏）"
    assert aitem["operator_error_message"]  # 纯 admin 仍可看运营诊断
    for token in _FORBIDDEN:
        assert token not in adm.text


# ---------------------------------------------------------------------------
# 4. 上游 leaky 错误：用户态 + 运营态 + 审计都不泄露
# ---------------------------------------------------------------------------
class _LeakyWK:
    async def create_kb(self, *, name, embedding_model_id, trace_id=None, **_):
        return "kb-leak-1"

    async def initialize_kb(self, kb_id, **_):
        return None

    async def get_initialization_config(self, kb_id, *, trace_id=None):
        return {}

    async def upload_file(self, **_):
        raise WeKnoraError("weknora_down", f"UPSTREAM {_LEAK_SECRET}")

    async def get_knowledge(self, *_a, **_k):
        return {}

    async def delete_knowledge(self, *_a, **_k):
        return None

    async def search(self, **_):
        return []

    async def hybrid_search(self, **_):
        return []


def _enable_leaky(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr("app.services.ingest.weknora_enabled", lambda: True)
    monkeypatch.setattr("app.services.knowledge.weknora_enabled", lambda: True)
    monkeypatch.setattr(get_settings(), "weknora_embedding_model_id", "test-embed")
    app.dependency_overrides[get_weknora_client] = lambda: _LeakyWK()


async def test_upstream_leaky_error_not_exposed_anywhere(client, db_session, monkeypatch):
    _enable_leaky(monkeypatch)
    try:
        up = (await client.post(UPLOAD, headers=_hdr(USER_CONSULTANT),
                                files={"file": ("d.txt", b"content body for leak test", "text/plain")})).json()
        task_id = up["ingest_task_id"]
        r = await client.post(
            f"/api/v1/ingest/{task_id}/confirm", headers=_hdr(USER_CONSULTANT),
            json={"title": "leak", "summary": "s", "tags": [], "target_scope": "personal",
                  "asset_type": "methodology", "confidentiality_level": "L2", "ai_access_level": "A2"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["index_status"] == "index_failed"
        # 用户态：响应是目录文案，不含上游 message。
        assert body["index_status"] == "index_failed"
        for token in _FORBIDDEN + ["UPSTREAM"]:
            assert token not in r.text
        asset_id = body["result_asset_id"]
        # 详情用户态。
        d = await client.get(f"{KN}/{asset_id}", headers=_hdr(USER_CONSULTANT))
        assert d.json()["index_error_message"] == error_catalog.user_message("weknora_down")
        for token in _FORBIDDEN + ["UPSTREAM"]:
            assert token not in d.text
        # ops 运营态。
        ops = await client.get(OPS, headers=_hdr(USER_BOSS))
        for token in _FORBIDDEN + ["UPSTREAM"]:
            assert token not in ops.text
        # 审计：不写上游 message。
        ev = (await db_session.execute(
            select(AuditEvent).where(AuditEvent.action == "ingest.index_failed")
        )).scalars().all()
        blob = str([e.extra for e in ev])
        for token in _FORBIDDEN + ["UPSTREAM"]:
            assert token not in blob
        # extra 仍含安全 error_code。
        assert any((e.extra or {}).get("error_code") == "weknora_call_failed" for e in ev)
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


# ---------------------------------------------------------------------------
# 5. WeCom 扫描错误目录化（安全运营态文案）
# ---------------------------------------------------------------------------
def test_wecom_scan_error_catalog_safe():
    info = error_catalog.get_error("wecom_scan_failed")
    assert "企业微信" in info.user_message or "可稍后重试" in info.user_message
    # 运营态不含 token/cookie/download_url/file id/space id 值。
    for token in ["token", "cookie", "download_url", "fileid", "spaceid:", "http"]:
        assert token not in info.operator_message and token not in info.remediation_hint
    # owner 失效等具体 wecom 码归类到 wecom_scan_failed。
    assert error_catalog.get_error("wecom_scan_owner_invalid").operator_message == info.operator_message


# ---------------------------------------------------------------------------
# 6. 上游 leaky **code**（非 message）也不外显（PBC-11F residual）
# ---------------------------------------------------------------------------
_LEAKY_CODE = "sk-secret-mid-chat-wk-kb-company-http://host-api_key-base_url"


class _LeakyCodeWK(_LeakyWK):
    async def upload_file(self, **_):
        raise WeKnoraError(_LEAKY_CODE, "safe message")


async def test_upstream_leaky_code_not_exposed(client, db_session, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr("app.services.ingest.weknora_enabled", lambda: True)
    monkeypatch.setattr("app.services.knowledge.weknora_enabled", lambda: True)
    monkeypatch.setattr(get_settings(), "weknora_embedding_model_id", "test-embed")
    app.dependency_overrides[get_weknora_client] = lambda: _LeakyCodeWK()
    try:
        up = (await client.post(UPLOAD, headers=_hdr(USER_CONSULTANT),
                                files={"file": ("d.txt", b"leaky code body", "text/plain")})).json()
        r = await client.post(
            f"/api/v1/ingest/{up['ingest_task_id']}/confirm", headers=_hdr(USER_CONSULTANT),
            json={"title": "lc", "summary": "s", "tags": [], "target_scope": "personal",
                  "asset_type": "methodology", "confidentiality_level": "L2", "ai_access_level": "A2"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["index_status"] == "index_failed"
        asset_id = body["result_asset_id"]
        for token in _FORBIDDEN:
            assert token not in r.text
        # DB 写的是安全目录 code，不是原始 leaky code。
        ver = (await db_session.execute(
            select(KnowledgeAssetVersion)
            .where(KnowledgeAssetVersion.asset_id == uuid.UUID(asset_id))
            .where(KnowledgeAssetVersion.version_status == "active")
        )).scalar_one()
        assert ver.index_error_code == "unknown"
        assert _LEAKY_CODE not in (ver.index_error_code or "")
        # 详情 / ops / 审计均不含 leaky code。
        d = await client.get(f"{KN}/{asset_id}", headers=_hdr(USER_CONSULTANT))
        assert d.json()["index_error_code"] == "unknown"
        for token in _FORBIDDEN:
            assert token not in d.text
        ops = await client.get(OPS, headers=_hdr(USER_BOSS))
        oitem = next(i for i in ops.json()["recent_failed"] if i["asset_id"] == asset_id)
        assert oitem["index_error_code"] == "unknown"
        for token in _FORBIDDEN:
            assert token not in ops.text
        ev = (await db_session.execute(
            select(AuditEvent).where(AuditEvent.action == "ingest.index_failed")
        )).scalars().all()
        blob = str([e.extra for e in ev])
        for token in _FORBIDDEN:
            assert token not in blob
        assert any((e.extra or {}).get("error_code") == "unknown" for e in ev)
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_historical_dirty_code_not_exposed(client, db_session):
    # 直接把 DB active 版本写成脏 code + 脏 message（模拟历史数据）。
    await _set_index_failed(
        db_session, KA_PERSONAL,
        code="mid-chat-sk-secret-wk-kb-company", dirty_message="dirty upstream " + _LEAK_SECRET,
    )
    d = await client.get(f"{KN}/{KA_PERSONAL}", headers=_hdr(USER_CONSULTANT))
    assert d.json()["index_error_code"] == "unknown"
    assert d.json()["index_error_message"] == error_catalog.user_message("unknown")
    for token in _FORBIDDEN + ["mid-chat"]:
        assert token not in d.text
    ops = await client.get(OPS, headers=_hdr(USER_BOSS))
    item = next(i for i in ops.json()["recent_failed"] if i["asset_id"] == str(KA_PERSONAL))
    assert item["index_error_code"] == "unknown"
    assert item["operator_error_message"] == error_catalog.get_error("unknown").operator_message
    assert item["remediation_hint"] == error_catalog.get_error("unknown").remediation_hint
    for token in _FORBIDDEN + ["mid-chat"]:
        assert token not in ops.text
