"""预览凭证 API 测试（IMPLEMENT-07 最小闭环）。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.knowledge import KnowledgeAsset
from app.models.preview import PreviewCredential
from app.seed.dev_seed import (
    KA_COMPANY_ARCHIVED,
    KA_COMPANY_L4,
    KA_COMPANY_L5,
    KA_PERSONAL,
    KA_PROJECT_ALPHA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
)


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


def _preview_url(asset_id):
    return f"/api/v1/knowledge/{asset_id}/preview"


_LEAK_TOKENS = ["storage_ref", "source_file_ref", "bucket", "token_hash", "s3://", "oss://"]


def _assert_no_leak(text: str):
    for t in _LEAK_TOKENS:
        assert t not in text, f"响应不应泄露 {t}"


async def test_personal_owner_preview_full_no_leak(client):
    """个人知识 owner 申请 preview 成功，preview_type=full，无敏感字段泄露。"""
    resp = await client.post(_preview_url(KA_PERSONAL), headers=_hdr(USER_CONSULTANT))
    assert resp.status_code == 200
    body = resp.json()
    assert body["preview_type"] == "full"
    assert body["credential_fingerprint"]
    assert body["preview_entry_url"].startswith("/api/v1/preview/")
    _assert_no_leak(resp.text)


async def test_project_member_preview_controlled_entry(client):
    """项目成员对项目资产申请 preview 成功，返回平台受控相对入口。"""
    resp = await client.post(_preview_url(KA_PROJECT_ALPHA), headers=_hdr(USER_CONSULTANT))
    assert resp.status_code == 200
    assert resp.json()["preview_entry_url"].startswith("/api/v1/preview/")


async def test_admin_preview_403(client):
    """纯 admin 申请 preview 返回 403 admin_business_permission_denied。"""
    resp = await client.post(_preview_url(KA_PERSONAL), headers=_hdr(USER_ADMIN_ONLY))
    assert resp.status_code == 403
    assert resp.json()["detail"]["denied_reason"] == "admin_business_permission_denied"


async def test_no_original_returns_original_requires_request(client, db_session):
    """有 summary 无 original（company L4 的 consultant）→ 403 original_requires_request，不创建凭证。"""
    before = len((await db_session.execute(select(PreviewCredential))).scalars().all())
    resp = await client.post(_preview_url(KA_COMPANY_L4), headers=_hdr(USER_CONSULTANT))
    assert resp.status_code == 403
    assert resp.json()["detail"]["denied_reason"] == "original_requires_request"
    after = len((await db_session.execute(select(PreviewCredential))).scalars().all())
    assert after == before


async def test_l5_not_discoverable_for_consultant(client):
    """普通用户申请 L5 preview 不泄露存在（404）。"""
    resp = await client.post(_preview_url(KA_COMPANY_L5), headers=_hdr(USER_CONSULTANT))
    assert resp.status_code == 404


async def test_l5_boss_preview_full(client):
    """boss 申请 L5 preview 成功，preview_type=full。"""
    resp = await client.post(_preview_url(KA_COMPANY_L5), headers=_hdr(USER_BOSS))
    assert resp.status_code == 200
    assert resp.json()["preview_type"] == "full"


async def test_archived_preview_rejected_no_credential(client, db_session):
    """archived 资产申请 preview 被拒（403 asset_not_active），不创建凭证。"""
    before = len((await db_session.execute(select(PreviewCredential))).scalars().all())
    resp = await client.post(_preview_url(KA_COMPANY_ARCHIVED), headers=_hdr(USER_BOSS))
    assert resp.status_code == 403
    assert resp.json()["detail"]["denied_reason"] == "asset_not_active"
    after = len((await db_session.execute(select(PreviewCredential))).scalars().all())
    assert after == before


async def test_preview_entry_active_returns_placeholder(client, db_session):
    """对 active credential 访问入口返回占位 metadata，并更新 used_at / last_used_at。"""
    cred_id = (await client.post(_preview_url(KA_PERSONAL), headers=_hdr(USER_CONSULTANT))).json()[
        "credential_id"
    ]
    resp = await client.get(f"/api/v1/preview/{cred_id}", headers=_hdr(USER_CONSULTANT))
    assert resp.status_code == 200
    body = resp.json()
    assert body["preview_type"] == "full"
    assert "message" in body
    _assert_no_leak(resp.text)
    cred = await db_session.get(PreviewCredential, uuid.UUID(cred_id))
    # 注意：db_session 与请求共享同一内存库
    assert cred is not None and cred.used_at is not None and cred.last_used_at is not None


async def test_preview_invalid_version_id_404_no_credential(client, db_session):
    """传入随机 version_id → 404 version_not_found，不创建凭证。"""
    before = len((await db_session.execute(select(PreviewCredential))).scalars().all())
    resp = await client.post(
        _preview_url(KA_PERSONAL),
        headers=_hdr(USER_CONSULTANT),
        json={"version_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["denied_reason"] == "version_not_found"
    after = len((await db_session.execute(select(PreviewCredential))).scalars().all())
    assert after == before


async def test_preview_other_asset_version_404(client, db_session):
    """传入属于其他资产的 version_id → 404 version_not_found。"""
    other = await db_session.get(KnowledgeAsset, KA_PROJECT_ALPHA)
    other_version_id = other.current_version_id
    assert other_version_id is not None
    resp = await client.post(
        _preview_url(KA_PERSONAL),
        headers=_hdr(USER_CONSULTANT),
        json={"version_id": str(other_version_id)},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["denied_reason"] == "version_not_found"


async def test_preview_entry_admin_403(client):
    """纯 admin 访问已有 preview entry 返回 403 admin_business_permission_denied。"""
    cred_id = (await client.post(_preview_url(KA_PERSONAL), headers=_hdr(USER_CONSULTANT))).json()[
        "credential_id"
    ]
    resp = await client.get(f"/api/v1/preview/{cred_id}", headers=_hdr(USER_ADMIN_ONLY))
    assert resp.status_code == 403
    assert resp.json()["detail"]["denied_reason"] == "admin_business_permission_denied"


async def test_preview_entry_expired_returns_403(client, db_session):
    """expired credential 访问返回 403 preview_credential_expired，状态更新为 expired。"""
    cred = PreviewCredential(
        id=uuid.uuid4(),
        target_asset_id=KA_PERSONAL,
        requester_user_id=USER_CONSULTANT,
        preview_type="full",
        credential_status="active",
        token_hash="x",
        credential_fingerprint="x",
        preview_entry_url="/api/v1/preview/x",
        issued_at=datetime.now(timezone.utc) - timedelta(hours=1),
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db_session.add(cred)
    await db_session.commit()
    resp = await client.get(f"/api/v1/preview/{cred.id}", headers=_hdr(USER_CONSULTANT))
    assert resp.status_code == 403
    assert resp.json()["detail"]["denied_reason"] == "preview_credential_expired"
    refreshed = await db_session.get(PreviewCredential, cred.id)
    await db_session.refresh(refreshed)
    assert refreshed.credential_status == "expired"
