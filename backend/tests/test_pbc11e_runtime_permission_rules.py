"""PBC-11E：运行时权限规则化测试。

覆盖：load_access_policy 缺失/禁用/非法 fail-closed；toggle 关闭后跨项目/公司 L1/L2 原文运行时
被拒（API access_info.can_view_original 随之变化），但 active access_grant 仍放大；超时自动审批
（仅 L1/L2、机密除外、各跳过条件、不重复 grant、安全审计）；Celery task 包装可调用 service。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.audit import AuditEvent
from app.models.knowledge import KnowledgeAsset
from app.models.original_access import AccessGrant, OriginalAccessRequest
from app.models.permission_rule import PermissionRule
from app.schemas.permission import AccessLayer
from app.services import original_access
from app.services.permission import build_caller_context, decide
from app.services.permission_rules import (
    access_request_timeout_hours,
    ensure_default_rules,
    load_access_policy,
)
from app.models.identity import User
from app.seed.dev_seed import (
    KA_COMPANY_L2,
    KA_PROJECT_ALPHA,
    KA_PROJECT_ALPHA_L5,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
)

KN = "/api/v1/knowledge"
CROSS = "cross_project_l1_l2_original_for_business_user"
COMPANY = "company_l1_l2_original_for_business_user"
TIMEOUT = "access_request_timeout_hours"
GRANT_DAYS = "access_grant_duration_days"


def _hdr(u):
    return {"X-Dev-User-Id": str(u)}


def _now():
    return datetime.now(timezone.utc)


async def _rule(db_session, key) -> PermissionRule:
    await ensure_default_rules(db_session)
    return (await db_session.execute(select(PermissionRule).where(PermissionRule.rule_key == key))).scalar_one()


async def _set_toggle(db_session, key, *, value_bool=None, enabled=None):
    r = await _rule(db_session, key)
    if value_bool is not None:
        r.value_bool = value_bool
    if enabled is not None:
        r.enabled = enabled
    await db_session.commit()


async def _set_numeric(db_session, key, *, value_number=None, enabled=None):
    r = await _rule(db_session, key)
    if value_number is not None:
        r.value_number = value_number
    if enabled is not None:
        r.enabled = enabled
    await db_session.commit()


# ---------------------------------------------------------------------------
# load_access_policy 单元（缺失/默认/禁用/非法）
# ---------------------------------------------------------------------------
async def test_policy_missing_uses_factory_default(db_session):
    # 未 seed → 缺失 → 回退出厂默认（True）。
    p = await load_access_policy(db_session)
    assert p.cross_project_l1_l2_original_for_business_user is True
    assert p.company_l1_l2_original_for_business_user is True


async def test_policy_disabled_fail_closed(db_session):
    await _set_toggle(db_session, CROSS, enabled=False)  # 禁用 → False（不回到 True）
    p = await load_access_policy(db_session)
    assert p.cross_project_l1_l2_original_for_business_user is False
    assert p.company_l1_l2_original_for_business_user is True  # 另一项未动


async def test_policy_value_false(db_session):
    await _set_toggle(db_session, COMPANY, value_bool=False)
    p = await load_access_policy(db_session)
    assert p.company_l1_l2_original_for_business_user is False


async def test_policy_invalid_value_fail_closed(db_session):
    # toggle value_bool 置空（非法）→ fail-closed False。
    r = await _rule(db_session, CROSS)
    r.value_bool = None
    await db_session.commit()
    p = await load_access_policy(db_session)
    assert p.cross_project_l1_l2_original_for_business_user is False


# ---------------------------------------------------------------------------
# decide() 运行时接入（纯函数 + policy）
# ---------------------------------------------------------------------------
async def _asset(db_session, asset_id):
    return (await db_session.execute(select(KnowledgeAsset).where(KnowledgeAsset.id == asset_id))).scalar_one()


async def _ctx(db_session, user_id):
    from sqlalchemy.orm import selectinload

    u = (await db_session.execute(
        select(User).where(User.id == user_id).options(
            selectinload(User.company_roles), selectinload(User.project_members))
    )).scalar_one()
    return build_caller_context(u)


async def test_cross_project_toggle_off_denies_original_grant_still_works(db_session, client):
    asset = await _asset(db_session, KA_PROJECT_ALPHA)  # 项目 Alpha L2
    boss = await _ctx(db_session, USER_BOSS)            # 非 Alpha 成员业务用户
    # 默认（ON）：跨项目 L1/L2 原文放行。
    p_on = await load_access_policy(db_session)
    assert decide(boss, asset, AccessLayer.original, policy=p_on).allowed is True
    # 关闭 → 原文被拒，但 summary/discovery 仍可。
    await _set_toggle(db_session, CROSS, value_bool=False)
    p_off = await load_access_policy(db_session)
    assert decide(boss, asset, AccessLayer.original, policy=p_off).allowed is False
    assert decide(boss, asset, AccessLayer.summary, policy=p_off).allowed is True
    assert decide(boss, asset, AccessLayer.discovery, policy=p_off).allowed is True
    # active grant 仍放大到 original。
    assert decide(boss, asset, AccessLayer.original, has_original_grant=True, policy=p_off).allowed is True


async def test_company_toggle_off_denies_original(db_session):
    asset = await _asset(db_session, KA_COMPANY_L2)  # 公司 L2
    ctx = await _ctx(db_session, USER_CONSULTANT)
    await _set_toggle(db_session, COMPANY, value_bool=False)
    p = await load_access_policy(db_session)
    assert decide(ctx, asset, AccessLayer.original, policy=p).allowed is False
    assert decide(ctx, asset, AccessLayer.summary, policy=p).allowed is True
    assert decide(ctx, asset, AccessLayer.original, has_original_grant=True, policy=p).allowed is True


# ---------------------------------------------------------------------------
# API 集成：knowledge 详情 can_view_original 随规则变化
# ---------------------------------------------------------------------------
async def test_detail_can_view_original_follows_rule(client, db_session):
    # 默认 ON：公司 L2 业务用户可见原文。
    d_on = await client.get(f"{KN}/{KA_COMPANY_L2}", headers=_hdr(USER_CONSULTANT))
    assert d_on.json()["access_info"]["original"] is True
    # 关闭 company 开关 → 原文层 False，摘要仍 True。
    await _set_toggle(db_session, COMPANY, value_bool=False)
    d_off = await client.get(f"{KN}/{KA_COMPANY_L2}", headers=_hdr(USER_CONSULTANT))
    assert d_off.json()["access_info"]["original"] is False
    assert d_off.json()["access_info"]["summary"] is True


async def test_admin_still_cannot_discover_business_knowledge(client, db_session):
    await _set_toggle(db_session, COMPANY, value_bool=False)  # 规则变化不影响 admin 边界
    r = await client.get(f"{KN}/{KA_COMPANY_L2}", headers=_hdr(USER_ADMIN_ONLY))
    assert r.status_code == 404  # 纯 admin 不发现业务知识


# ---------------------------------------------------------------------------
# 超时自动审批
# ---------------------------------------------------------------------------
async def _make_pending(db_session, asset_id, requester, *, age_hours: float):
    req = OriginalAccessRequest(
        asset_id=asset_id, requester_user_id=requester,
        requested_access_layer="original", status="pending",
        created_at=_now() - timedelta(hours=age_hours),
    )
    db_session.add(req)
    await db_session.commit()
    return req


async def test_auto_approve_l1_l2_timed_out(db_session):
    await _set_toggle(db_session, COMPANY, value_bool=False)  # 让 pending 合理（否则已有原文权）
    await _set_numeric(db_session, TIMEOUT, value_number=1, enabled=True)
    req = await _make_pending(db_session, KA_COMPANY_L2, USER_CONSULTANT, age_hours=2)
    stats = await original_access.auto_approve_timed_out_original_access_requests(db_session, trace_id="t-auto")
    assert stats["enabled"] is True
    assert stats["approved"] == 1
    await db_session.refresh(req)
    assert req.status == "approved"
    assert req.reviewer_user_id is None  # 系统自动审批
    grant = (await db_session.execute(
        select(AccessGrant).where(AccessGrant.asset_id == KA_COMPANY_L2, AccessGrant.grantee_user_id == USER_CONSULTANT)
    )).scalars().first()
    assert grant is not None and grant.status == "active" and grant.expires_at is not None


async def test_auto_approve_not_timed_out_skipped(db_session):
    await _set_toggle(db_session, COMPANY, value_bool=False)
    await _set_numeric(db_session, TIMEOUT, value_number=24, enabled=True)
    await _make_pending(db_session, KA_COMPANY_L2, USER_CONSULTANT, age_hours=1)
    stats = await original_access.auto_approve_timed_out_original_access_requests(db_session, trace_id="t")
    assert stats["checked"] == 0 and stats["approved"] == 0


async def test_auto_approve_skips_confidential(db_session):
    await _set_numeric(db_session, TIMEOUT, value_number=1, enabled=True)
    await _make_pending(db_session, KA_PROJECT_ALPHA_L5, USER_CONSULTANT, age_hours=5)  # L5
    stats = await original_access.auto_approve_timed_out_original_access_requests(db_session, trace_id="t")
    assert stats["skipped_confidential"] == 1 and stats["approved"] == 0


async def test_auto_approve_disabled_rule_no_action(db_session):
    await _set_numeric(db_session, TIMEOUT, enabled=False)
    await _make_pending(db_session, KA_COMPANY_L2, USER_CONSULTANT, age_hours=5)
    stats = await original_access.auto_approve_timed_out_original_access_requests(db_session, trace_id="t")
    assert stats["enabled"] is False and stats["approved"] == 0


async def test_auto_approve_invalid_timeout_no_action(db_session):
    await _set_numeric(db_session, TIMEOUT, value_number=0, enabled=True)  # <=0 → 不启用
    assert await access_request_timeout_hours(db_session) is None
    await _make_pending(db_session, KA_COMPANY_L2, USER_CONSULTANT, age_hours=5)
    stats = await original_access.auto_approve_timed_out_original_access_requests(db_session, trace_id="t")
    assert stats["enabled"] is False


async def test_auto_approve_inactive_requester_skipped(db_session):
    await _set_toggle(db_session, COMPANY, value_bool=False)
    await _set_numeric(db_session, TIMEOUT, value_number=1, enabled=True)
    await _make_pending(db_session, KA_COMPANY_L2, USER_CONSULTANT, age_hours=5)
    # 申请人停用。
    u = (await db_session.execute(select(User).where(User.id == USER_CONSULTANT))).scalar_one()
    u.status = "inactive"
    await db_session.commit()
    stats = await original_access.auto_approve_timed_out_original_access_requests(db_session, trace_id="t")
    assert stats["skipped_invalid"] == 1 and stats["approved"] == 0


async def test_auto_approve_no_duplicate_grant_finalizes_request(db_session):
    await _set_toggle(db_session, COMPANY, value_bool=False)
    await _set_numeric(db_session, TIMEOUT, value_number=1, enabled=True)
    req = await _make_pending(db_session, KA_COMPANY_L2, USER_CONSULTANT, age_hours=5)
    # 预置一个 live grant。
    db_session.add(AccessGrant(
        asset_id=KA_COMPANY_L2, grantee_user_id=USER_CONSULTANT, grant_type="original_access",
        granted_by_user_id=USER_CONSULTANT, status="active", expires_at=_now() + timedelta(days=3),
    ))
    await db_session.commit()
    stats = await original_access.auto_approve_timed_out_original_access_requests(db_session, trace_id="t")
    assert stats["approved"] == 1
    await db_session.refresh(req)
    assert req.status == "approved"
    grants = (await db_session.execute(
        select(AccessGrant).where(AccessGrant.asset_id == KA_COMPANY_L2,
                                  AccessGrant.grantee_user_id == USER_CONSULTANT,
                                  AccessGrant.status == "active")
    )).scalars().all()
    assert len(grants) == 1  # 不重复建


async def test_auto_approve_renews_expired_active_grant(db_session):
    # 残留修复：已有 status=active 但已过期的 grant 不应阻塞新授权。
    await _set_toggle(db_session, COMPANY, value_bool=False)
    await _set_numeric(db_session, TIMEOUT, value_number=1, enabled=True)
    req = await _make_pending(db_session, KA_COMPANY_L2, USER_CONSULTANT, age_hours=5)
    old = AccessGrant(
        asset_id=KA_COMPANY_L2, grantee_user_id=USER_CONSULTANT, grant_type="original_access",
        granted_by_user_id=USER_CONSULTANT, status="active", expires_at=_now() - timedelta(days=1),
    )
    db_session.add(old)
    await db_session.commit()
    old_id = old.id

    stats = await original_access.auto_approve_timed_out_original_access_requests(db_session, trace_id="t-renew")
    assert stats["approved"] == 1 and stats["errors"] == 0
    await db_session.refresh(req)
    assert req.status == "approved"
    old_after = (await db_session.execute(select(AccessGrant).where(AccessGrant.id == old_id))).scalar_one()
    assert old_after.status == "expired"
    actives = (await db_session.execute(
        select(AccessGrant).where(
            AccessGrant.asset_id == KA_COMPANY_L2, AccessGrant.grantee_user_id == USER_CONSULTANT,
            AccessGrant.status == "active")
    )).scalars().all()
    assert len(actives) == 1
    assert actives[0].id != old_id
    assert actives[0].source_request_id == req.id


async def test_manual_approve_renews_expired_active_grant(db_session):
    await _set_toggle(db_session, COMPANY, value_bool=False)
    req = await _make_pending(db_session, KA_COMPANY_L2, USER_CONSULTANT, age_hours=1)
    old = AccessGrant(
        asset_id=KA_COMPANY_L2, grantee_user_id=USER_CONSULTANT, grant_type="original_access",
        granted_by_user_id=USER_CONSULTANT, status="active", expires_at=_now() - timedelta(days=1),
    )
    db_session.add(old)
    await db_session.commit()
    old_id = old.id

    boss = await _ctx(db_session, USER_BOSS)  # 治理角色可审批公司资产
    res = await original_access.approve_request(db_session, boss, req.id, "manual ok", "t-manual")
    assert res.status == "approved"
    old_after = (await db_session.execute(select(AccessGrant).where(AccessGrant.id == old_id))).scalar_one()
    assert old_after.status == "expired"
    actives = (await db_session.execute(
        select(AccessGrant).where(
            AccessGrant.asset_id == KA_COMPANY_L2, AccessGrant.grantee_user_id == USER_CONSULTANT,
            AccessGrant.status == "active")
    )).scalars().all()
    assert len(actives) == 1 and actives[0].id != old_id


async def test_auto_approve_audit_safe(db_session):
    await _set_toggle(db_session, COMPANY, value_bool=False)
    await _set_numeric(db_session, TIMEOUT, value_number=1, enabled=True)
    await _make_pending(db_session, KA_COMPANY_L2, USER_CONSULTANT, age_hours=5)
    await original_access.auto_approve_timed_out_original_access_requests(db_session, trace_id="t-audit")
    ev = (await db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "access.original_approved")
    )).scalars().all()
    assert any((e.extra or {}).get("auto") is True for e in ev)
    blob = str([(e.extra, e.before_snapshot, e.after_snapshot) for e in ev])
    for token in ["storage_ref", "source_file_ref", "download_url", "token", "cookie",
                  "api_key", "weknora_kb_id", "weknora_doc_id", "sk-", "wk-kb", "wk-doc"]:
        assert token not in blob
    # actor 为系统（无业务发起人）。
    assert any(e.actor_user_id is None for e in ev)


async def test_celery_task_wrapper_returns_safe_stats(db_session):
    import app.worker.tasks.original_access as task_mod

    class _Ctx:
        def __init__(self, s):
            self.s = s

        async def __aenter__(self):
            return self.s

        async def __aexit__(self, *a):
            return False

    class _Maker:
        def __init__(self, s):
            self.s = s

        def __call__(self):
            return _Ctx(self.s)

    await _set_numeric(db_session, TIMEOUT, enabled=False)
    stats = await task_mod._run(_Maker(db_session), "t-task")
    assert set(stats) >= {"checked", "approved", "skipped_confidential", "skipped_invalid", "errors", "enabled"}
    assert stats["enabled"] is False
