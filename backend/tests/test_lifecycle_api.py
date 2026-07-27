"""生命周期归档 / 重新启用 + 告警规则 / 通知 API 测试（IMPLEMENT-10）。

覆盖任务要求 1-12：迁移仅三表、archive-request 不改状态、archive-confirm 改状态、
归档后仍被检索/预览/Agent 排除、reenable-request/confirm、纯 admin 拒绝强审计、
personal/project/company 权限边界、L5 不泄露、告警规则增改审计、通知安全元数据、
审计/生命周期/通知不落禁止键或敏感值。
"""

from __future__ import annotations

from app.seed.dev_seed import (
    KA_COMPANY_L2,
    KA_COMPANY_L5,
    KA_PERSONAL,
    KA_PROJECT_ALPHA,
    KA_PROJECT_ALPHA_ARCHIVED,
    PROJECT_ALPHA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
    USER_PROJECT_MANAGER,
)

LC = "/api/v1/knowledge/{aid}/lifecycle"
AUDIT = "/api/v1/admin/audit"
ALERTS = "/api/v1/admin/alerts"

_LEAK_TOKENS = [
    "storage_ref",
    "source_file_ref",
    "vector_id",
    "api_key",
    "dataset_id",
    "workflow_id",
    "kb_id",
    "bucket",
    "s3://",
    "oss://",
    "internal://",
    "download_url",
    "file_url",
    "preview_token",
    "token_hash",
]


def _hdr(user_id, trace=None):
    h = {"X-Dev-User-Id": str(user_id)}
    if trace:
        h["X-Trace-Id"] = trace
    return h


def _assert_no_leak(text: str):
    for t in _LEAK_TOKENS:
        assert t not in text, f"响应不应泄露 {t}"


async def _events(client, aid, viewer=USER_BOSS):
    r = await client.get(LC.format(aid=aid) + "/events", headers=_hdr(viewer))
    assert r.status_code == 200, r.text
    return r.json()["items"]


# ---- 1. 迁移 0008 仅创建三张允许的表 ----
def test_migration_0008_creates_only_three_tables():
    import pathlib
    import re

    path = (
        pathlib.Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / ("0008_create_lifecycle_alert_notification.py")
    )
    text = path.read_text(encoding="utf-8")
    created = set(re.findall(r'op\.create_table\(\s*"([^"]+)"', text))
    assert created == {
        "asset_lifecycle_events",
        "alert_rules",
        "notification_records",
    }


# ---- 2. archive-request 创建事件 + 审计，但不改状态 ----
async def test_archive_request_creates_event_no_status_change(client):
    aid = KA_PROJECT_ALPHA
    r = await client.post(
        LC.format(aid=aid) + "/archive-request",
        headers=_hdr(USER_CONSULTANT, "trc-areq"),
        json={"reason": "长期未调用", "candidate_source": "manual"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["lifecycle_event_id"]
    assert body["status"] == "archive_candidate"
    assert body["trace_id"] == "trc-areq"

    # 资产状态未变（仍可在知识详情看到，active）。
    detail = await client.get(f"/api/v1/knowledge/{aid}", headers=_hdr(USER_CONSULTANT))
    assert detail.status_code == 200
    assert detail.json()["asset_status"] == "active"

    # 事件 + 审计共享 trace。
    evts = await _events(client, aid)
    assert any(e["event_type"] == "archive_candidate" for e in evts)
    audit = await client.get(f"{AUDIT}/trace/trc-areq", headers=_hdr(USER_BOSS))
    actions = {e["action"] for e in audit.json()["items"]}
    assert "lifecycle.archive_candidate" in actions


# ---- 3. archive-confirm 改状态为 archived + 事件 + 审计 ----
async def test_archive_confirm_sets_archived(client):
    aid = KA_PROJECT_ALPHA
    r = await client.post(
        LC.format(aid=aid) + "/archive-confirm",
        headers=_hdr(USER_CONSULTANT, "trc-aconf"),
        json={"reason": "项目结束归档"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["asset_status"] == "archived"
    assert body["archived_at"] is not None
    assert body["archive_reason"] == "项目结束归档"

    evts = await _events(client, aid)
    archived = next(e for e in evts if e["event_type"] == "archived")
    assert archived["old_status"] == "active"
    assert archived["new_status"] == "archived"

    audit = await client.get(f"{AUDIT}/trace/trc-aconf", headers=_hdr(USER_BOSS))
    actions = {e["action"] for e in audit.json()["items"]}
    assert "lifecycle.archived" in actions


# ---- 4. 归档后仍被知识列表 / 预览 / Agent 排除 ----
async def test_archived_excluded_in_knowledge_preview_agent(client):
    aid = KA_PROJECT_ALPHA
    await client.post(
        LC.format(aid=aid) + "/archive-confirm",
        headers=_hdr(USER_CONSULTANT, "trc-x"),
        json={"reason": "归档"},
    )
    # 知识列表（含 include_archived）对普通成员仍不返回该资产。
    lst = await client.get("/api/v1/knowledge?include_archived=true", headers=_hdr(USER_CONSULTANT))
    assert all(item["id"] != str(aid) for item in lst.json()["items"])

    # 预览签发被拒（asset_not_active）。
    pv = await client.post(f"/api/v1/knowledge/{aid}/preview", headers=_hdr(USER_CONSULTANT))
    assert pv.status_code == 403
    assert pv.json()["detail"]["denied_reason"] == "asset_not_active"

    # Agent 召回不含已归档资产。
    qa = await client.post(
        f"/api/v1/projects/{PROJECT_ALPHA}/qa",
        headers=_hdr(USER_CONSULTANT),
        json={"query": "供应链优化"},
    )
    if qa.status_code == 200:
        cited = {c["asset_id"] for c in qa.json()["citations"]}
        assert str(aid) not in cited


# ---- 5 & 6. reenable-request 不改状态；reenable-confirm 改状态且保留归档记录 ----
async def test_reenable_request_then_confirm(client):
    aid = KA_PROJECT_ALPHA
    # 先归档（设置 archived_at / archive_reason），再走重新启用以验证保留。
    await client.post(
        LC.format(aid=aid) + "/archive-confirm",
        headers=_hdr(USER_CONSULTANT),
        json={"reason": "先归档"},
    )

    req = await client.post(
        LC.format(aid=aid) + "/reenable-request",
        headers=_hdr(USER_CONSULTANT, "trc-rreq"),
        json={"reason": "项目复用需要", "target_status": "active"},
    )
    assert req.status_code == 200, req.text
    assert req.json()["status"] == "reenable_requested"
    # 仍为 archived（events 查询可见 archived 资产）。
    evts = await _events(client, aid, viewer=USER_CONSULTANT)
    assert any(e["event_type"] == "reenable_requested" for e in evts)

    conf = await client.post(
        LC.format(aid=aid) + "/reenable-confirm",
        headers=_hdr(USER_CONSULTANT, "trc-rconf"),
        json={"reason": "复核通过", "target_status": "needs_update"},
    )
    assert conf.status_code == 200, conf.text
    assert conf.json()["asset_status"] == "needs_update"

    # 重新启用后归档历史保留（archived_at / archive_reason 不清空）—— 经详情可见。
    detail = await client.get(f"/api/v1/knowledge/{aid}", headers=_hdr(USER_CONSULTANT))
    assert detail.status_code == 200
    assert detail.json()["archived_at"] is not None
    assert detail.json()["archive_reason"] == "先归档"

    audit = await client.get(f"{AUDIT}/trace/trc-rconf", headers=_hdr(USER_BOSS))
    assert "lifecycle.reenabled" in {e["action"] for e in audit.json()["items"]}


async def test_reenable_confirm_rejects_bad_target_status(client):
    r = await client.post(
        LC.format(aid=KA_PROJECT_ALPHA_ARCHIVED) + "/reenable-confirm",
        headers=_hdr(USER_CONSULTANT),
        json={"reason": "x", "target_status": "deprecated"},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["denied_reason"] == "lifecycle_invalid_target_status"


# ---- 7. 纯 admin 生命周期动作被拒并写 admin.business_denied（强审计）----
async def test_pure_admin_lifecycle_denied_strong_audit(client):
    r = await client.post(
        LC.format(aid=KA_PROJECT_ALPHA) + "/archive-confirm",
        headers=_hdr(USER_ADMIN_ONLY, "trc-admindeny"),
        json={"reason": "x"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "admin_business_permission_denied"
    audit = await client.get(f"{AUDIT}/trace/trc-admindeny", headers=_hdr(USER_BOSS))
    denied = next(e for e in audit.json()["items"] if e["action"] == "admin.business_denied")
    assert denied["severity"] == "warning"
    assert denied["risk_level"] == "high"


# ---- 8. personal / project / company 权限边界 ----
async def test_detail_exposes_lifecycle_capability_independently_from_delete(client):
    maintainer = await client.get(
        f"/api/v1/knowledge/{KA_PROJECT_ALPHA}", headers=_hdr(USER_CONSULTANT)
    )
    assert maintainer.status_code == 200
    maintainer_access = maintainer.json()["access_info"]
    assert maintainer_access["can_manage_lifecycle"] is True
    assert maintainer_access["can_delete"] is False

    project_manager = await client.get(
        f"/api/v1/knowledge/{KA_PROJECT_ALPHA}", headers=_hdr(USER_PROJECT_MANAGER)
    )
    assert project_manager.status_code == 200
    assert project_manager.json()["access_info"]["can_manage_lifecycle"] is True

    consultant = await client.get(
        f"/api/v1/knowledge/{KA_COMPANY_L2}", headers=_hdr(USER_CONSULTANT)
    )
    assert consultant.status_code == 200
    assert consultant.json()["access_info"]["can_manage_lifecycle"] is False


async def test_personal_only_owner(client):
    # 他人（经理B）对顾问A的个人资产 → 表现为不存在（不泄露）。
    other = await client.post(
        LC.format(aid=KA_PERSONAL) + "/archive-request",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={"reason": "x"},
    )
    assert other.status_code == 404
    # 本人允许。
    owner = await client.post(
        LC.format(aid=KA_PERSONAL) + "/archive-request",
        headers=_hdr(USER_CONSULTANT),
        json={"reason": "整理"},
    )
    assert owner.status_code == 200


async def test_project_maintainer_and_pm_allowed_others_denied(client):
    # 项目经理（PM of ALPHA）允许。
    pm = await client.post(
        LC.format(aid=KA_PROJECT_ALPHA) + "/archive-request",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={"reason": "pm 发起"},
    )
    assert pm.status_code == 200
    # boss 非项目成员、非 maintainer、project scope → 不允许（lifecycle_action_not_allowed）。
    boss = await client.post(
        LC.format(aid=KA_PROJECT_ALPHA) + "/archive-request",
        headers=_hdr(USER_BOSS),
        json={"reason": "x"},
    )
    assert boss.status_code == 403
    assert boss.json()["detail"]["denied_reason"] == "lifecycle_action_not_allowed"


async def test_company_governance_only(client):
    # 顾问A（非治理）对公司资产 → 403 lifecycle_action_not_allowed。
    consultant = await client.post(
        LC.format(aid=KA_COMPANY_L2) + "/archive-request",
        headers=_hdr(USER_CONSULTANT),
        json={"reason": "x"},
    )
    assert consultant.status_code == 403
    assert consultant.json()["detail"]["denied_reason"] == "lifecycle_action_not_allowed"
    # 咨询总监允许，且公司级确认为强审计。
    director = await client.post(
        LC.format(aid=KA_COMPANY_L2) + "/archive-confirm",
        headers=_hdr(USER_DIRECTOR, "trc-coconf"),
        json={"reason": "公司治理归档"},
    )
    assert director.status_code == 200
    audit = await client.get(f"{AUDIT}/trace/trc-coconf", headers=_hdr(USER_BOSS))
    arch = next(e for e in audit.json()["items"] if e["action"] == "lifecycle.archived")
    assert arch["risk_level"] == "high"  # 公司级强审计


# ---- 9. L5 不可发现用户的生命周期访问不泄露存在 ----
async def test_l5_lifecycle_no_leak(client):
    # 顾问A 不可发现公司 L5 → 动作与事件查询均 404（不泄露）。
    act = await client.post(
        LC.format(aid=KA_COMPANY_L5) + "/archive-request",
        headers=_hdr(USER_CONSULTANT),
        json={"reason": "x"},
    )
    assert act.status_code == 404
    evt = await client.get(LC.format(aid=KA_COMPANY_L5) + "/events", headers=_hdr(USER_CONSULTANT))
    assert evt.status_code == 404
    # boss 可见且确认为强审计（L5 + company）。
    conf = await client.post(
        LC.format(aid=KA_COMPANY_L5) + "/archive-confirm",
        headers=_hdr(USER_BOSS, "trc-l5conf"),
        json={"reason": "绝密归档"},
    )
    assert conf.status_code == 200


# ---- 10. 告警规则列表 / 更新（admin）+ config.alert_rule_updated 审计 ----
async def test_alert_rules_list_and_update(client):
    # 当前治理身份可读取告警规则。
    governance = await client.get(f"{ALERTS}/rules", headers=_hdr(USER_BOSS))
    assert governance.status_code == 200

    rules = await client.get(f"{ALERTS}/rules", headers=_hdr(USER_ADMIN_ONLY))
    assert rules.status_code == 200
    items = rules.json()["items"]
    # 默认归档阈值规则（730 天未调用 + 30 天预警期）已落库。
    thresholds = {r["rule_name"]: r["threshold"] for r in items}
    assert thresholds.get("长期未调用归档预警") == 730
    assert thresholds.get("归档预警期") == 30

    rid = items[0]["id"]
    patched = await client.patch(
        f"{ALERTS}/rules/{rid}",
        headers=_hdr(USER_ADMIN_ONLY, "trc-rule"),
        json={"enabled": False, "threshold": 365, "notification_channels": ["in_app", "email"]},
    )
    assert patched.status_code == 200
    assert patched.json()["enabled"] is False
    assert patched.json()["threshold"] == 365

    governance_patch = await client.patch(
        f"{ALERTS}/rules/{rid}", headers=_hdr(USER_BOSS), json={"enabled": True}
    )
    assert governance_patch.status_code == 200

    audit = await client.get(f"{AUDIT}/trace/trc-rule", headers=_hdr(USER_DIRECTOR))
    assert "config.alert_rule_updated" in {e["action"] for e in audit.json()["items"]}


# ---- 11. 通知记录列表只回安全元数据 ----
async def test_notifications_safe_metadata(client):
    # 触发一次归档确认 → 生成一条本地通知。
    await client.post(
        LC.format(aid=KA_PROJECT_ALPHA) + "/archive-confirm",
        headers=_hdr(USER_CONSULTANT),
        json={"reason": "归档触发通知"},
    )
    # 非 admin 无权。
    forbidden = await client.get(f"{ALERTS}/notifications", headers=_hdr(USER_CONSULTANT))
    assert forbidden.status_code == 403

    notifs = await client.get(f"{ALERTS}/notifications", headers=_hdr(USER_ADMIN_ONLY))
    assert notifs.status_code == 200
    items = notifs.json()["items"]
    assert len(items) >= 1
    assert all(n["send_status"] == "pending" for n in items)  # 未真实发送
    _assert_no_leak(notifs.text)


# ---- 12b. 用户文本 reason 的值级脱敏（IMPLEMENT-10_FIX）----
async def test_lifecycle_reason_value_sanitized_everywhere(client):
    """敏感字符串 reason 即便由用户文本传入，也不得在任何落库 / 响应处出现原值。"""
    aid = KA_PROJECT_ALPHA
    # 归档确认：reason 为对象存储 URL。
    conf = await client.post(
        LC.format(aid=aid) + "/archive-confirm",
        headers=_hdr(USER_CONSULTANT, "trc-san"),
        json={"reason": "s3://real-bucket/path/file.pdf"},
    )
    assert conf.status_code == 200
    assert conf.json()["archive_reason"] == "[redacted]"
    for m in ("s3://", "real-bucket", "path/file.pdf"):
        assert m not in conf.text

    # 生命周期事件 reason 被脱敏。
    evts = await client.get(LC.format(aid=aid) + "/events", headers=_hdr(USER_CONSULTANT))
    archived = next(e for e in evts.json()["items"] if e["event_type"] == "archived")
    assert archived["reason"] == "[redacted]"
    assert "s3://" not in evts.text

    # 重新启用确认：reason 为内部地址，目标 needs_update。
    re = await client.post(
        LC.format(aid=aid) + "/reenable-confirm",
        headers=_hdr(USER_CONSULTANT, "trc-san2"),
        json={"reason": "internal://archive/secret", "target_status": "needs_update"},
    )
    assert re.status_code == 200

    # 详情：归档历史保留，archive_reason 仍为脱敏占位（不含原值）。
    detail = await client.get(f"/api/v1/knowledge/{aid}", headers=_hdr(USER_CONSULTANT))
    assert detail.status_code == 200
    assert detail.json()["archive_reason"] == "[redacted]"

    # reenabled 事件 reason 被脱敏（无 internal://）。
    evts2 = await client.get(LC.format(aid=aid) + "/events", headers=_hdr(USER_CONSULTANT))
    reenabled = next(e for e in evts2.json()["items"] if e["event_type"] == "reenabled")
    assert reenabled["reason"] == "[redacted]"
    assert "internal://" not in evts2.text

    # 通知 title / content 无任何敏感标记 / 原值。
    notifs = await client.get(f"{ALERTS}/notifications", headers=_hdr(USER_ADMIN_ONLY))
    for m in ("s3://", "real-bucket", "internal://", "secret", "path/file.pdf"):
        assert m not in notifs.text

    # 审计链路（两条 trace）同样无原值。
    for trace in ("trc-san", "trc-san2"):
        audit = await client.get(f"{AUDIT}/trace/{trace}", headers=_hdr(USER_BOSS))
        for m in ("s3://", "real-bucket", "internal://", "path/file.pdf"):
            assert m not in audit.text


# ---- 12. 审计 / 生命周期 / 通知不落禁止键或敏感值 ----
async def test_lifecycle_records_no_forbidden_values(client):
    aid = KA_PROJECT_ALPHA
    await client.post(
        LC.format(aid=aid) + "/archive-confirm",
        headers=_hdr(USER_CONSULTANT, "trc-leak"),
        json={"reason": "归档"},
    )
    # 生命周期事件、审计 trace、通知三处均不泄露敏感标识。
    evts = await client.get(LC.format(aid=aid) + "/events", headers=_hdr(USER_CONSULTANT))
    _assert_no_leak(evts.text)
    audit = await client.get(f"{AUDIT}/trace/trc-leak", headers=_hdr(USER_BOSS))
    _assert_no_leak(audit.text)
    notifs = await client.get(f"{ALERTS}/notifications", headers=_hdr(USER_ADMIN_ONLY))
    _assert_no_leak(notifs.text)
