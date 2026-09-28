"""Generic recovery matrix: assignments may change, authentication may not be bypassed."""

import uuid
from itertools import permutations

import pytest
from fastapi import HTTPException, Response

from app.api import auth
from app.models.identity import User, UserCompanyRole
from app.services import work_identity as identity

ROLES = ("admin", "boss", "consulting_director", "consultant")


@pytest.mark.parametrize("role", ROLES)
def test_existing_selection_is_preserved_when_roles_are_added(role):
    user = user_with_roles([role])
    cookie = identity.issue_role_cookie_value(session_token="session", user=user, role=role)
    user.company_roles = [UserCompanyRole(company_role=r, status="active") for r in ROLES]
    assert (
        identity.resolve_active_role(user=user, session_token="session", cookie_value=cookie)
        == role
    )


def user_with_roles(roles):
    user = User(id=uuid.uuid4(), name="Test", email="test@example.test", status="active")
    user.company_roles = [UserCompanyRole(company_role=r, status="active") for r in roles]
    user.project_memberships = []
    return user


async def call_me(monkeypatch, user, cookie):
    async def resolve(*args, **kwargs):
        return user

    monkeypatch.setattr(auth.session_service, "resolve_current_user", resolve)
    response = Response()
    result = await auth.auth_me(
        response=response,
        x_dev_user_id=None,
        kap_session="session",
        kap_active_company_role=cookie,
        session=None,
    )
    return result, response


@pytest.mark.parametrize("old,new", list(permutations(ROLES, 2)))
async def test_single_remaining_assignment_recovers_for_every_role(monkeypatch, old, new):
    user = user_with_roles([old])
    cookie = identity.issue_role_cookie_value(session_token="session", user=user, role=old)
    user.company_roles = [UserCompanyRole(company_role=new, status="active")]
    result, response = await call_me(monkeypatch, user, cookie)
    assert result.active_company_role == new
    assert "kap_active_company_role=" in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "no-store"
    # Ordinary business endpoints must reject stale credentials, not replay work.
    with pytest.raises(identity.StaleActiveRoleCookie):
        identity.resolve_active_role(user=user, session_token="session", cookie_value=cookie)


@pytest.mark.parametrize("remaining", [[], ["admin", "boss"]])
async def test_recovery_never_picks_a_privileged_default(monkeypatch, remaining):
    user = user_with_roles(["consultant"])
    cookie = identity.issue_role_cookie_value(session_token="session", user=user, role="consultant")
    user.company_roles = [UserCompanyRole(company_role=r, status="active") for r in remaining]
    with pytest.raises(HTTPException) as error:
        await call_me(monkeypatch, user, cookie)
    assert error.value.status_code == 403
    assert error.value.detail["available_roles"] == remaining


@pytest.mark.parametrize("token,cookie", [("session", "consultant.forged"), ("other", None)])
async def test_untrusted_cookie_cannot_use_recovery(monkeypatch, token, cookie):
    user = user_with_roles(["consultant"])
    cookie = cookie or identity.issue_role_cookie_value(
        session_token=token, user=user, role="consultant"
    )
    user.company_roles = [UserCompanyRole(company_role="boss", status="active")]
    with pytest.raises(HTTPException) as error:
        await call_me(monkeypatch, user, cookie)
    assert error.value.detail["denied_reason"] == "active_company_role_cookie_invalid"


async def test_live_session_explicit_selection_after_revocation(client, db_session):
    from sqlalchemy import update

    from app.seed.dev_seed import USER_CONSULTANT

    await client.post("/api/v1/auth/login", json={"email": "consultant.a@dev.local"})
    await db_session.execute(
        update(UserCompanyRole)
        .where(UserCompanyRole.user_id == USER_CONSULTANT)
        .values(status="inactive")
    )
    db_session.add_all(
        [
            UserCompanyRole(user_id=USER_CONSULTANT, company_role=r, status="active")
            for r in ("boss", "admin")
        ]
    )
    await db_session.commit()
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 403
    assert me.json()["detail"]["available_roles"] == ["admin", "boss"]
    assert "set-cookie" not in me.headers
    assert (await client.get("/api/v1/knowledge")).status_code == 403
    csrf = (await client.get("/api/v1/auth/csrf")).json()["csrf_token"]
    result = await client.post(
        "/api/v1/auth/active-company-role",
        json={"company_role": "boss"},
        headers={"X-CSRF-Token": csrf},
    )
    assert result.status_code == 200, result.text
    assert (await client.get("/api/v1/auth/me")).json()["active_company_role"] == "boss"
