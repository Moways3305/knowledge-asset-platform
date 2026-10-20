"""Old preview capabilities must not outlive the requester's live original access."""

import uuid
from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, MetaData, String, Table, create_engine, inspect, select
from test_preview_notifications import _entry_fetch_token, _hdr, _issue, _upload_confirm_personal

from app.models.identity import ProjectMember, User, UserCompanyRole
from app.models.knowledge import KnowledgeAsset
from app.models.original_access import AccessGrant
from app.models.preview import PreviewCredential
from app.seed.dev_seed import PROJECT_ALPHA, USER_BOSS, USER_CONSULTANT


async def _prepare(client, session, change):
    asset_id = await _upload_confirm_personal(client, content=b"synthetic preview bytes")
    asset = await session.get(KnowledgeAsset, uuid.UUID(asset_id))
    grant_id = None
    if change.startswith("grant_") or change == "classification":
        asset.scope = "company"
        asset.confidentiality_level = "L3"
        asset.owner_user_id = USER_BOSS
        await session.commit()
        requested = await client.post(
            f"/api/v1/knowledge/{asset_id}/original-access/request",
            headers=_hdr(USER_CONSULTANT),
            json={"reason": "synthetic regression"},
        )
        assert requested.status_code == 200
        request_id = requested.json()["request"]["request_id"]
        approved = await client.post(
            f"/api/v1/original-access/requests/{request_id}/approve",
            headers=_hdr(USER_BOSS),
            json={},
        )
        assert approved.status_code == 200
        grant_id = approved.json()["grant"]["grant_id"]
    elif change == "membership":
        asset.scope = "project"
        asset.project_id = PROJECT_ALPHA
        await session.commit()
    issued = await _issue(client, asset_id)
    assert issued.status_code == 200
    credential_id = issued.json()["credential_id"]
    token = await _entry_fetch_token(client, credential_id)
    return asset_id, credential_id, token, grant_id


@pytest.mark.parametrize("endpoint", ["entry", "file", "range"])
@pytest.mark.parametrize(
    "change",
    [
        "inactive",
        "role_removed",
        "role_replaced",
        "grant_revoked",
        "grant_expired",
        "membership",
        "ownership",
        "classification",
    ],
)
async def test_old_preview_rechecks_live_access(client, db_session, change, endpoint):
    asset_id, credential_id, token, grant_id = await _prepare(client, db_session, change)
    if change == "inactive":
        user = await db_session.get(User, USER_CONSULTANT)
        user.status = "inactive"
    elif change in {"role_removed", "role_replaced"}:
        role = (
            await db_session.execute(
                select(UserCompanyRole).where(
                    UserCompanyRole.user_id == USER_CONSULTANT,
                    UserCompanyRole.company_role == "consultant",
                )
            )
        ).scalar_one()
        role.status = "inactive"
        if change == "role_replaced":
            db_session.add(
                UserCompanyRole(user_id=USER_CONSULTANT, company_role="boss", status="active")
            )
    elif change == "grant_revoked":
        revoked = await client.post(
            f"/api/v1/original-access/grants/{grant_id}/revoke",
            headers=_hdr(USER_BOSS),
            json={"reason": "synthetic regression"},
        )
        assert revoked.status_code == 200
    elif change == "grant_expired":
        grant = await db_session.get(AccessGrant, uuid.UUID(grant_id))
        grant.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    elif change == "membership":
        member = (
            await db_session.execute(
                select(ProjectMember).where(
                    ProjectMember.user_id == USER_CONSULTANT,
                    ProjectMember.project_id == PROJECT_ALPHA,
                )
            )
        ).scalar_one()
        member.status = "inactive"
    elif change == "ownership":
        asset = await db_session.get(KnowledgeAsset, uuid.UUID(asset_id))
        asset.owner_user_id = USER_BOSS
    elif change == "classification":
        asset = await db_session.get(KnowledgeAsset, uuid.UUID(asset_id))
        asset.confidentiality_level = "L5"
    await db_session.commit()
    if endpoint == "entry":
        response = await client.get(
            f"/api/v1/preview/{credential_id}", headers=_hdr(USER_CONSULTANT)
        )
    else:
        response = await client.get(
            f"/api/v1/preview/{credential_id}/file",
            params={"ft": token},
            headers={"Range": "bytes=0-3"} if endpoint == "range" else {},
        )
    assert response.status_code == 403, (change, endpoint, response.status_code)
    assert "synthetic preview bytes" not in response.text


async def test_live_grant_still_serves_bytes_without_document_server_session(client, db_session):
    _, credential_id, token, _ = await _prepare(client, db_session, "grant_valid")
    response = await client.get(f"/api/v1/preview/{credential_id}/file", params={"ft": token})
    assert response.status_code == 200
    assert response.content == b"synthetic preview bytes"
    assert response.headers["cache-control"] == "no-store"
    credential = await db_session.get(PreviewCredential, uuid.UUID(credential_id))
    assert getattr(credential, "requester_company_role", None) == "consultant"


@pytest.mark.parametrize("endpoint", ["entry", "file"])
@pytest.mark.parametrize("role", [None, "admin", "unrecognized"])
async def test_legacy_credential_requires_reissue_not_default_role_guess(
    client, db_session, endpoint, role
):
    _, credential_id, token, _ = await _prepare(client, db_session, "personal")
    credential = await db_session.get(PreviewCredential, uuid.UUID(credential_id))
    credential.requester_company_role = role
    await db_session.commit()
    if endpoint == "entry":
        response = await client.get(
            f"/api/v1/preview/{credential_id}", headers=_hdr(USER_CONSULTANT)
        )
    else:
        response = await client.get(f"/api/v1/preview/{credential_id}/file", params={"ft": token})
    assert response.status_code == 403


def test_preview_role_migration_preserves_legacy_rows_without_guessing_roles():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0080_preview_requester_role.py"
    spec = spec_from_file_location("preview_role_migration", path)
    assert spec and spec.loader
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    table = Table("preview_credentials", metadata, Column("id", String, primary_key=True))
    with engine.begin() as connection:
        metadata.create_all(connection)
        connection.execute(table.insert().values(id="legacy"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            upgraded = Table("preview_credentials", MetaData(), autoload_with=connection)
            row = connection.execute(select(upgraded)).mappings().one()
            assert dict(row) == {"id": "legacy", "requester_company_role": None}
            migration.downgrade()
        assert [
            column["name"] for column in inspect(connection).get_columns("preview_credentials")
        ] == ["id"]
        assert connection.execute(select(table.c.id)).scalar_one() == "legacy"
    engine.dispose()
