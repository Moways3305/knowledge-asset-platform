"""Shared selector permissions must survive retirement of their former host feature."""

import pytest

from app.models.identity import User
from app.seed.dev_seed import (
    PROJECT_ALPHA,
    PROJECT_BETA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_PROJECT_MANAGER,
)


@pytest.mark.parametrize("kind", ["users", "projects"])
@pytest.mark.parametrize("user", [USER_ADMIN_ONLY, USER_BOSS, USER_PROJECT_MANAGER])
async def test_operator_selectors_remain_available(client, kind, user):
    response = await client.get(
        f"/api/v1/admin/operation-options/{kind}", headers={"X-Dev-User-Id": str(user)}
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"]
    allowed = {"id", "name"} if kind == "projects" else {"user_id", "name", "role_label"}
    assert all(set(item) == allowed for item in response.json()["items"])


@pytest.mark.parametrize("kind", ["users", "projects"])
async def test_consultant_cannot_read_management_options(client, kind):
    response = await client.get(
        f"/api/v1/admin/operation-options/{kind}",
        headers={"X-Dev-User-Id": str(USER_CONSULTANT)},
    )
    assert response.status_code == 403


async def test_project_manager_only_sees_managed_projects(client):
    response = await client.get(
        "/api/v1/admin/operation-options/projects",
        headers={"X-Dev-User-Id": str(USER_PROJECT_MANAGER)},
    )
    ids = {item["id"] for item in response.json()["items"]}
    assert str(PROJECT_ALPHA) in ids
    assert str(PROJECT_BETA) not in ids


async def test_inactive_and_system_only_users_are_not_binding_candidates(client, db_session):
    user = await db_session.get(User, USER_CONSULTANT)
    user.status = "inactive"
    await db_session.commit()
    response = await client.get(
        "/api/v1/admin/operation-options/users",
        headers={"X-Dev-User-Id": str(USER_ADMIN_ONLY)},
    )
    ids = {item["user_id"] for item in response.json()["items"]}
    assert str(USER_CONSULTANT) not in ids
    assert str(USER_ADMIN_ONLY) not in ids
