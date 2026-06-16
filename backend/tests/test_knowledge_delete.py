"""知识资产受控删除测试。

软删除（asset_status=deleted），权限（个人 owner / 项目 PM / 公司治理），
删除后退出 列表/详情/搜索/预览/原文授权运行时，撤销 grants、取消 pending requests，
WeKnora 失败仍 fail-closed，审计无泄露。

（项目知识库创建测试见 test_project_create.py。）
"""

from __future__ import annotations

import uuid

import httpx
from sqlalchemy import select

from app.main import app
from app.models.audit import AuditEvent
from app.models.identity import ProjectMember
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.original_access import AccessGrant, OriginalAccessRequest
from app.seed.dev_seed import (
    KA_COMPANY_L2,
    KA_PERSONAL,
    KA_PROJECT_ALPHA,
    PROJECT_ALPHA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
    USER_PROJECT_MANAGER,
)
from app.services.llm_client import get_llm_client
from app.services.weknora_client import get_weknora_client

KN = "/api/v1/knowledge"
SEARCH = "/api/v1/knowledge/search"
_COMPANY_KB = "wk-kb-company"

# 注：审计 extra 含安全布尔键 weknora_delete_attempted/succeeded（任务明确允许），
# 故不把裸 "weknora" 入列；真实泄露关注 WeKnora 内部 id（wk-kb / wk-doc / kb_id / doc_id）。
_LEAK = [
    "storage_ref",
    "source_file_ref",
    "internal://",
    "wk-kb",
    "wk-doc",
    "kb_id",
    "doc_id",
    "chunk_id",
    "access_token",
    "download_url",
    "cookie",
    "ww_consultant",
    "sk-",
    "Bearer",
]


def _hdr(uid, trace=None):
    h = {"X-Dev-User-Id": str(uid)}
    if trace:
        h["X-Trace-Id"] = trace
    return h


def _assert_no_leak(text):
    for t in _LEAK:
        assert t not in text, f"不应泄露 {t}"


def _del(aid):
    return f"{KN}/{aid}/delete"


# ---- 搜索 fake（验证删除后召回排除） ----
class _FakeSearchWeKnora:
    def __init__(self, docs):
        self.docs = docs

    async def search(self, *, query, kb_ids, knowledge_ids=None, top_k=20, trace_id=None):
        out = []
        for i, d in enumerate(self.docs):
            if d["kb_id"] not in kb_ids:
                continue
            out.append(
                {
                    "content": d["content"],
                    "knowledge_id": d["knowledge_id"],
                    "chunk_index": 0,
                    "score": round(1.0 - i * 0.01, 4),
                    "seq": 0,
                }
            )
        return out

    async def hybrid_search(self, **_):
        return []


class _NoLLM:
    provider = ""
    model = ""

    async def chat_completion(self, *_, **__):
        from app.services.llm_client import LLMError

        raise LLMError("llm_not_configured", "未配置")


# ================= 删除：权限矩阵 =================
async def test_owner_deletes_personal(client):
    r = await client.post(
        _del(KA_PERSONAL), headers=_hdr(USER_CONSULTANT), json={"reason": "上传错误"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["asset_status"] == "deleted"
    assert body["deleted_at"]
    _assert_no_leak(r.text)


async def test_non_owner_cannot_see_personal_404(client):
    # 经理 B 看不到顾问 A 的个人知识 → 404（不泄露存在性）。
    r = await client.post(_del(KA_PERSONAL), headers=_hdr(USER_PROJECT_MANAGER), json={})
    assert r.status_code == 404
    assert r.json()["detail"]["denied_reason"] == "knowledge_asset_not_found"


async def test_project_manager_deletes_project(client):
    r = await client.post(
        _del(KA_PROJECT_ALPHA), headers=_hdr(USER_PROJECT_MANAGER), json={"reason": "重复"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["asset_status"] == "deleted"


async def test_consultant_cannot_delete_project_403(client):
    # 顾问是 Alpha active 成员（可发现）但非 PM → 403 forbidden。
    r = await client.post(_del(KA_PROJECT_ALPHA), headers=_hdr(USER_CONSULTANT), json={})
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "knowledge_delete_forbidden"


async def test_coach_cannot_delete_project_403(client, db_session):
    # 把咨询总监设为 Alpha 的 active coach（非 PM）；coach 不可删除项目知识。
    db_session.add(
        ProjectMember(
            user_id=USER_DIRECTOR, project_id=PROJECT_ALPHA, project_role="coach", status="active"
        )
    )
    await db_session.commit()
    r = await client.post(_del(KA_PROJECT_ALPHA), headers=_hdr(USER_DIRECTOR), json={})
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "knowledge_delete_forbidden"


async def test_governance_deletes_company(client):
    r = await client.post(_del(KA_COMPANY_L2), headers=_hdr(USER_BOSS), json={"reason": "撤下"})
    assert r.status_code == 200, r.text
    assert r.json()["asset_status"] == "deleted"


async def test_pure_admin_cannot_delete(client, db_session):
    r = await client.post(_del(KA_COMPANY_L2), headers=_hdr(USER_ADMIN_ONLY), json={})
    assert r.status_code in (403, 404)
    if r.status_code == 403:
        assert r.json()["detail"]["denied_reason"] == "admin_business_permission_denied"
    # 资产仍未被删除。
    asset = await db_session.get(KnowledgeAsset, KA_COMPANY_L2)
    assert asset.asset_status == "active"


async def test_double_delete_404(client):
    assert (
        await client.post(_del(KA_PERSONAL), headers=_hdr(USER_CONSULTANT), json={})
    ).status_code == 200
    r2 = await client.post(_del(KA_PERSONAL), headers=_hdr(USER_CONSULTANT), json={})
    assert r2.status_code == 404


# ================= 删除：退出各运行时面 =================
async def test_deleted_exits_list_detail_mykn(client):
    await client.post(_del(KA_PERSONAL), headers=_hdr(USER_CONSULTANT), json={})
    # 列表（含 include_archived）不返回。
    for q in ["", "?include_archived=true"]:
        items = (await client.get(f"{KN}{q}", headers=_hdr(USER_CONSULTANT))).json()["items"]
        assert all(i["id"] != str(KA_PERSONAL) for i in items)
    # 个人知识不返回。
    my = (await client.get("/api/v1/my/knowledge", headers=_hdr(USER_CONSULTANT))).json()["items"]
    assert all(i["id"] != str(KA_PERSONAL) for i in my)
    # 详情 404。
    assert (
        await client.get(f"{KN}/{KA_PERSONAL}", headers=_hdr(USER_CONSULTANT))
    ).status_code == 404


async def test_deleted_exits_search(client):
    # 删除前可被检索；删除后即使 fake 仍返回 doc，也因 asset 非 active 被排除。
    app.dependency_overrides[get_weknora_client] = lambda: _FakeSearchWeKnora(
        [
            {
                "knowledge_id": f"wk-doc-{KA_COMPANY_L2}",
                "kb_id": _COMPANY_KB,
                "content": "零售数字化成熟度评估内容",
            }
        ]
    )
    app.dependency_overrides[get_llm_client] = lambda: _NoLLM()
    try:
        before = await client.post(
            SEARCH, headers=_hdr(USER_CONSULTANT), json={"query": "成熟度", "scope": "company"}
        )
        assert str(KA_COMPANY_L2) in {c["asset_id"] for c in before.json()["cards"]}
        await client.post(_del(KA_COMPANY_L2), headers=_hdr(USER_BOSS), json={})
        after = await client.post(
            SEARCH, headers=_hdr(USER_CONSULTANT), json={"query": "成熟度", "scope": "company"}
        )
        assert str(KA_COMPANY_L2) not in {c["asset_id"] for c in after.json()["cards"]}
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)
        app.dependency_overrides.pop(get_llm_client, None)


async def test_deleted_blocks_preview(client):
    # 删除前 consultant 可对公司 L2 申请预览；删除后预览失败。
    assert (
        await client.post(f"{KN}/{KA_COMPANY_L2}/preview", headers=_hdr(USER_CONSULTANT))
    ).status_code == 200
    await client.post(_del(KA_COMPANY_L2), headers=_hdr(USER_BOSS), json={})
    assert (
        await client.post(f"{KN}/{KA_COMPANY_L2}/preview", headers=_hdr(USER_CONSULTANT))
    ).status_code in (403, 404)


async def test_delete_revokes_grants_and_cancels_requests(client, db_session):
    # 预置 active grant + pending request，删除后均失效。
    db_session.add(
        AccessGrant(
            asset_id=KA_COMPANY_L2,
            grantee_user_id=USER_CONSULTANT,
            granted_by_user_id=USER_BOSS,
            grant_type="original_access",
            status="active",
        )
    )
    db_session.add(
        OriginalAccessRequest(
            asset_id=KA_COMPANY_L2,
            requester_user_id=USER_PROJECT_MANAGER,
            status="pending",
        )
    )
    await db_session.commit()
    r = await client.post(_del(KA_COMPANY_L2), headers=_hdr(USER_DIRECTOR), json={})
    assert r.status_code == 200
    grant = (
        (await db_session.execute(select(AccessGrant).where(AccessGrant.asset_id == KA_COMPANY_L2)))
        .scalars()
        .first()
    )
    assert grant.status == "revoked" and grant.revoke_reason == "asset_deleted"
    req = (
        (
            await db_session.execute(
                select(OriginalAccessRequest).where(OriginalAccessRequest.asset_id == KA_COMPANY_L2)
            )
        )
        .scalars()
        .first()
    )
    assert req.status == "cancelled"


async def test_delete_audit_no_leak(client, db_session):
    await client.post(
        _del(KA_COMPANY_L2),
        headers={**_hdr(USER_BOSS), "X-Trace-Id": "trc-del"},
        json={"reason": "误上传"},
    )
    evt = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "knowledge.asset_deleted")
            )
        )
        .scalars()
        .first()
    )
    assert evt is not None
    assert evt.actor_user_id == USER_BOSS
    assert evt.after_snapshot["asset_status"] == "deleted"
    blob = f"{evt.before_snapshot}{evt.after_snapshot}{evt.extra}"
    _assert_no_leak(blob)
    # 软删除：资产行仍在（审计不断链），仅状态变化。
    asset = await db_session.get(KnowledgeAsset, KA_COMPANY_L2)
    assert asset is not None and asset.asset_status == "deleted" and asset.deleted_by == USER_BOSS


class _BoomWeKnora:
    """delete_knowledge 抛真实 httpx 网络异常（非 OSError / 非 WeKnoraError）。"""

    async def delete_knowledge(self, knowledge_id, *, trace_id=None):
        raise httpx.ConnectError("boom")


async def test_weknora_delete_network_failure_still_soft_deletes(client, db_session, monkeypatch):
    """WeKnora 删除遇网络/超时异常时，平台软删除仍必须成功（fail-closed）。"""
    # 造一个带 active weknora_doc_id 的个人资产（owner=顾问 A）。
    aid = uuid.uuid4()
    asset = KnowledgeAsset(
        id=aid,
        title="待删除带索引资产",
        scope="personal",
        zone="asset",
        asset_type="methodology",
        owner_user_id=USER_CONSULTANT,
        maintainer_user_id=USER_CONSULTANT,
        visibility="project_only",
        confidentiality_level="L2",
        ai_access_level="A1",
        asset_status="active",
    )
    version = KnowledgeAssetVersion(
        asset_id=aid,
        version_no="v1",
        version_status="active",
        created_by=USER_CONSULTANT,
        weknora_kb_id="wk-kb-secret",
        weknora_doc_id="wk-doc-secret",
        weknora_parse_status="completed",
    )
    asset.versions.append(version)
    db_session.add(asset)
    await db_session.commit()

    # 让 knowledge 模块认为 WeKnora 已启用，并注入会抛 httpx 异常的 client。
    monkeypatch.setattr("app.services.knowledge.weknora_enabled", lambda: True)
    app.dependency_overrides[get_weknora_client] = lambda: _BoomWeKnora()
    try:
        r = await client.post(
            _del(aid),
            headers={**_hdr(USER_CONSULTANT), "X-Trace-Id": "trc-wk-fail"},
            json={"reason": "误上传"},
        )
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)

    # 平台软删除仍成功。
    assert r.status_code == 200, r.text
    assert r.json()["asset_status"] == "deleted"
    _assert_no_leak(r.text)
    assert "boom" not in r.text

    # 资产进入 deleted；详情 404。
    db_session.expire_all()  # 丢弃 identity-map 旧值，强制从 DB 读取 API 已提交的状态。
    fresh = await db_session.get(KnowledgeAsset, aid)
    assert (
        fresh.asset_status == "deleted" and fresh.deleted_by == USER_CONSULTANT and fresh.deleted_at
    )
    assert (await client.get(f"{KN}/{aid}", headers=_hdr(USER_CONSULTANT))).status_code == 404

    # 审计：attempted=True、succeeded=False；不含 doc/kb id、URL、异常原文。
    evt = (
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "knowledge.asset_deleted", AuditEvent.target_id == aid
                )
            )
        )
        .scalars()
        .first()
    )
    assert evt is not None
    assert evt.extra["weknora_delete_attempted"] is True
    assert evt.extra["weknora_delete_succeeded"] is False
    blob = f"{evt.before_snapshot}{evt.after_snapshot}{evt.extra}"
    _assert_no_leak(blob)
    assert "boom" not in blob and "wk-doc-secret" not in blob and "wk-kb-secret" not in blob


async def test_can_delete_flag_in_detail(client):
    # owner 详情 can_delete=true；非删除权用户为 false。
    d_owner = await client.get(f"{KN}/{KA_COMPANY_L2}", headers=_hdr(USER_BOSS))
    assert d_owner.json()["access_info"]["can_delete"] is True
    d_other = await client.get(f"{KN}/{KA_COMPANY_L2}", headers=_hdr(USER_CONSULTANT))
    assert d_other.json()["access_info"]["can_delete"] is False
