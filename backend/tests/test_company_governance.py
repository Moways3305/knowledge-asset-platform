"""Company knowledge-base lifecycle and first-Boss bootstrap boundaries."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select

from app.commands import bootstrap_boss as bootstrap_command
from app.main import app
from app.models.audit import AuditEvent
from app.models.identity import UserCompanyRole
from app.models.knowledge import KnowledgeAsset
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
        self.deleted_kbs: list[str] = []

    async def create_kb(self, **_kwargs) -> str:
        self.created += 1
        return _SECRET_KB_ID

    async def initialize_kb(self, _kb_id: str, **_kwargs) -> None:
        self.initialized += 1
        if self.fail_initialize:
            raise WeKnoraError("weknora_init_failed", "unsafe upstream detail")

    async def get_kb(self, kb_id, *, trace_id=None):
        return {
            "summary_model_id": "test-chat",
            "embedding_model_id": "test-embed",
            "chunking_config": {},
            "vlm_config": {},
            "asr_config": {},
            "storage_provider_config": {},
            "extract_config": {},
            "question_generation_config": {},
        }

    async def update_initialization_config(self, kb_id, *, config, trace_id=None):
        self.initialized += 1
        if self.fail_initialize:
            raise WeKnoraError("weknora_init_failed", "unsafe upstream detail")
        return {"success": True}

    async def delete_kb(self, kb_id: str, *, trace_id: str | None = None) -> None:
        self.deleted_kbs.append(kb_id)


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


async def _ensure_company_kb_active(client, db_session, monkeypatch, fake) -> WeknoraKbMapping:
    """复用：创建一个 active 公司库映射并返回，供删除用例使用。"""
    from conftest import patch_default_model

    await _remove_company_mapping(db_session)
    patch_default_model(monkeypatch, embedding="embedding-model-secret")
    app.dependency_overrides[get_weknora_client] = lambda: fake
    resp = await client.post(COMPANY_KB, headers=_hdr(USER_BOSS), json={})
    assert resp.status_code == 200
    assert resp.json()["available"] is True
    mapping = (
        await db_session.execute(
            select(WeknoraKbMapping).where(WeknoraKbMapping.scope == "company")
        )
    ).scalar_one()
    return mapping


async def _clear_company_assets(db_session) -> None:
    """硬删除所有 company scope 资产（dev seed 预置 + 测试新增），让删除前置闸放行。"""
    await db_session.execute(delete(KnowledgeAsset).where(KnowledgeAsset.scope == "company"))
    await db_session.commit()


async def test_company_kb_delete_rejects_non_boss(client, db_session, monkeypatch):
    fake = _FakeWeKnora()
    try:
        await _ensure_company_kb_active(client, db_session, monkeypatch, fake)
        for user_id in (USER_DIRECTOR, USER_ADMIN_ONLY, USER_CONSULTANT):
            resp = await client.delete(COMPANY_KB, headers=_hdr(user_id))
            assert resp.status_code == 403
            assert resp.json()["detail"]["denied_reason"] == "company_kb_delete_governance_only"
            _assert_safe(resp.text)
        # 未删除：底座 delete_kb 未被调用。
        assert fake.deleted_kbs == []
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_company_kb_delete_blocked_when_company_assets_exist(client, db_session, monkeypatch):
    fake = _FakeWeKnora()
    try:
        await _ensure_company_kb_active(client, db_session, monkeypatch, fake)
        await _clear_company_assets(db_session)
        # 添加 1 个公司资产使前置闸触发。
        db_session.add(
            KnowledgeAsset(
                title="公司资产",
                scope="company",
                zone="asset",
                asset_type="methodology",
                owner_user_id=USER_BOSS,
                project_id=None,
                visibility="project_only",
                confidentiality_level="L2",
                ai_access_level="A1",
                asset_status="active",
            )
        )
        await db_session.commit()

        resp = await client.delete(COMPANY_KB, headers=_hdr(USER_BOSS))
        assert resp.status_code == 409
        assert resp.json()["detail"]["denied_reason"] == "company_kb_not_empty"
        assert "1 个公司资产" in resp.json()["detail"]["message"]
        _assert_safe(resp.text)
        # 底座未删除。
        assert fake.deleted_kbs == []
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_company_kb_delete_by_boss_removes_mapping_and_calls_weknora(
    client, db_session, monkeypatch
):
    fake = _FakeWeKnora()
    try:
        mapping = await _ensure_company_kb_active(client, db_session, monkeypatch, fake)
        kb_id = mapping.weknora_kb_id
        # 清空 dev seed 预置的公司资产，让前置闸放行。
        await _clear_company_assets(db_session)

        resp = await client.delete(COMPANY_KB, headers=_hdr(USER_BOSS))
        assert resp.status_code == 204
        assert resp.content == b""

        # 底座被调用删除整库。
        assert fake.deleted_kbs == [kb_id]
        # 映射行被删除。
        remaining = (
            await db_session.execute(
                select(WeknoraKbMapping).where(WeknoraKbMapping.scope == "company")
            )
        ).scalar_one_or_none()
        assert remaining is None

        events = list(
            (
                await db_session.execute(
                    select(AuditEvent).where(AuditEvent.action == "config.company_kb_deleted")
                )
            )
            .scalars()
            .all()
        )
        assert len(events) >= 1
        assert events[-1].actor_user_id == USER_BOSS
        _assert_safe(str(events[-1].extra))
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_company_kb_delete_when_weknora_fails_is_audited_as_exception(
    client, db_session, monkeypatch
):
    class _FailDeleteWeKnora(_FakeWeKnora):
        async def delete_kb(self, kb_id, *, trace_id=None):
            raise WeKnoraError("weknora_delete_failed", "底座删除失败")

    fake = _FailDeleteWeKnora()
    try:
        await _ensure_company_kb_active(client, db_session, monkeypatch, fake)
        await _clear_company_assets(db_session)
        resp = await client.delete(COMPANY_KB, headers=_hdr(USER_BOSS))
        assert resp.status_code == 503
        assert resp.json()["detail"]["denied_reason"] == "company_kb_unavailable"
        _assert_safe(resp.text)
        events = list(
            (
                await db_session.execute(
                    select(AuditEvent).where(AuditEvent.action == "config.company_kb_deleted")
                )
            )
            .scalars()
            .all()
        )
        assert len(events) >= 1
        assert str(events[-1].extra).find("unavailable") >= 0
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_company_kb_delete_returns_404_when_not_created(client, db_session):
    await _remove_company_mapping(db_session)
    resp = await client.delete(COMPANY_KB, headers=_hdr(USER_BOSS))
    assert resp.status_code == 404
    assert resp.json()["detail"]["denied_reason"] == "company_kb_not_found"


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
