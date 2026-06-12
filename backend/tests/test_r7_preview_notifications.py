"""R7 ONLYOFFICE 真预览 + WeCom 真通知测试（全 fake，不打网络）。

覆盖：
- 预览签发仍走集中权限 + 仅申请人可用；纯 admin 不可签发。
- 预览入口返回真实 ONLYOFFICE 只读配置（替代占位）；配置/取件 URL 无任何内部引用泄露。
- 受控取件端点：错/过期/撤销 token 拒绝；校验通过经平台存储返回字节。
- 未配置 / 不支持类型 → 安全说明，不泄露内部。
- WeCom 通知派发：绑定 wecom_user_id → sent；缺绑定/非 active/上游失败 → 安全失败；
  已 sent 不重复下发；通知内容值级脱敏。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

import app.services.onlyoffice as oo_mod
import app.services.preview as pv_mod
from app.models.audit import AuditEvent
from app.models.identity import User
from app.models.preview import PreviewCredential
from app.seed.dev_seed import USER_ADMIN_ONLY, USER_BOSS, USER_CONSULTANT
from app.services import alert as alert_service
from app.services import wecom_notification
from app.services.wecom_client import WeComError

UPLOAD = "/api/v1/ingest/upload"


def _hdr(user_id, trace=None):
    h = {"X-Dev-User-Id": str(user_id)}
    if trace:
        h["X-Trace-Id"] = trace
    return h


_PREVIEW_LEAK = [
    "storage_ref", "source_file_ref", "internal://", "s3://", "oss://",
    "weknora", "kb_id", "doc_id", "jwt_secret", "onlyoffice_jwt",
]


def _assert_no_leak(text):
    for t in _PREVIEW_LEAK:
        assert t not in text, f"响应不应泄露 {t}"


def _enable_onlyoffice(monkeypatch):
    monkeypatch.setattr(oo_mod, "onlyoffice_enabled", lambda: True)
    monkeypatch.setattr(pv_mod, "onlyoffice_enabled", lambda: True)


async def _upload_confirm_personal(client, *, name="doc.txt", content=b"R7 preview content body.", mime="text/plain"):
    """Path B 上传 + 确认为个人资产（consultant 对本人个人库有 original）。返回 asset_id。"""
    up = await client.post(UPLOAD, headers=_hdr(USER_CONSULTANT), files={"file": (name, content, mime)})
    task_id = up.json()["ingest_task_id"]
    conf = await client.post(
        f"/api/v1/ingest/{task_id}/confirm", headers=_hdr(USER_CONSULTANT),
        json={"title": "R7 资产", "summary": "摘要", "tags": ["t"], "target_scope": "personal",
              "asset_type": "methodology", "confidentiality_level": "L2", "ai_access_level": "A2"},
    )
    assert conf.status_code == 200, conf.text
    return conf.json()["result_asset_id"]


async def _issue(client, asset_id, user=USER_CONSULTANT):
    return await client.post(f"/api/v1/knowledge/{asset_id}/preview", headers=_hdr(user), json={})


# ---------------- 预览签发 / 权限 ----------------
async def test_admin_cannot_issue_preview(client):
    asset_id = await _upload_confirm_personal(client)
    r = await _issue(client, asset_id, user=USER_ADMIN_ONLY)
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "admin_business_permission_denied"


async def test_preview_entry_returns_onlyoffice_config(client, monkeypatch):
    _enable_onlyoffice(monkeypatch)
    asset_id = await _upload_confirm_personal(client)
    cred_id = (await _issue(client, asset_id)).json()["credential_id"]
    entry = await client.get(f"/api/v1/preview/{cred_id}", headers=_hdr(USER_CONSULTANT))
    assert entry.status_code == 200, entry.text
    body = entry.json()
    assert body["onlyoffice_config"] is not None
    cfg = body["onlyoffice_config"]
    assert cfg["editorConfig"]["mode"] == "view"
    assert cfg["document"]["permissions"]["edit"] is False
    # 取件 URL 指向平台受控端点，含短时 ft token，但无内部引用。
    assert "/api/v1/preview/" in cfg["document"]["url"] and "ft=" in cfg["document"]["url"]
    _assert_no_leak(entry.text)


async def test_preview_entry_wrong_user_404(client, monkeypatch):
    _enable_onlyoffice(monkeypatch)
    asset_id = await _upload_confirm_personal(client)
    cred_id = (await _issue(client, asset_id)).json()["credential_id"]
    # 他人（非申请人）使用入口 → 404，不泄露存在。
    other = await client.get(f"/api/v1/preview/{cred_id}", headers=_hdr(USER_BOSS))
    assert other.status_code == 404


async def test_preview_not_configured_safe_message(client):
    # 未启用 ONLYOFFICE（默认）→ 安全说明，无 config，无泄露，不回退原文 URL。
    asset_id = await _upload_confirm_personal(client)
    cred_id = (await _issue(client, asset_id)).json()["credential_id"]
    entry = await client.get(f"/api/v1/preview/{cred_id}", headers=_hdr(USER_CONSULTANT))
    assert entry.status_code == 200
    assert entry.json()["onlyoffice_config"] is None
    assert entry.json()["message"] == "onlyoffice_not_configured"
    _assert_no_leak(entry.text)


async def test_preview_unsupported_type(client, monkeypatch):
    _enable_onlyoffice(monkeypatch)
    asset_id = await _upload_confirm_personal(client, name="image.png", content=b"\x89PNG fake bytes", mime="image/png")
    cred_id = (await _issue(client, asset_id)).json()["credential_id"]
    entry = await client.get(f"/api/v1/preview/{cred_id}", headers=_hdr(USER_CONSULTANT))
    assert entry.json()["onlyoffice_config"] is None
    assert entry.json()["message"] == "preview_type_not_available"


# ---------------- 受控取件端点 ----------------
async def _entry_fetch_token(client, cred_id):
    entry = await client.get(f"/api/v1/preview/{cred_id}", headers=_hdr(USER_CONSULTANT))
    url = entry.json()["onlyoffice_config"]["document"]["url"]
    return parse_qs(urlparse(url).query)["ft"][0]


async def test_controlled_file_serves_bytes(client, monkeypatch):
    _enable_onlyoffice(monkeypatch)
    content = "受控取件正文内容。".encode()
    asset_id = await _upload_confirm_personal(client, content=content)
    cred_id = (await _issue(client, asset_id)).json()["credential_id"]
    ft = await _entry_fetch_token(client, cred_id)
    resp = await client.get(f"/api/v1/preview/{cred_id}/file", params={"ft": ft})
    assert resp.status_code == 200
    assert resp.content == content
    # 头部不含内部引用。
    _assert_no_leak(str(dict(resp.headers)))


async def test_controlled_file_wrong_token_rejected(client, monkeypatch):
    _enable_onlyoffice(monkeypatch)
    asset_id = await _upload_confirm_personal(client)
    cred_id = (await _issue(client, asset_id)).json()["credential_id"]
    await _entry_fetch_token(client, cred_id)  # 铸造正确 token
    resp = await client.get(f"/api/v1/preview/{cred_id}/file", params={"ft": "wrong-token"})
    assert resp.status_code == 403
    assert resp.json()["detail"]["denied_reason"] == "preview_fetch_token_invalid"


async def test_controlled_file_expired_and_revoked(client, monkeypatch, db_session):
    _enable_onlyoffice(monkeypatch)
    asset_id = await _upload_confirm_personal(client)
    cred_id = (await _issue(client, asset_id)).json()["credential_id"]
    ft = await _entry_fetch_token(client, cred_id)
    # 过期 → 403。
    cred = await db_session.get(PreviewCredential, uuid.UUID(cred_id))
    cred.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()
    r_exp = await client.get(f"/api/v1/preview/{cred_id}/file", params={"ft": ft})
    assert r_exp.status_code == 403 and r_exp.json()["detail"]["denied_reason"] == "preview_credential_expired"
    # 撤销 → 403。
    cred = await db_session.get(PreviewCredential, uuid.UUID(cred_id))
    cred.expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    cred.credential_status = "revoked"
    await db_session.commit()
    r_rev = await client.get(f"/api/v1/preview/{cred_id}/file", params={"ft": ft})
    assert r_rev.status_code == 403 and r_rev.json()["detail"]["denied_reason"] == "preview_credential_revoked"


# ---------------- WeCom 通知派发 ----------------
class FakeSender:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    async def send(self, *, wecom_user_id, title, content, trace_id=None):
        if self.fail:
            raise WeComError("wecom_msg_60020", "下发失败")
        self.calls.append((wecom_user_id, title, content))


async def _wecom_record(db_session, recipient, *, title="归档预警：X", content="安全摘要内容。"):
    rec = await alert_service.record_local_notification(
        db_session, recipient_user_id=recipient, title=title, content=content,
        channel="wecom",
    )
    await db_session.commit()
    return rec


async def test_dispatch_sends_bound_recipient(db_session):
    # consultant_a 绑定 wecom_user_id（seed），pending wecom 通知 → sent。
    rec = await _wecom_record(db_session, USER_CONSULTANT)
    sender = FakeSender()
    res = await wecom_notification.dispatch_pending(db_session, sender=sender, trace_id="trc-n1")
    assert res["sent"] == 1 and res["failed"] == 0
    await db_session.refresh(rec)
    assert rec.send_status == "sent" and rec.sent_at is not None
    assert len(sender.calls) == 1
    # 审计 notification.sent 不含正文。
    audit = (await db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "notification.sent")
        .where(AuditEvent.target_id == rec.id)
    )).scalar_one()
    assert "安全摘要内容" not in str(audit.extra)


async def test_dispatch_missing_binding_fails_safe(db_session):
    # boss 无 wecom_user_id（seed）→ 安全失败。
    rec = await _wecom_record(db_session, USER_BOSS)
    res = await wecom_notification.dispatch_pending(db_session, sender=FakeSender())
    assert res["failed"] == 1
    await db_session.refresh(rec)
    assert rec.send_status == "failed" and rec.failure_reason == "recipient_unavailable"


async def test_dispatch_inactive_recipient_fails_safe(db_session):
    inactive = User(id=uuid.uuid4(), name="离职Y", email="y@dev.local",
                    status="inactive", wecom_user_id="ww_y")
    db_session.add(inactive)
    await db_session.commit()
    rec = await _wecom_record(db_session, inactive.id)
    res = await wecom_notification.dispatch_pending(db_session, sender=FakeSender())
    assert res["failed"] == 1
    await db_session.refresh(rec)
    assert rec.send_status == "failed" and rec.failure_reason == "recipient_unavailable"


async def test_dispatch_upstream_failure_and_no_duplicate_send(db_session):
    rec = await _wecom_record(db_session, USER_CONSULTANT)
    # 第一次上游失败 → failed + attempts=1。
    res1 = await wecom_notification.dispatch_pending(db_session, sender=FakeSender(fail=True))
    assert res1["failed"] == 1
    await db_session.refresh(rec)
    assert rec.send_status == "failed" and rec.send_attempts == 1
    # 重试（可重试，attempts<max）→ 成功 sent。
    ok = FakeSender()
    res2 = await wecom_notification.dispatch_pending(db_session, sender=ok)
    assert res2["sent"] == 1
    await db_session.refresh(rec)
    assert rec.send_status == "sent"
    # 再派发：已 sent 不重复下发（幂等）。
    again = FakeSender()
    res3 = await wecom_notification.dispatch_pending(db_session, sender=again)
    assert res3["processed"] == 0 and len(again.calls) == 0


async def test_disabled_flag_fails_closed_no_send(db_session, monkeypatch):
    # WECOM_NOTIFY_ENABLED 关 → 工厂给 Null 发送器，派发器不外发，记录保持 pending。
    monkeypatch.setattr(wecom_notification, "wecom_send_enabled", lambda: False)
    sender = wecom_notification.get_wecom_notification_sender()
    assert isinstance(sender, wecom_notification.NullWeComNotificationSender)
    rec = await _wecom_record(db_session, USER_CONSULTANT)
    res = await wecom_notification.dispatch_pending(db_session, sender=sender)
    assert res["sent"] == 0 and res["processed"] == 0 and res.get("skipped") == "wecom_notify_disabled"
    await db_session.refresh(rec)
    # 未尝试外发：仍 pending、attempts 未增。
    assert rec.send_status == "pending" and rec.send_attempts == 0


async def test_disabled_flag_default_channel_in_app(monkeypatch):
    monkeypatch.setattr(wecom_notification, "wecom_send_enabled", lambda: False)
    assert wecom_notification.default_notification_channel() == "in_app"
    monkeypatch.setattr(wecom_notification, "wecom_send_enabled", lambda: True)
    assert wecom_notification.default_notification_channel() == "wecom"


async def test_alert_rule_channel_validation(client):
    rules = await client.get("/api/v1/admin/alerts/rules", headers=_hdr(USER_ADMIN_ONLY))
    assert rules.status_code == 200
    rule_id = rules.json()["items"][0]["id"]
    # 非法渠道 → 422 invalid_notification_channel。
    bad = await client.patch(
        f"/api/v1/admin/alerts/rules/{rule_id}", headers=_hdr(USER_ADMIN_ONLY),
        json={"notification_channels": ["bogus_channel"]},
    )
    assert bad.status_code == 422
    assert bad.json()["detail"]["denied_reason"] == "invalid_notification_channel"
    # 合法 wecom + in_app → 200。
    ok = await client.patch(
        f"/api/v1/admin/alerts/rules/{rule_id}", headers=_hdr(USER_ADMIN_ONLY),
        json={"notification_channels": ["wecom", "in_app"]},
    )
    assert ok.status_code == 200
    assert set(ok.json()["notification_channels"]) == {"wecom", "in_app"}


async def test_notification_content_value_sanitized(db_session):
    # 内含对象存储 URL 的内容在落库时被值级脱敏。
    rec = await alert_service.record_local_notification(
        db_session, recipient_user_id=USER_CONSULTANT,
        title="通知", content="s3://secret-bucket/path/original.docx", channel="wecom",
    )
    await db_session.commit()
    assert "s3://" not in rec.content and rec.content == "[redacted]"
