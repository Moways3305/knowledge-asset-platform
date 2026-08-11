"""PBC-70 project switching and overview permission contract."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.identity import Project, ProjectMember, User, UserCompanyRole
from app.seed.dev_seed import (
    KA_PROJECT_ALPHA_L5,
    PROJECT_ALPHA,
    PROJECT_BETA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
    USER_PROJECT_MANAGER,
)

PROJECTS = "/api/v1/projects"


def _headers(user_id: uuid.UUID) -> dict[str, str]:
    return {"X-Dev-User-Id": str(user_id)}


async def _member_user(
    db_session,
    *,
    project_id: uuid.UUID,
    project_role: str,
    company_role: str = "consultant",
) -> uuid.UUID:
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        name=f"Overview {project_role}",
        email=f"overview-{user_id}@test.local",
        status="active",
    )
    user.company_roles.append(UserCompanyRole(company_role=company_role, status="active"))
    user.project_members.append(
        ProjectMember(project_id=project_id, project_role=project_role, status="active")
    )
    db_session.add(user)
    await db_session.commit()
    return user_id


async def test_project_list_uses_active_memberships_and_reports_role(client, db_session):
    second = Project(id=uuid.uuid4(), name="Switchable second", status="active")
    db_session.add(second)
    db_session.add(
        ProjectMember(
            user_id=USER_CONSULTANT,
            project_id=second.id,
            project_role="coach",
            status="active",
        )
    )
    await db_session.commit()

    response = await client.get(PROJECTS, headers=_headers(USER_CONSULTANT))

    assert response.status_code == 200
    items = response.json()["items"]
    assert [(item["name"], item["project_role"]) for item in items] == [
        ("Alpha 项目", "consultant"),
        ("Switchable second", "coach"),
    ]
    assert items[0]["can_manage"] is False


@pytest.mark.parametrize("user_id", [USER_BOSS, USER_DIRECTOR, USER_ADMIN_ONLY])
async def test_company_and_admin_roles_do_not_expand_project_list(client, user_id):
    response = await client.get(PROJECTS, headers=_headers(user_id))

    assert response.status_code == 200
    assert response.json() == {"items": []}


@pytest.mark.parametrize("company_role", ["boss", "consulting_director"])
async def test_company_governance_role_with_membership_gets_only_project_role_permissions(
    client, db_session, company_role
):
    user_id = await _member_user(
        db_session,
        project_id=PROJECT_ALPHA,
        project_role="consultant",
        company_role=company_role,
    )

    project_list = await client.get(PROJECTS, headers=_headers(user_id))
    overview = await client.get(f"{PROJECTS}/{PROJECT_ALPHA}/overview", headers=_headers(user_id))

    assert [item["id"] for item in project_list.json()["items"]] == [str(PROJECT_ALPHA)]
    assert overview.status_code == 200
    assert overview.json()["project"]["project_role"] == "consultant"
    assert overview.json()["project"]["can_manage"] is False
    assert overview.json()["members"] == []
    assert overview.json()["counts"]["pending_review_count"] == 0
    assert overview.json()["counts"]["original_access_request_count"] == 0


@pytest.mark.parametrize("project_role", ["consultant", "coach"])
async def test_ordinary_members_receive_safe_read_only_overview(client, db_session, project_role):
    user_id = await _member_user(db_session, project_id=PROJECT_ALPHA, project_role=project_role)

    response = await client.get(f"{PROJECTS}/{PROJECT_ALPHA}/overview", headers=_headers(user_id))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["project"]["project_role"] == project_role
    assert body["project"]["can_manage"] is False
    assert body["capabilities"] == {
        "can_view_knowledge": True,
        "can_upload_material": True,
        "can_manage_members": False,
        "can_manage_kb": False,
        "can_confirm_assets": False,
    }
    assert body["members"] == []
    assert body["knowledge_base"] == {"configured": True, "status": "active"}
    assert str(KA_PROJECT_ALPHA_L5) in {item["asset_id"] for item in body["recent_activity"]}


async def test_project_manager_receives_governance_sections(client):
    response = await client.get(
        f"{PROJECTS}/{PROJECT_ALPHA}/overview", headers=_headers(USER_PROJECT_MANAGER)
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["project"]["can_manage"] is True
    assert body["capabilities"]["can_manage_members"] is True
    assert body["capabilities"]["can_manage_kb"] is True
    assert body["capabilities"]["can_confirm_assets"] is True
    assert body["counts"]["pending_review_count"] >= 1
    assert {member["project_role"] for member in body["members"]} >= {
        "project_manager",
        "consultant",
    }
    assert all(
        set(member) == {"user_id", "name", "project_role", "status"} for member in body["members"]
    )


@pytest.mark.parametrize("user_id", [USER_BOSS, USER_DIRECTOR, USER_ADMIN_ONLY])
async def test_nonmembers_cannot_enter_project_overview_or_knowledge(client, user_id):
    overview = await client.get(f"{PROJECTS}/{PROJECT_ALPHA}/overview", headers=_headers(user_id))
    knowledge = await client.get(
        "/api/v1/knowledge",
        params={"scope": "project", "project_id": str(PROJECT_ALPHA)},
        headers=_headers(user_id),
    )

    assert overview.status_code == 404
    assert knowledge.status_code in {403, 404}


async def test_missing_and_inaccessible_projects_are_indistinguishable(client):
    inaccessible = await client.get(
        f"{PROJECTS}/{PROJECT_BETA}/overview", headers=_headers(USER_CONSULTANT)
    )
    missing = await client.get(
        f"{PROJECTS}/{uuid.uuid4()}/overview", headers=_headers(USER_CONSULTANT)
    )

    assert inaccessible.status_code == missing.status_code == 404
    assert inaccessible.json() == missing.json()


async def test_membership_revocation_takes_effect_on_next_request(client, db_session):
    user_id = await _member_user(db_session, project_id=PROJECT_ALPHA, project_role="consultant")
    assert (
        await client.get(f"{PROJECTS}/{PROJECT_ALPHA}/overview", headers=_headers(user_id))
    ).status_code == 200

    membership = (
        await db_session.execute(
            select(ProjectMember).where(
                ProjectMember.user_id == user_id,
                ProjectMember.project_id == PROJECT_ALPHA,
            )
        )
    ).scalar_one()
    membership.status = "inactive"
    await db_session.commit()

    project_list = await client.get(PROJECTS, headers=_headers(user_id))
    overview = await client.get(f"{PROJECTS}/{PROJECT_ALPHA}/overview", headers=_headers(user_id))
    assert project_list.json() == {"items": []}
    assert overview.status_code == 404


async def test_empty_project_returns_true_zeroes(client, db_session):
    project = Project(id=uuid.uuid4(), name="Empty overview", status="active")
    db_session.add(project)
    await db_session.flush()
    user_id = await _member_user(db_session, project_id=project.id, project_role="project_manager")

    response = await client.get(f"{PROJECTS}/{project.id}/overview", headers=_headers(user_id))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["counts"] == {
        "material_count": 0,
        "asset_count": 0,
        "pending_confirmation_count": 0,
        "pending_review_count": 0,
        "original_access_request_count": 0,
    }
    assert body["knowledge_base"] == {"configured": False, "status": None}
    assert body["recent_activity"] == []


async def test_overview_response_does_not_expose_internal_or_content_fields(client):
    response = await client.get(
        f"{PROJECTS}/{PROJECT_ALPHA}/overview", headers=_headers(USER_PROJECT_MANAGER)
    )

    lowered = response.text.lower()
    for token in (
        "storage_ref",
        "source_file_ref",
        "weknora_kb_id",
        "weknora_doc_id",
        "fetch_token",
        "download_url",
        "summary",
        "email",
        "company_roles",
    ):
        assert token not in lowered
