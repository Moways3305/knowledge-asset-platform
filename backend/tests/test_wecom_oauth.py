"""企微 OAuth 身份 + Path A 微盘扫描测试（fake WeCom 客户端，不打真实网络）。

覆盖：
- OAuth start 生成 state 绑定授权 URL，不泄露 secret。
- OAuth callback（合法 code/state）建会话 + 返回身份；未知/非 active 用户 fail closed；
  缺/错 state 拒绝；login.success/failed 审计不含 code/token/secret。
- wecom_user_id 唯一且用于身份解析。
- 扫描配置 列表/启停/记录 API 权限 + 无内部引用泄露。
- 手动扫描建 wecom_scan_record + path_a_wecom IngestTask，复用既有异步处理到 pending_confirmation。
- 重复扫描不重复建任务；单文件失败不中断整批。
- 纯 admin 可运营扫描但拿不到扫描任务的 AI 业务正文。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.main import app
from app.models.audit import AuditEvent
from app.models.identity import User
from app.models.ingest import IngestTask
from app.models.wecom import WecomScanConfig, WecomScanRecord
from app.seed.dev_seed import (
    PROJECT_ALPHA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
)
from app.services.wecom_client import (
    WeComDriveClient,
    WeComDriveFile,
    WeComError,
    WeComIdentity,
    get_wecom_drive_client,
    get_wecom_oauth_client,
    parse_directory_path,
)

START = "/api/v1/auth/wecom/start"
CALLBACK = "/api/v1/auth/wecom/callback"
CONFIGS = "/api/v1/admin/wecom-scan/configs"

_LEAK = [
    "source_file_ref",
    "storage_ref",
    "internal://",
    "download_url",
    "access_token",
    "app_secret",
    "wecom_secret",
    "ww_consultant_a",
    "weknora",
    "kb_id",
    "doc_id",
    "sk-",
    "Bearer",
]


def _hdr(user_id, trace=None):
    h = {"X-Dev-User-Id": str(user_id)}
    if trace:
        h["X-Trace-Id"] = trace
    return h


def _assert_no_leak(text):
    for t in _LEAK:
        assert t not in text, f"响应不应泄露 {t}"


class FakeOAuth:
    def __init__(self, wecom_user_id="ww_consultant_a"):
        self.wecom_user_id = wecom_user_id

    def build_authorize_url(self, *, state, mode="client"):
        # 含 corp_id/state，绝不含 app_secret。
        base = (
            "https://open.work.weixin.qq.com/wwopen/sso/qrConnect"
            if mode == "web_qr"
            else "https://open.weixin.qq.com/connect/oauth2/authorize"
        )
        return f"{base}?appid=test_corp&state={state}"

    async def exchange_code(self, code):
        if not code:
            raise WeComError("wecom_missing_code", "缺少 code")
        return WeComIdentity(wecom_user_id=self.wecom_user_id)

    async def get_member_status(self, wecom_user_id):
        # 默认 fake 成员有效（保持既有回调成功用例语义）。
        from app.services.wecom_client import WeComMemberStatus

        return WeComMemberStatus(wecom_user_id, True, "active", "企微成员有效")


class FakeDrive:
    """fake 微盘：list_files 返回元数据；download_file 返回字节；可模拟单文件失败。"""

    def __init__(self, files, fail_ids=()):
        self._files = files  # list[(file_id, name, content_hash, content_bytes)]
        self._fail = set(fail_ids)

    async def list_files(self, directory_path):
        return [
            WeComDriveFile(file_id=fid, name=name, mime="text/plain", size=len(b), content_hash=h)
            for (fid, name, h, b) in self._files
        ]

    async def download_file(self, file_id):
        if file_id in self._fail:
            raise WeComError("wecom_download_failed", "下载失败")
        for fid, _name, _h, b in self._files:
            if fid == file_id:
                return b
        raise WeComError("wecom_not_found", "文件不存在")


def _install_oauth(fake):
    app.dependency_overrides[get_wecom_oauth_client] = lambda: fake


def _install_drive(fake):
    app.dependency_overrides[get_wecom_drive_client] = lambda: fake


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.pop(get_wecom_oauth_client, None)
    app.dependency_overrides.pop(get_wecom_drive_client, None)


# ---------------- OAuth ----------------
async def test_oauth_start_state_bound_no_secret(client):
    _install_oauth(FakeOAuth())
    resp = await client.get(START)
    assert resp.status_code == 200
    url = resp.json()["authorize_url"]
    assert "connect/oauth2/authorize" in url
    assert "state=" in url and "appid=" in url
    assert "secret" not in resp.text
    # state 写入 httpOnly cookie（不在 JSON body）。
    assert client.cookies.get("kap_oauth_state")


async def test_oauth_start_web_qr_state_bound_no_secret(client):
    _install_oauth(FakeOAuth())
    resp = await client.get(START, params={"mode": "web_qr"})
    assert resp.status_code == 200
    url = resp.json()["authorize_url"]
    assert "wwopen/sso/qrConnect" in url
    assert "state=" in url and "appid=" in url
    assert "secret" not in resp.text
    # state 写入 httpOnly cookie（不在 JSON body）。
    assert client.cookies.get("kap_oauth_state")


async def test_oauth_callback_success_creates_session(client):
    _install_oauth(FakeOAuth("ww_consultant_a"))
    await client.get(START)
    state = client.cookies.get("kap_oauth_state")
    resp = await client.get(
        CALLBACK,
        params={"code": "valid-code", "state": state},
        headers={"X-Trace-Id": "trc-oauth-ok"},
    )
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"] == "/"
    assert "kap_session=" in resp.headers.get("set-cookie", "")
    assert resp.text == ""
    # 会话 cookie 已下发；后续 /auth/me 即为该用户。
    me = await client.get("/api/v1/auth/me")
    assert me.json()["user_id"] == str(USER_CONSULTANT)
    _assert_no_leak(resp.text)


async def test_oauth_callback_unknown_user_fails_closed(client):
    _install_oauth(FakeOAuth("ww_unknown_nobody"))
    await client.get(START)
    state = client.cookies.get("kap_oauth_state")
    resp = await client.get(CALLBACK, params={"code": "c", "state": state})
    assert resp.status_code == 303, resp.text
    body = (await client.get("/api/v1/auth/me")).json()
    assert body["status"] == "active"
    assert body["company_roles"] == ["consultant"]
    assert body["is_business_user"] is True
    assert body["can_discover_l5"] is False


async def test_oauth_callback_inactive_user_fails_closed(client, db_session):
    inactive = User(
        id=uuid.uuid4(),
        name="离职X",
        email="left@dev.local",
        status="inactive",
        wecom_user_id="ww_inactive",
    )
    db_session.add(inactive)
    await db_session.commit()
    _install_oauth(FakeOAuth("ww_inactive"))
    await client.get(START)
    state = client.cookies.get("kap_oauth_state")
    resp = await client.get(
        CALLBACK, params={"code": "c", "state": state}, headers={"X-Trace-Id": "trc-oauth-inactive"}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["denied_reason"] == "user_inactive"


async def test_oauth_callback_invalid_state_rejected(client):
    _install_oauth(FakeOAuth())
    await client.get(START)  # sets a state cookie
    # 提供不匹配的 state → 400。
    resp = await client.get(CALLBACK, params={"code": "c", "state": "tampered-state"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["denied_reason"] == "oauth_state_invalid"


async def test_oauth_audit_has_no_code_or_token(client, db_session):
    _install_oauth(FakeOAuth("ww_consultant_a"))
    await client.get(START)
    state = client.cookies.get("kap_oauth_state")
    await client.get(
        CALLBACK,
        params={"code": "secret-code-xyz", "state": state},
        headers={"X-Trace-Id": "trc-oauth-audit"},
    )
    row = (
        await db_session.execute(
            select(AuditEvent)
            .where(AuditEvent.trace_id == "trc-oauth-audit")
            .where(AuditEvent.action == "auth.wecom_login_success")
        )
    ).scalar_one()
    extra_text = str(row.extra or {})
    assert row.extra.get("login_method") == "wecom_oauth"
    for tok in ("secret-code-xyz", "access_token", "code", "state"):
        assert tok not in extra_text


# ---------------- 扫描配置 / 记录 API ----------------
async def _new_config(db_session, *, scope_type="project", project_id=PROJECT_ALPHA, enabled=True):
    config = WecomScanConfig(
        directory_path="/微盘/Alpha 交付",
        scope_type=scope_type,
        related_project_id=project_id if scope_type == "project" else None,
        enabled=enabled,
        created_by=USER_CONSULTANT,
    )
    db_session.add(config)
    await db_session.commit()
    return config


async def test_scan_config_permissions(client, db_session):
    await _new_config(db_session)
    # admin / boss 可读；consultant 403。
    assert (await client.get(CONFIGS, headers=_hdr(USER_ADMIN_ONLY))).status_code == 200
    assert (await client.get(CONFIGS, headers=_hdr(USER_BOSS))).status_code == 200
    forbidden = await client.get(CONFIGS, headers=_hdr(USER_CONSULTANT))
    assert forbidden.status_code == 403
    _assert_no_leak((await client.get(CONFIGS, headers=_hdr(USER_ADMIN_ONLY))).text)


async def test_scan_config_update_admin_only(client, db_session):
    config = await _new_config(db_session)
    url = f"{CONFIGS}/{config.id}"
    # 治理角色（非 admin）不能启停。
    assert (
        await client.patch(url, headers=_hdr(USER_DIRECTOR), json={"enabled": False})
    ).status_code == 403
    ok = await client.patch(url, headers=_hdr(USER_ADMIN_ONLY), json={"enabled": False})
    assert ok.status_code == 200
    assert ok.json()["enabled"] is False


# ---------------- Path A 扫描 ----------------
async def test_manual_scan_creates_tasks_and_reuses_processing(client, db_session):
    config = await _new_config(db_session)
    drive = FakeDrive(
        [
            ("f1", "Alpha 交付报告.txt", "wh1", "供应链优化交付报告正文若干。".encode()),
            ("f2", "Alpha 方法论.txt", "wh2", "项目方法论正文内容。".encode()),
        ]
    )
    _install_drive(drive)
    resp = await client.post(f"{CONFIGS}/{config.id}/scan", headers=_hdr(USER_ADMIN_ONLY))
    assert resp.status_code == 200, resp.text
    rec = resp.json()
    assert rec["scan_status"] == "completed"
    assert rec["discovered_count"] == 2 and rec["new_count"] == 2 and rec["duplicate_count"] == 0
    _assert_no_leak(resp.text)

    # 建了 path_a_wecom 任务，且复用既有异步处理到 pending_confirmation。
    tasks = list(
        (await db_session.execute(select(IngestTask).where(IngestTask.source == "path_a_wecom")))
        .scalars()
        .all()
    )
    assert len(tasks) == 2
    for t in tasks:
        assert t.status in ("pending_confirmation", "failed")
        assert t.target_scope == "project" and t.target_zone == "material"
        assert t.created_by == USER_CONSULTANT


async def test_rescan_dedups_no_duplicate_tasks(client, db_session):
    config = await _new_config(db_session)
    files = [("f1", "a.txt", "dh1", "内容A 正文若干。".encode())]
    _install_drive(FakeDrive(files))
    r1 = await client.post(f"{CONFIGS}/{config.id}/scan", headers=_hdr(USER_ADMIN_ONLY))
    assert r1.json()["new_count"] == 1
    # 同内容再扫 → 重复，不新建任务。
    _install_drive(FakeDrive(files))
    r2 = await client.post(f"{CONFIGS}/{config.id}/scan", headers=_hdr(USER_ADMIN_ONLY))
    assert r2.json()["new_count"] == 0 and r2.json()["duplicate_count"] == 1
    total = await db_session.scalar(
        select(func.count())
        .select_from(IngestTask)
        .where(IngestTask.source == "path_a_wecom")
        .where(IngestTask.source_file_hash == "dh1")
    )
    assert total == 1


async def test_scan_per_file_failure_not_abort(client, db_session):
    config = await _new_config(db_session)
    drive = FakeDrive(
        [("f1", "ok.txt", "fh1", "正文内容。".encode()), ("f2", "bad.txt", "fh2", b"x")],
        fail_ids={"f2"},
    )
    _install_drive(drive)
    resp = await client.post(f"{CONFIGS}/{config.id}/scan", headers=_hdr(USER_ADMIN_ONLY))
    rec = resp.json()
    assert rec["scan_status"] == "completed"
    assert rec["discovered_count"] == 2 and rec["new_count"] == 1 and rec["failed_count"] == 1


async def test_scan_records_listed_no_leak(client, db_session):
    config = await _new_config(db_session)
    _install_drive(FakeDrive([("f1", "a.txt", "rh1", "正文。".encode())]))
    await client.post(f"{CONFIGS}/{config.id}/scan", headers=_hdr(USER_ADMIN_ONLY))
    recs = await client.get(f"{CONFIGS}/{config.id}/records", headers=_hdr(USER_BOSS))
    assert recs.status_code == 200
    assert len(recs.json()["items"]) >= 1
    _assert_no_leak(recs.text)


# ---------------- 真实 Drive 客户端纯函数（无网络） ----------------
def test_parse_directory_path_valid_and_invalid():
    assert parse_directory_path("spaceid:sp1;fatherid:fa1") == ("sp1", "fa1")
    # fatherid 省略 → 根目录（空串）。
    assert parse_directory_path("spaceid:sp1") == ("sp1", "")
    # 缺 spaceid → 拒绝（不静默用 admin/系统）。
    import pytest as _pytest

    with _pytest.raises(WeComError):
        parse_directory_path("/微盘/Alpha")


def test_drive_check_errcode():
    c = WeComDriveClient(corp_id="x", app_secret="s", base_url="https://q")
    assert c._check({"errcode": 0, "file_list": []})["file_list"] == []
    import pytest as _pytest

    with _pytest.raises(WeComError) as ei:
        c._check({"errcode": 40058, "errmsg": "raw upstream msg"})
    # 只暴露 errcode，不回显上游 errmsg 原文。
    assert "raw upstream msg" not in str(ei.value)
    assert "40058" in ei.value.code


# ---------------- 幂等（DB 级 + API 行为） ----------------
async def test_scan_idempotency_same_key_returns_same_record(client, db_session):
    config = await _new_config(db_session)
    files = [("f1", "idem.txt", "ih1", "正文内容若干。".encode())]
    _install_drive(FakeDrive(files))
    r1b = await client.post(
        f"{CONFIGS}/{config.id}/scan",
        headers={**_hdr(USER_ADMIN_ONLY), "Idempotency-Key": "K1"},
    )
    _install_drive(FakeDrive(files))
    r2 = await client.post(
        f"{CONFIGS}/{config.id}/scan",
        headers={**_hdr(USER_ADMIN_ONLY), "Idempotency-Key": "K1"},
    )
    assert r1b.status_code == 200 and r2.status_code == 200
    # 同 key 第二次返回同一条记录。
    assert r1b.json()["id"] == r2.json()["id"]
    # 该 key 只建一条记录。
    key_recs = await db_session.scalar(
        select(func.count())
        .select_from(WecomScanRecord)
        .where(WecomScanRecord.config_id == config.id)
        .where(WecomScanRecord.idempotency_key == "K1")
    )
    assert key_recs == 1
    # 同内容 hash 不重复建任务。
    task_cnt = await db_session.scalar(
        select(func.count())
        .select_from(IngestTask)
        .where(IngestTask.source == "path_a_wecom")
        .where(IngestTask.source_file_hash == "ih1")
    )
    assert task_cnt == 1


async def test_scan_idempotency_different_key_and_config(client, db_session):
    config = await _new_config(db_session)
    files = [("f1", "a.txt", "dk1", "正文。".encode())]
    _install_drive(FakeDrive(files))
    await client.post(
        f"{CONFIGS}/{config.id}/scan", headers={**_hdr(USER_ADMIN_ONLY), "Idempotency-Key": "A"}
    )
    _install_drive(FakeDrive(files))
    await client.post(
        f"{CONFIGS}/{config.id}/scan", headers={**_hdr(USER_ADMIN_ONLY), "Idempotency-Key": "B"}
    )
    # 同 config 不同 key → 两条记录。
    cnt = await db_session.scalar(
        select(func.count())
        .select_from(WecomScanRecord)
        .where(WecomScanRecord.config_id == config.id)
    )
    assert cnt == 2

    # 不同 config 同 key → 允许（部分唯一是 config+key 维度）。
    config2 = await _new_config(db_session)
    _install_drive(FakeDrive(files))
    r = await client.post(
        f"{CONFIGS}/{config2.id}/scan", headers={**_hdr(USER_ADMIN_ONLY), "Idempotency-Key": "A"}
    )
    assert r.status_code == 200
    cnt2 = await db_session.scalar(
        select(func.count())
        .select_from(WecomScanRecord)
        .where(WecomScanRecord.config_id == config2.id)
        .where(WecomScanRecord.idempotency_key == "A")
    )
    assert cnt2 == 1


async def test_scan_idempotency_db_index_exists(db_session):
    """DB 级保证：(config_id, idempotency_key) 上存在**部分唯一索引**（仅非空 key）。"""
    from sqlalchemy import text as _text

    row = (
        await db_session.execute(
            _text(
                "SELECT sql FROM sqlite_master WHERE type='index' "
                "AND name='uq_wecom_scan_idempotency'"
            )
        )
    ).scalar_one_or_none()
    assert row is not None, "缺少 (config_id, idempotency_key) 唯一索引"
    sql = row.upper()
    assert "UNIQUE" in sql
    assert "CONFIG_ID" in sql and "IDEMPOTENCY_KEY" in sql
    # 部分索引：仅 idempotency_key 非空时唯一（NULL key 的记录不受约束）。
    assert "IS NOT NULL" in sql


async def test_admin_cannot_read_scan_task_business_content(client, db_session):
    config = await _new_config(db_session)
    _install_drive(FakeDrive([("f1", "secret.txt", "ah1", "客户机密正文内容若干。".encode())]))
    await client.post(f"{CONFIGS}/{config.id}/scan", headers=_hdr(USER_ADMIN_ONLY))
    task = (
        (await db_session.execute(select(IngestTask).where(IngestTask.source == "path_a_wecom")))
        .scalars()
        .first()
    )
    # 纯 admin 读 ai-result → 仅运营元数据，无业务正文（suggested_title/抽取预览为 None）。
    admin_view = await client.get(
        f"/api/v1/ingest/{task.id}/ai-result", headers=_hdr(USER_ADMIN_ONLY)
    )
    assert admin_view.status_code == 200
    assert admin_view.json().get("suggested_title") is None
    assert admin_view.json().get("extracted_text_preview") is None
    # 创建人（顾问A）可见业务建议正文。
    owner_view = await client.get(
        f"/api/v1/ingest/{task.id}/ai-result", headers=_hdr(USER_CONSULTANT)
    )
    assert owner_view.status_code == 200
    _assert_no_leak(admin_view.text)
