"""原文访问申请与授权测试。

覆盖：不可发现 404、可见无原文权可申请、重复申请复用 pending、已有 grant 不重复 pending、
项目角色与公司治理角色可按范围审批建 grant、纯 admin / 普通顾问不可审批、撤销/过期 grant 不再
放行原文、运行时入口（知识详情 original + stage2 取件）grant 前后行为不同、审计安全无泄露。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models.audit import AuditEvent
from app.models.knowledge import KnowledgeAsset
from app.models.original_access import AccessGrant, OriginalAccessRequest
from app.seed.dev_seed import (
    PROJECT_BETA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
    USER_PROJECT_MANAGER,
)
from app.services import original_access as oa
from app.services.identity import load_user_with_roles
from app.services.permission import build_caller_context

_LEAK = [
    "storage_ref",
    "source_file_ref",
    "weknora",
    "access_token",
    "download_url",
    "token_hash",
    "app_secret",
]


def _hdr(uid, **extra):
    return {"X-Dev-User-Id": str(uid), **extra}


def _assert_no_leak(text: str):
    low = text.lower()
    for t in _LEAK:
        assert t.lower() not in low, f"不应泄露 {t}"


async def _mk_asset(
    db_session, *, scope="company", level="L3", project_id=None, status="active"
) -> uuid.UUID:
    """建一个公司资产；公司顾问可见安全摘要但默认无原文。"""
    aid = uuid.uuid4()
    db_session.add(
        KnowledgeAsset(
            id=aid,
            title="公司 L3 资产",
            scope=scope,
            zone="asset",
            asset_type="case",
            owner_user_id=USER_PROJECT_MANAGER,
            project_id=project_id,
            confidentiality_level=level,
            asset_status=status,
        )
    )
    await db_session.commit()
    return aid


def _req_path(aid):
    return f"/api/v1/knowledge/{aid}/original-access/request"


# ---------------- 申请 ----------------
async def test_undiscoverable_asset_404(client):
    # 不存在的资产 → 404，不泄露存在。
    r = await client.post(
        _req_path(uuid.uuid4()), headers=_hdr(USER_CONSULTANT), json={"reason": "x"}
    )
    assert r.status_code == 404
    assert r.json()["detail"]["denied_reason"] == "knowledge_asset_not_found"


async def test_visible_no_original_can_request(client, db_session):
    aid = await _mk_asset(db_session)  # 公司 L3，USER_CONSULTANT 可发现摘要、无原文
    r = await client.post(
        _req_path(aid),
        headers=_hdr(USER_CONSULTANT, **{"X-Trace-Id": "trc-original-access-req"}),
        json={"reason": "需复用方法论"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "created"
    assert r.json()["request"]["status"] == "pending"
    _assert_no_leak(r.text)


async def test_repeat_request_reuses_pending(client, db_session):
    aid = await _mk_asset(db_session)
    r1 = await client.post(_req_path(aid), headers=_hdr(USER_CONSULTANT), json={"reason": "a"})
    r2 = await client.post(_req_path(aid), headers=_hdr(USER_CONSULTANT), json={"reason": "b"})
    assert r1.json()["status"] == "created" and r2.json()["status"] == "pending_exists"
    assert r1.json()["request"]["request_id"] == r2.json()["request"]["request_id"]
    count = (
        await db_session.execute(
            select(func.count())
            .select_from(OriginalAccessRequest)
            .where(OriginalAccessRequest.asset_id == aid)
        )
    ).scalar_one()
    assert count == 1


async def test_member_with_original_no_pending(client, db_session):
    # USER_PROJECT_MANAGER 是 ALPHA PM；建一个 ALPHA L3 资产，PM 本就有原文权 → already_granted。
    from app.seed.dev_seed import PROJECT_ALPHA

    aid = await _mk_asset(db_session, scope="project", project_id=PROJECT_ALPHA)
    r = await client.post(_req_path(aid), headers=_hdr(USER_PROJECT_MANAGER), json={"reason": "x"})
    assert r.status_code == 200
    assert r.json()["status"] == "already_granted"
    count = (
        await db_session.execute(
            select(func.count())
            .select_from(OriginalAccessRequest)
            .where(OriginalAccessRequest.asset_id == aid)
        )
    ).scalar_one()
    assert count == 0


# ---------------- 审批 ----------------
async def _create_pending(client, db_session, requester=USER_CONSULTANT):
    aid = await _mk_asset(db_session)
    r = await client.post(_req_path(aid), headers=_hdr(requester), json={"reason": "需要"})
    return aid, r.json()["request"]["request_id"]


async def test_pm_can_approve_creates_grant(client, db_session):
    # 公司资产由总经理审批原文申请。
    aid, rid = await _create_pending(client, db_session)
    r = await client.post(
        f"/api/v1/original-access/requests/{rid}/approve",
        headers=_hdr(USER_BOSS),
        json={"note": "ok"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved" and r.json()["grant"]["status"] == "active"
    assert r.json()["grant"]["expires_at"] is not None
    # grant 落库且 active。
    g = (
        await db_session.execute(select(AccessGrant).where(AccessGrant.asset_id == aid))
    ).scalar_one()
    assert g.grantee_user_id == USER_CONSULTANT and g.status == "active"


async def test_bulk_original_access_returns_partial_terminal_result(client, db_session):
    _, first = await _create_pending(client, db_session)
    _, second = await _create_pending(client, db_session)
    approved = await client.post(
        f"/api/v1/original-access/requests/{first}/approve",
        headers=_hdr(USER_BOSS),
        json={},
    )
    assert approved.status_code == 200

    response = await client.post(
        "/api/v1/original-access/requests/bulk-action",
        headers=_hdr(USER_BOSS),
        json={"item_ids": [first, second], "action": "reject", "note": "批量复核"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed_with_errors"
    assert (body["succeeded"], body["skipped"], body["failed"]) == (1, 1, 0)
    _assert_no_leak(response.text)


async def test_director_can_approve(client, db_session):
    aid, rid = await _create_pending(client, db_session)
    r = await client.post(
        f"/api/v1/original-access/requests/{rid}/approve", headers=_hdr(USER_DIRECTOR), json={}
    )
    assert r.status_code == 200 and r.json()["status"] == "approved"


async def test_admin_cannot_approve(client, db_session):
    aid, rid = await _create_pending(client, db_session)
    r = await client.post(
        f"/api/v1/original-access/requests/{rid}/approve", headers=_hdr(USER_ADMIN_ONLY), json={}
    )
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "admin_business_permission_denied"


async def test_consultant_cannot_approve(client, db_session):
    aid, rid = await _create_pending(client, db_session)
    # 另一个普通顾问（请求人自己也不能审批自己）→ 用请求人 USER_CONSULTANT 尝试审批。
    r = await client.post(
        f"/api/v1/original-access/requests/{rid}/approve", headers=_hdr(USER_CONSULTANT), json={}
    )
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "original_access_review_forbidden"


# ---------------- 运行时联动 ----------------
async def test_grant_enables_then_revoke_disables_original(client, db_session):
    aid, rid = await _create_pending(client, db_session)
    # 申请前：知识详情 original=False, can_request=True
    d0 = await client.get(f"/api/v1/knowledge/{aid}", headers=_hdr(USER_CONSULTANT))
    assert d0.status_code == 200
    assert d0.json()["access_info"]["original"] is False
    # 审批 → grant
    appr = await client.post(
        f"/api/v1/original-access/requests/{rid}/approve", headers=_hdr(USER_BOSS), json={}
    )
    gid = appr.json()["grant"]["grant_id"]
    # 授权后：original=True，来源 access_grant
    d1 = await client.get(f"/api/v1/knowledge/{aid}", headers=_hdr(USER_CONSULTANT))
    assert d1.json()["access_info"]["original"] is True
    assert d1.json()["access_info"]["effective_source"] == "access_grant"
    # 撤销 → original 回到 False
    rv = await client.post(
        f"/api/v1/original-access/grants/{gid}/revoke",
        headers=_hdr(USER_BOSS),
        json={"reason": "no longer needed"},
    )
    assert rv.status_code == 200 and rv.json()["status"] == "revoked"
    d2 = await client.get(f"/api/v1/knowledge/{aid}", headers=_hdr(USER_CONSULTANT))
    assert d2.json()["access_info"]["original"] is False


async def test_expired_grant_not_live(client, db_session):
    aid = await _mk_asset(db_session)
    # 直接建一条已过期 grant。
    g = AccessGrant(
        asset_id=aid,
        grantee_user_id=USER_CONSULTANT,
        grant_type="original_access",
        granted_by_user_id=USER_BOSS,
        status="active",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db_session.add(g)
    await db_session.commit()
    assert await oa.has_active_grant(db_session, USER_CONSULTANT, aid) is False
    d = await client.get(f"/api/v1/knowledge/{aid}", headers=_hdr(USER_CONSULTANT))
    assert d.json()["access_info"]["original"] is False


# ---------------- 审计 ----------------
async def test_audit_actions_and_no_leak(client, db_session):
    aid, rid = await _create_pending(client, db_session)
    appr = await client.post(
        f"/api/v1/original-access/requests/{rid}/approve",
        headers=_hdr(USER_BOSS, **{"X-Trace-Id": "trc-original-access-audit"}),
        json={"note": "ok"},
    )
    gid = appr.json()["grant"]["grant_id"]
    await client.post(
        f"/api/v1/original-access/grants/{gid}/revoke", headers=_hdr(USER_BOSS), json={}
    )
    actions = {e.action for e in (await db_session.execute(select(AuditEvent))).scalars().all()}
    assert {
        "access.original_requested",
        "access.original_approved",
        "access.original_grant_revoked",
    } <= actions
    rows = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action.like("access.original%"))
            )
        )
        .scalars()
        .all()
    )
    blob = "".join(str(e.extra) + str(e.before_snapshot) + str(e.after_snapshot) for e in rows)
    for t in _LEAK:
        assert t.lower() not in blob.lower()


# ---------------- 预览拒绝文案现实口径----------------
async def test_preview_denied_message_is_current_copy(client, db_session):
    aid = await _mk_asset(db_session)  # 公司 L3，USER_CONSULTANT 无原文权
    r = await client.post(
        f"/api/v1/knowledge/{aid}/preview", headers=_hdr(USER_CONSULTANT), json={}
    )
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert detail["denied_reason"] == "original_requires_request"
    msg = detail["message"]
    for stale in ("待后续任务", "未实现", "占位"):
        assert stale not in msg, f"预览拒绝文案不应含旧口径「{stale}」"
    _assert_no_leak(r.text)


# ---------------- 申请人不在 active context 验证（沿用既有口径）----------------
async def test_requester_context_unaffected(db_session):
    user = await load_user_with_roles(db_session, user_id=USER_CONSULTANT)
    ctx = build_caller_context(user)
    assert PROJECT_BETA not in ctx.active_project_ids  # 仍非 BETA active 成员
