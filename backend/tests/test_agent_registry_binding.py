"""WorkBuddy per-user token 绑定校验测试（admin create 经既有白名单端点）。"""

from __future__ import annotations

import uuid

from app.models.identity import User, UserCompanyRole
from app.seed.dev_seed import USER_ADMIN_ONLY, USER_CONSULTANT

WHITELIST = "/api/v1/admin/permissions/agent-whitelist"


def _admin_hdr():
    return {"X-Dev-User-Id": str(USER_ADMIN_ONLY)}


def _payload(**over):
    body = {
        "provider": "workbuddy",
        "agent_identifier": f"wb-{uuid.uuid4().hex[:8]}",
        "agent_name": "WorkBuddy 接入",
        "capability": "qa",
        "max_confidentiality_level": "L2",
        "max_ai_access_level": "A2",
    }
    body.update(over)
    return body


async def test_workbuddy_requires_bound_user(client):
    resp = await client.post(WHITELIST, headers=_admin_hdr(), json=_payload())
    assert resp.status_code == 400
    assert resp.json()["detail"]["denied_reason"] == "bound_user_required"


async def test_bind_pure_admin_rejected(client):
    resp = await client.post(
        WHITELIST, headers=_admin_hdr(), json=_payload(bound_user_id=str(USER_ADMIN_ONLY))
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["denied_reason"] == "bound_user_invalid"


async def test_bind_inactive_user_rejected(client, db_session):
    inactive_id = uuid.uuid4()
    u = User(
        id=inactive_id,
        name="停用员工",
        email=f"x{inactive_id.hex[:6]}@dev.local",
        status="inactive",
    )
    u.company_roles.append(UserCompanyRole(company_role="consultant", status="active"))
    db_session.add(u)
    await db_session.commit()
    resp = await client.post(
        WHITELIST, headers=_admin_hdr(), json=_payload(bound_user_id=str(inactive_id))
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["denied_reason"] == "bound_user_invalid"


async def test_valid_binding_returns_token_and_safe_view(client):
    resp = await client.post(
        WHITELIST, headers=_admin_hdr(), json=_payload(bound_user_id=str(USER_CONSULTANT))
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token"] and body["token"].startswith("kgw_")
    rule = body["rule"]
    assert rule["bound_user_id"] == str(USER_CONSULTANT)
    assert rule["bound_user_name"]  # 安全展示名
    assert rule["bound_user_active"] is True
    for k in ("token_hash", "external_app_id", "external_workflow_id", "agent_identifier"):
        assert k not in rule


async def test_provider_default_is_custom(client):
    resp = await client.post(
        WHITELIST,
        headers=_admin_hdr(),
        json={
            "agent_identifier": f"c-{uuid.uuid4().hex[:8]}",
            "agent_name": "中立接入",
            "capability": "qa",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["rule"]["provider"] == "custom"
