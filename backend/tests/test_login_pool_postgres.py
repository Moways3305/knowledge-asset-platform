"""Password computation must not reserve the only business DB connection."""

import asyncio
import uuid

import httpx
import pytest
import test_search_pool_postgres as pool_tests
from sqlalchemy import func, select, text, update

from app.db.session import get_db
from app.main import create_app
from app.models.audit import AuditEvent
from app.models.auth_security import AuthLoginAttempt
from app.models.auth_session import UserSession
from app.models.identity import ProjectMember, User, UserCompanyRole
from app.seed.dev_seed import DEV_PASSWORD, USER_CONSULTANT
from app.services import audit, passwords

single_connection_db = pool_tests.single_connection_db


def login_app(sessions):
    async def database():
        async with sessions() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = database
    return app


@pytest.mark.parametrize("known", [True, False])
@pytest.mark.parametrize("cancel", [False, True])
async def test_login_releases_pool_during_hash(single_connection_db, monkeypatch, known, cancel):
    sessions = single_connection_db
    entered, release = asyncio.Event(), asyncio.Event()
    method = "verify_password_async" if known else "dummy_verify_async"
    original = getattr(passwords, method)

    async def held(*args):
        entered.set()
        await release.wait()
        return await original(*args)

    monkeypatch.setattr(passwords, method, held)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=login_app(sessions)), base_url="https://testserver"
    ) as client:
        token = (await client.get("/api/v1/auth/csrf")).json()["csrf_token"]
        pending = asyncio.create_task(
            client.post(
                "/api/v1/auth/login",
                headers={"X-CSRF-Token": token},
                json={
                    "email": "consultant.a@dev.local" if known else "missing@example.invalid",
                    "password": DEV_PASSWORD,
                },
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), 3)
            async with sessions() as other:
                assert await asyncio.wait_for(other.scalar(text("SELECT 1")), 0.5) == 1
                for model in (UserSession, AuthLoginAttempt):
                    assert await other.scalar(select(func.count()).select_from(model)) == 0
            if cancel:
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            else:
                release.set()
                response = await asyncio.wait_for(pending, 3)
                assert response.status_code == (200 if known else 401)
                assert ("kap_session=" in response.headers.get("set-cookie", "")) == known
        finally:
            release.set()
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(UserSession)) == int(
            known and not cancel
        )
        assert await session.scalar(select(func.count()).select_from(AuthLoginAttempt)) == int(
            not cancel
        )
        assert await session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action.in_(["login.success", "login.failed"]))
        ) == int(not cancel)


@pytest.mark.parametrize("change", ["disable", "reset_password", "role", "membership"])
async def test_login_refreshes_identity_after_hash(single_connection_db, monkeypatch, change):
    sessions = single_connection_db
    entered, release = asyncio.Event(), asyncio.Event()
    original = passwords.verify_password_async

    async def held(*args):
        entered.set()
        await release.wait()
        return await original(*args)

    monkeypatch.setattr(passwords, "verify_password_async", held)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=login_app(sessions)), base_url="https://testserver"
    ) as client:
        pending = asyncio.create_task(
            client.post(
                "/api/v1/auth/login",
                json={"email": "consultant.a@dev.local", "password": DEV_PASSWORD},
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), 3)
            async with sessions() as writer:
                if change in {"disable", "reset_password"}:
                    user = await writer.get(User, USER_CONSULTANT)
                    if change == "disable":
                        user.status = "inactive"
                    else:
                        user.password_hash = passwords.hash_password("changed-synthetic-password")
                else:
                    model = UserCompanyRole if change == "role" else ProjectMember
                    await writer.execute(
                        update(model)
                        .where(model.user_id == USER_CONSULTANT)
                        .values(status="inactive")
                    )
                await writer.commit()
            release.set()
            response = await asyncio.wait_for(pending, 3)
            if change in {"disable", "reset_password"}:
                assert response.status_code == 401
                assert "kap_session=" not in response.headers.get("set-cookie", "")
            else:
                assert response.status_code == 200
                assert (
                    response.json()["company_roles" if change == "role" else "project_memberships"]
                    == []
                )
        finally:
            release.set()
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
    async with sessions() as check:
        attempts = list(await check.scalars(select(AuthLoginAttempt)))
        assert len(attempts) == 1
        success = change in {"role", "membership"}
        assert attempts[0].result == ("success" if success else "failed")
        assert await check.scalar(select(func.count()).select_from(UserSession)) == int(success)


@pytest.mark.parametrize("cancel", [False, True])
async def test_login_final_write_is_atomic(single_connection_db, monkeypatch, cancel):
    sessions = single_connection_db
    entered = asyncio.Event()
    original = audit.record_event

    async def fail(session, **kwargs):
        result = await original(session, **kwargs)
        if kwargs.get("action") == "login.success":
            await session.flush()
            entered.set()
            if cancel:
                await asyncio.Event().wait()
            raise RuntimeError("synthetic audit failure")
        return result

    monkeypatch.setattr(audit, "record_event", fail)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=login_app(sessions)), base_url="https://testserver"
    ) as client:
        pending = asyncio.create_task(
            client.post(
                "/api/v1/auth/login",
                json={"email": "consultant.a@dev.local", "password": DEV_PASSWORD},
            )
        )

        try:
            await asyncio.wait_for(entered.wait(), 3)
            if cancel:
                pending.cancel()
            with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
                await pending
        finally:
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
    async with sessions() as check:
        assert await check.scalar(text("SELECT 1")) == 1
        for model in (UserSession, AuthLoginAttempt):
            assert await check.scalar(select(func.count()).select_from(model)) == 0
        assert (
            await check.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "login.success")
            )
            == 0
        )


@pytest.mark.parametrize("correct", [True, False])
async def test_deleted_user_during_hash_has_no_stale_attempt_owner(
    single_connection_db, monkeypatch, correct
):
    sessions = single_connection_db
    user_id = uuid.uuid4()
    async with sessions() as session:
        session.add(
            User(
                id=user_id,
                email="deleted@example.invalid",
                name="Synthetic",
                password_hash=passwords.hash_password(DEV_PASSWORD),
            )
        )
        await session.commit()
    entered, release = asyncio.Event(), asyncio.Event()
    original = passwords.verify_password_async

    async def held(*args):
        entered.set()
        await release.wait()
        return await original(*args)

    monkeypatch.setattr(passwords, "verify_password_async", held)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=login_app(sessions)), base_url="https://testserver"
    ) as client:
        pending = asyncio.create_task(
            client.post(
                "/api/v1/auth/login",
                json={
                    "email": "deleted@example.invalid",
                    "password": DEV_PASSWORD if correct else "incorrect",
                },
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), 3)
            async with sessions() as writer:
                user = await writer.get(User, user_id)
                await writer.delete(user)
                await writer.commit()
            release.set()
            response = await asyncio.wait_for(pending, 3)
            assert response.status_code == 401
            assert "kap_session=" not in response.headers.get("set-cookie", "")
        finally:
            release.set()
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
    async with sessions() as check:
        attempts = list(await check.scalars(select(AuthLoginAttempt)))
        assert len(attempts) == 1 and attempts[0].user_id is None
        assert await check.scalar(select(func.count()).select_from(UserSession)) == 0
