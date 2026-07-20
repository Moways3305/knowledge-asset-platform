"""Company knowledge-base lifecycle and first-Boss bootstrap boundaries."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select

from app.commands import bootstrap_boss as bootstrap_command
from app.main import app
from app.models.audit import AuditEvent
from app.models.identity import UserCompanyRole
from app.models.weknora import WeknoraKbMapping
from app.schemas.enums import CompanyRole, RoleStatus
from app.seed.dev_seed import USER_ADMIN_ONLY, USER_BOSS, USER_CONSULTANT, USER_DIRECTOR
from app.services.governance_bootstrap import BossBootstrapResult, bootstrap_first_boss
from app.services.weknora_client import WeKnoraError, get_weknora_client

COMPANY_KB = "/api/v1/company/knowledge-base"
_SECRET_KB_ID = "SECRET-WEKNORA-KB-ID"
_LEAK_TOKENS = (_SECRET_KB_ID, "embedding-model-secret", "api_key", "storage_ref")


def _hdr(user_id: uuid.UUID) -> dict[str, str]:
    return {"X-Dev-User-Id": str(user_id)}


class _FakeWeKnora:
    def __init__(self, *, fail_initialize: bool = False) -> None:
        self.fail_initialize = fail_initialize
        self.created = 0
        self.initialized = 0

    async def create_kb(self, **_kwargs) -> str:
        self.created += 1
        return _SECRET_KB_ID

    async def initialize_kb(self, _kb_id: str, **_kwargs) -> None:
        self.initialized += 1
        if self.fail_initialize:
            raise WeKnoraError("weknora_init_failed", "unsafe upstream detail")


async def _remove_company_mapping(db_session) -> None:
    await db_session.execute(delete(WeknoraKbMapping).where(WeknoraKbMapping.scope == "company"))
    await db_session.commit()


def _assert_safe(text: str) -> None:
    for token in _LEAK_TOKENS:
        assert token not in text


async def test_company_kb_governance_only_and_denial_is_audited(client, db_session):
    for user_id in (USER_ADMIN_ONLY, USER_CONSULTANT):
        response = await client.post(COMPANY_KB, headers=_hdr(user_id), json={})
        assert response.status_code == 403
        _assert_safe(response.text)

    events = list(
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action == "config.company_kb_created",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(events) >= 2
    for event in events[-2:]:
        blob = str(event.extra)
        assert "target_user_id" not in blob
        assert str(USER_ADMIN_ONLY) not in blob
        assert str(USER_CONSULTANT) not in blob


async def test_company_kb_create_is_real_safe_and_idempotent(client, db_session, monkeypatch):
    from conftest import patch_default_model

    await _remove_company_mapping(db_session)
    patch_default_model(monkeypatch, embedding="embedding-model-secret")
    fake = _FakeWeKnora()
    app.dependency_overrides[get_weknora_client] = lambda: fake
    try:
        first = await client.post(
            COMPANY_KB, headers=_hdr(USER_BOSS), json={"display_name": "公司知识库"}
        )
        second = await client.post(
            COMPANY_KB, headers=_hdr(USER_DIRECTOR), json={"display_name": "不会覆盖"}
        )
        assert first.status_code == second.status_code == 200
        assert first.json()["status"] == "active"
        assert first.json()["available"] is True
        assert second.json()["display_name"] == "公司知识库"
        assert fake.created == fake.initialized == 1
        _assert_safe(first.text + second.text)
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_company_kb_init_failure_is_not_available(client, db_session, monkeypatch):
    from conftest import patch_default_model

    await _remove_company_mapping(db_session)
    patch_default_model(monkeypatch, embedding="embedding-model-secret")
    fake = _FakeWeKnora(fail_initialize=True)
    app.dependency_overrides[get_weknora_client] = lambda: fake
    try:
        response = await client.post(COMPANY_KB, headers=_hdr(USER_BOSS), json={})
        assert response.status_code == 200
        assert response.json()["status"] == "init_failed"
        assert response.json()["available"] is False
        _assert_safe(response.text)
        mapping = (
            await db_session.execute(
                select(WeknoraKbMapping).where(WeknoraKbMapping.scope == "company")
            )
        ).scalar_one()
        assert mapping.status == "init_failed"
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_bootstrap_runs_once_without_identity_in_audit(db_session):
    boss_role = (
        await db_session.execute(
            select(UserCompanyRole).where(
                UserCompanyRole.user_id == USER_BOSS,
                UserCompanyRole.company_role == CompanyRole.boss.value,
            )
        )
    ).scalar_one()
    boss_role.status = RoleStatus.inactive.value
    await db_session.commit()

    created = await bootstrap_first_boss(
        db_session, target_user_id=USER_CONSULTANT, trace_id="bootstrap-test"
    )
    repeated = await bootstrap_first_boss(
        db_session, target_user_id=USER_DIRECTOR, trace_id="bootstrap-repeat"
    )
    assert created is BossBootstrapResult.created
    assert repeated is BossBootstrapResult.already_configured

    event = (
        await db_session.execute(
            select(AuditEvent).where(AuditEvent.action == "governance.boss_bootstrapped")
        )
    ).scalar_one()
    assert event.actor_user_id is None
    blob = str(event.extra)
    assert str(USER_CONSULTANT) not in blob
    assert "email" not in blob


async def test_bootstrap_is_safe_noop_when_multiple_active_bosses_exist(db_session):
    db_session.add(
        UserCompanyRole(
            user_id=USER_DIRECTOR,
            company_role=CompanyRole.boss.value,
            status=RoleStatus.active.value,
        )
    )
    await db_session.commit()

    result = await bootstrap_first_boss(
        db_session, target_user_id=USER_CONSULTANT, trace_id="bootstrap-multiple-bosses"
    )

    assert result is BossBootstrapResult.already_configured
    target_role = (
        await db_session.execute(
            select(UserCompanyRole).where(
                UserCompanyRole.user_id == USER_CONSULTANT,
                UserCompanyRole.company_role == CompanyRole.boss.value,
            )
        )
    ).scalar_one_or_none()
    assert target_role is None


def test_bootstrap_has_no_http_route():
    assert all("bootstrap" not in path for path in app.openapi()["paths"])


def test_bootstrap_command_output_never_echoes_target(monkeypatch, capsys):
    target = uuid.uuid4()

    async def _fake_run(_target_user_id):
        return BossBootstrapResult.already_configured

    monkeypatch.setenv("KAP_BOOTSTRAP_BOSS_TARGET_USER_ID", str(target))
    monkeypatch.setattr(bootstrap_command, "_run", _fake_run)
    assert bootstrap_command.main([]) == 3
    output = capsys.readouterr().out
    assert output.strip() == BossBootstrapResult.already_configured.value
    assert str(target) not in output


def test_bootstrap_command_accepts_cli_target_and_prefers_it(monkeypatch, capsys):
    target = uuid.uuid4()
    captured = None

    async def _fake_run(target_user_id):
        nonlocal captured
        captured = target_user_id
        return BossBootstrapResult.created

    monkeypatch.setenv("KAP_BOOTSTRAP_BOSS_TARGET_USER_ID", str(uuid.uuid4()))
    monkeypatch.setattr(bootstrap_command, "_run", _fake_run)

    assert bootstrap_command.main(["--user-id", str(target)]) == 0
    assert captured == target
    output = capsys.readouterr().out
    assert output.strip() == BossBootstrapResult.created.value
    assert str(target) not in output


def test_bootstrap_command_rejects_invalid_cli_target_without_database_access(monkeypatch, capsys):
    async def _unexpected_run(_target_user_id):
        raise AssertionError("invalid target must not access the database")

    monkeypatch.setenv("KAP_BOOTSTRAP_BOSS_TARGET_USER_ID", str(uuid.uuid4()))
    monkeypatch.setattr(bootstrap_command, "_run", _unexpected_run)

    assert bootstrap_command.main(["--user-id", "not-a-uuid"]) == 2
    assert capsys.readouterr().out.strip() == "boss_bootstrap_invalid_target"
