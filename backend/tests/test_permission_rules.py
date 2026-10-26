"""权限规则配置中心 API 测试。

覆盖：默认规则幂等创建、读权限（admin/boss/director vs consultant 403）、
写权限（boss/director numeric+toggle 可写；admin 只读 403 admin_business_permission_denied；
consultant 403）、fixed_path 不可改、未知 rule 404、负值校验、写审计 action 与安全无泄露。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.audit import AuditEvent
from app.models.permission_rule import PermissionRule
from app.seed.dev_seed import (
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
)
from app.services import permission_rules as rules_service

RULES = "/api/v1/admin/permissions/rules"

_LEAK_TOKENS = [
    "token_hash",
    "token",
    "api_key",
    "app_secret",
    "storage_ref",
    "source_file_ref",
    "dataset_id",
    "workflow_id",
    "kb_id",
    "bucket",
    "base_url",
    "weknora",
    "oauth",
]


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


def _assert_no_leak(text: str):
    low = text.lower()
    for t in _LEAK_TOKENS:
        assert t not in low, f"响应不应泄露 {t}"


async def _rule_by_key(client, user_id, key):
    r = await client.get(RULES, headers=_hdr(user_id))
    assert r.status_code == 200, r.text
    return next(i for i in r.json()["items"] if i["rule_key"] == key)


# ---------------- 读权限 ----------------
async def test_admin_can_read_rules_no_leak(client):
    r = await client.get(RULES, headers=_hdr(USER_ADMIN_ONLY))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 15 and len(body["items"]) == body["total"]
    item = body["items"][0]
    for k in (
        "rule_id",
        "rule_key",
        "rule_group",
        "rule_type",
        "display_name",
        "default_bool",
        "default_number",
        "default_text",
        "editable",
        "updated_at",
    ):
        assert k in item
    _assert_no_leak(r.text)


async def test_boss_and_director_can_read(client):
    for uid in (USER_BOSS, USER_DIRECTOR):
        r = await client.get(RULES, headers=_hdr(uid))
        assert r.status_code == 200


async def test_consultant_cannot_read(client):
    r = await client.get(RULES, headers=_hdr(USER_CONSULTANT))
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "permission_rules_forbidden"


# ---------------- 默认规则幂等 ----------------
async def test_default_rules_idempotent(client, db_session):
    # 两次读触发两次 ensure，不应重复建行。
    await client.get(RULES, headers=_hdr(USER_ADMIN_ONLY))
    await client.get(RULES, headers=_hdr(USER_BOSS))
    rows = (await db_session.execute(select(PermissionRule.rule_key))).scalars().all()
    assert len(rows) == len(set(rows)) == len(rules_service.DEFAULT_RULES)


# ---------------- 写权限 ----------------
async def test_boss_can_update_numeric(client):
    rule = await _rule_by_key(client, USER_BOSS, "access_request_timeout_hours")
    r = await client.patch(
        f"{RULES}/{rule['rule_id']}",
        headers=_hdr(USER_BOSS),
        json={"value_number": 72},
    )
    assert r.status_code == 200, r.text
    assert r.json()["value_number"] == 72
    assert r.json()["updated_by_name"] == "总经理C"


async def test_director_can_update_toggle(client):
    rule = await _rule_by_key(client, USER_DIRECTOR, "company_l1_l2_original_for_business_user")
    r = await client.patch(
        f"{RULES}/{rule['rule_id']}",
        headers=_hdr(USER_DIRECTOR),
        json={"value_bool": False},
    )
    assert r.status_code == 200, r.text
    assert r.json()["value_bool"] is False


async def test_admin_cannot_update(client):
    rule = await _rule_by_key(client, USER_ADMIN_ONLY, "review_timeout_hours")
    r = await client.patch(
        f"{RULES}/{rule['rule_id']}",
        headers=_hdr(USER_ADMIN_ONLY),
        json={"value_number": 99},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "admin_business_permission_denied"


async def test_consultant_cannot_update(client):
    # consultant 无读权；用 boss 取 id，再以 consultant 改 → 403。
    rule = await _rule_by_key(client, USER_BOSS, "review_timeout_hours")
    r = await client.patch(
        f"{RULES}/{rule['rule_id']}",
        headers=_hdr(USER_CONSULTANT),
        json={"value_number": 1},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "permission_rules_forbidden"


# ---------------- 校验 ----------------
async def test_fixed_path_not_editable(client):
    rule = await _rule_by_key(client, USER_BOSS, "project_asset_validation_paths")
    assert rule["editable"] is False
    r = await client.patch(
        f"{RULES}/{rule['rule_id']}",
        headers=_hdr(USER_BOSS),
        json={"value_text": "随意改"},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["denied_reason"] == "rule_not_editable"


async def test_numeric_rejects_negative(client):
    rule = await _rule_by_key(client, USER_BOSS, "access_grant_duration_days")
    r = await client.patch(
        f"{RULES}/{rule['rule_id']}",
        headers=_hdr(USER_BOSS),
        json={"value_number": -1},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["denied_reason"] == "invalid_rule_value"


async def test_numeric_rejects_bool(client):
    rule = await _rule_by_key(client, USER_BOSS, "access_grant_duration_days")
    r = await client.patch(
        f"{RULES}/{rule['rule_id']}",
        headers=_hdr(USER_BOSS),
        json={"value_bool": True},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["denied_reason"] == "invalid_rule_value"


async def test_unknown_rule_404(client):
    r = await client.patch(
        f"{RULES}/{uuid.uuid4()}",
        headers=_hdr(USER_BOSS),
        json={"value_number": 1},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["denied_reason"] == "permission_rule_not_found"


# ---------------- 审计 ----------------
async def test_update_writes_safe_audit(client, db_session):
    rule = await _rule_by_key(client, USER_BOSS, "access_grant_duration_days")
    r = await client.patch(
        f"{RULES}/{rule['rule_id']}",
        headers={**_hdr(USER_BOSS), "X-Trace-Id": "trc-permission-rules"},
        json={"value_number": 400},
    )
    assert r.status_code == 200, r.text
    rows = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "config.permission_rule_updated")
            )
        )
        .scalars()
        .all()
    )
    assert rows, "应写入 config.permission_rule_updated 审计事件"
    ev = rows[-1]
    assert ev.target_type == "permission_rule"
    assert ev.target_id == uuid.UUID(rule["rule_id"])
    extra = ev.extra or {}
    assert extra.get("rule_key") == "access_grant_duration_days"
    assert (ev.before_snapshot or {}).get("value_number") == 7
    assert (ev.after_snapshot or {}).get("value_number") == 400
    blob = str(extra) + str(ev.before_snapshot) + str(ev.after_snapshot)
    for t in _LEAK_TOKENS:
        assert t not in blob.lower()


async def test_retired_cross_project_rule_is_hidden_and_rejects_stale_write(client, db_session):
    legacy = PermissionRule(
        rule_key="cross_project_l1_l2_original_for_business_user",
        rule_group="access_request",
        rule_type="toggle",
        display_name="跨项目 L1/L2 原文默认放行业务用户",
        value_bool=True,
        editable=True,
        enabled=True,
    )
    db_session.add(legacy)
    await db_session.commit()
    await db_session.refresh(legacy)
    rule_id, updated_at = legacy.id, legacy.updated_at
    response = await client.get(RULES, headers=_hdr(USER_BOSS))
    assert legacy.rule_key not in {r["rule_key"] for r in response.json()["items"]}
    response = await client.patch(
        f"{RULES}/{rule_id}", headers=_hdr(USER_BOSS), json={"value_bool": False}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["denied_reason"] == "rule_not_editable"
    await db_session.refresh(legacy)
    assert legacy.value_bool is True and legacy.updated_at == updated_at
    assert (
        not (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.target_id == rule_id,
                    AuditEvent.action == "config.permission_rule_updated",
                )
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.parametrize(
    "key",
    [
        "cross_project_source_threshold",
        "cross_project_call_count_threshold",
        "project_upgrade_signal_window_days",
        "review_timeout_hours",
        "asset_modify_rate_threshold",
        "asset_not_helpful_threshold",
        "asset_expiry_days",
        "asset_archive_inactive_days",
        "asset_archive_notice_days",
    ],
)
async def test_reference_rule_cannot_claim_to_change_runtime(client, db_session, key):
    await rules_service.ensure_default_rules(db_session)
    stored = (
        await db_session.execute(select(PermissionRule).where(PermissionRule.rule_key == key))
    ).scalar_one()
    stored.description = "旧说明：自动归档或直接触发处理"
    stored.editable = True
    await db_session.commit()
    await db_session.refresh(stored)
    old_value, old_time = stored.value_number, stored.updated_at
    rule = await _rule_by_key(client, USER_BOSS, key)
    assert rule["effective_mode"] == "reference" and rule["editable"] is False
    assert "参考" in rule["description"] and "自动归档" not in rule["description"]
    response = await client.patch(
        f"{RULES}/{stored.id}", headers=_hdr(USER_BOSS), json={"value_number": 11}
    )
    assert response.status_code == 422
    await db_session.refresh(stored)
    assert stored.value_number == old_value and stored.updated_at == old_time
    assert stored.description == "旧说明：自动归档或直接触发处理"


@pytest.mark.parametrize(
    "key",
    [
        "personal_knowledge_default_private",
        "personal_to_project_material_requires_owner_submit",
    ],
)
async def test_legacy_personal_toggle_is_presented_as_fixed_policy(client, db_session, key):
    await rules_service.ensure_default_rules(db_session)
    stored = (
        await db_session.execute(select(PermissionRule).where(PermissionRule.rule_key == key))
    ).scalar_one()
    stored.rule_type = "toggle"
    stored.value_bool = False
    stored.editable = True
    await db_session.commit()
    await db_session.refresh(stored)
    old_time = stored.updated_at
    rule = await _rule_by_key(client, USER_BOSS, key)
    assert rule["effective_mode"] == "fixed" and rule["editable"] is False
    assert rule["rule_type"] == "fixed_path" and rule["value_text"]
    response = await client.patch(
        f"{RULES}/{stored.id}", headers=_hdr(USER_BOSS), json={"enabled": False}
    )
    assert response.status_code == 422
    await db_session.refresh(stored)
    assert stored.value_bool is False and stored.updated_at == old_time
