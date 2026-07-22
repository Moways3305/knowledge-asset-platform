"""`/api/v1/auth/me` 接口测试。

覆盖：默认开发用户、指定 X-Dev-User-Id、active 过滤、admin 边界、L5 发现、
consultant+admin 双角色。
"""

from __future__ import annotations

import uuid

from app.core.config import Settings
from app.models.identity import User, UserCompanyRole
from app.seed.dev_seed import (
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_CONSULTANT_ADMIN,
    USER_DIRECTOR,
    USER_PROJECT_MANAGER,
)
from app.services.permission import build_caller_context

ME_URL = "/api/v1/auth/me"


async def test_me_without_header_returns_default_dev_user(client):
    """未带 X-Dev-User-Id 时返回默认开发用户（顾问A）。"""
    resp = await client.get(ME_URL)
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "consultant.a@dev.local"
    assert body["is_business_user"] is True


async def test_me_with_header_returns_specified_user(client):
    """携带 X-Dev-User-Id 时返回指定用户（老板C）。"""
    resp = await client.get(ME_URL, headers={"X-Dev-User-Id": str(USER_BOSS)})
    assert resp.status_code == 200
    assert resp.json()["email"] == "boss.c@dev.local"


async def test_company_roles_only_active(client):
    """管理员E 带一个 inactive 的 consultant 角色，company_roles 不应包含它。"""
    resp = await client.get(ME_URL, headers={"X-Dev-User-Id": str(USER_ADMIN_ONLY)})
    body = resp.json()
    assert body["company_roles"] == ["admin"]
    assert "consultant" not in body["company_roles"]


async def test_project_memberships_only_active(client):
    """顾问A 在 Beta 项目的成员关系为 inactive，project_memberships 只含 Alpha。"""
    resp = await client.get(ME_URL, headers={"X-Dev-User-Id": str(USER_CONSULTANT)})
    body = resp.json()
    project_names = [m["project_name"] for m in body["project_memberships"]]
    assert project_names == ["Alpha 项目"]
    assert body["project_memberships"][0]["project_role"] == "consultant"


async def test_admin_only_is_not_business_user(client):
    """纯 admin（active）不应是业务用户，也不能发现 L5。"""
    resp = await client.get(ME_URL, headers={"X-Dev-User-Id": str(USER_ADMIN_ONLY)})
    body = resp.json()
    assert body["is_business_user"] is False
    assert body["can_discover_l5"] is False


async def test_boss_can_discover_l5(client):
    """boss 可以发现 L5。"""
    resp = await client.get(ME_URL, headers={"X-Dev-User-Id": str(USER_BOSS)})
    body = resp.json()
    assert body["can_discover_l5"] is True
    assert body["is_business_user"] is True


async def test_director_can_discover_l5(client):
    """consulting_director 可以发现 L5。"""
    resp = await client.get(ME_URL, headers={"X-Dev-User-Id": str(USER_DIRECTOR)})
    assert resp.json()["can_discover_l5"] is True


async def test_consultant_plus_admin_defaults_to_admin_identity(client):
    """多角色不再求并集；安全默认到管理员身份，需经会话主动切换后才有业务能力。"""
    resp = await client.get(ME_URL, headers={"X-Dev-User-Id": str(USER_CONSULTANT_ADMIN)})
    body = resp.json()
    assert body["is_business_user"] is False
    assert body["can_discover_l5"] is False
    assert set(body["company_roles"]) == {"consultant", "admin"}
    assert body["active_company_role"] == "admin"
    assert body["project_memberships"] == []


def test_business_identity_without_any_project_membership_is_valid():
    """A project-free system/user is valid; no synthetic manager membership is required."""
    user = User(id=uuid.uuid4(), name="无项目用户", email="none@example.test", status="active")
    user.company_roles.append(UserCompanyRole(company_role="boss", status="active"))
    caller = build_caller_context(user, active_company_role="boss")
    assert caller.is_business_user is True
    assert caller.active_project_ids == set()
    assert caller.active_project_roles == {}


async def test_project_manager_role_from_membership(client):
    """经理B 的 project_manager 角色来自 project_members。"""
    resp = await client.get(ME_URL, headers={"X-Dev-User-Id": str(USER_PROJECT_MANAGER)})
    body = resp.json()
    assert body["project_memberships"][0]["project_role"] == "project_manager"


async def test_unknown_user_returns_404(client):
    """未知用户 id 返回 404。"""
    unknown = "00000000-0000-0000-0000-0000000000ff"
    resp = await client.get(ME_URL, headers={"X-Dev-User-Id": unknown})
    assert resp.status_code == 404


async def test_invalid_dev_user_id_returns_400(client):
    """非法（非 UUID）的 X-Dev-User-Id 返回 400。"""
    resp = await client.get(ME_URL, headers={"X-Dev-User-Id": "not-a-uuid"})
    assert resp.status_code == 400


async def test_non_dev_environment_disables_mock_identity(client, monkeypatch):
    """非 local/dev/test 环境（如 prod）禁用开发态 mock identity。

    IMPLEMENT-12：身份改由会话提供。prod 环境下 X-Dev-User-Id 被忽略，且无有效
    会话 cookie，故视为未认证 → 401 not_authenticated（替代旧的 403）。
    通过 monkeypatch 使 app_env=prod，仅影响本测试。
    """
    monkeypatch.setattr(
        "app.api.auth.get_settings",
        lambda: Settings(app_env="prod"),
    )
    resp = await client.get(ME_URL, headers={"X-Dev-User-Id": str(USER_BOSS)})
    assert resp.status_code == 401
