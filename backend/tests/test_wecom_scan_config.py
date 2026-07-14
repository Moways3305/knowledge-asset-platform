"""企微微盘扫描配置 CRUD 测试。

覆盖：
- admin 可创建配置（配置操作人 = 审计 actor）；created_by = 业务归属人（task_owner_user_id）。
- boss / director 可读配置与项目候选，但不可创建 / 编辑。
- consultant 不可读（403）。
- directory_path 格式错误 / scope 非法 / project 缺 id / project 不存在 / name 空 → 422。
- personal/company scope 携带 project_id → 422（一致拒绝策略）。
- 创建后 GET 列表可见，含 name / related_project_name。
- PATCH 可改 enabled / name / target_scope。
- 创建的配置可触发扫描（复用既有扫描逻辑）。
- 审计 wecom_scan.config_created / config_updated 写安全字段；响应与审计无泄露。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.main import app
from app.models.audit import AuditEvent
from app.models.identity import ProjectMember, User, UserCompanyRole
from app.models.ingest import IngestTask
from app.models.wecom import WecomScanConfig, WecomScanRecord
from app.seed.dev_seed import (
    PROJECT_ALPHA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
    USER_PROJECT_MANAGER,
)
from app.services import wecom_scan as scan_service
from app.services.wecom_client import (
    WeComDriveClient,
    WeComDriveFile,
    get_wecom_drive_client,
)

CONFIGS = "/api/v1/admin/wecom-scan/configs"
OPTIONS = "/api/v1/admin/wecom-scan/project-options"
OWNER_OPTIONS = "/api/v1/admin/wecom-scan/owner-options"
PENDING = "/api/v1/ingest/pending?source=path_a_wecom"
VALID_DIR = "spaceid:sp1;fatherid:fa1"

_LEAK = [
    "source_file_ref",
    "storage_ref",
    "internal://",
    "download_url",
    "access_token",
    "app_secret",
    "wecom_secret",
    "cookie",
    "file_id",
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
        assert t not in text, f"响应/审计不应泄露 {t}"


def _body(**over):
    base = {
        "name": "Alpha 交付目录",
        "directory_path": VALID_DIR,
        "target_scope": "project",
        "target_project_id": str(PROJECT_ALPHA),
        # 业务归属人：顾问 A 是 Alpha active 成员。
        "task_owner_user_id": str(USER_CONSULTANT),
        "enabled": True,
    }
    base.update(over)
    return base


# ---------------- 创建 ----------------
async def test_admin_can_create_config(client):
    resp = await client.post(CONFIGS, headers=_hdr(USER_ADMIN_ONLY), json=_body())
    assert resp.status_code == 201, resp.text
    out = resp.json()
    assert out["name"] == "Alpha 交付目录"
    assert out["scope_type"] == "project"
    assert out["related_project_id"] == str(PROJECT_ALPHA)
    assert out["related_project_name"]  # 解析出项目名
    assert out["enabled"] is True
    # created_by = 业务归属人（顾问 A），而非配置操作人 admin。
    assert out["created_by"] == str(USER_CONSULTANT)
    assert out["created_by"] != str(USER_ADMIN_ONLY)
    assert out["task_owner_name"]
    _assert_no_leak(resp.text)


async def test_created_by_is_owner_not_admin_operator(client):
    # 配置操作人是 admin（审计 actor），created_by 写入校验通过的业务归属人；
    # 前端塞 created_by 不被 schema 接收。
    resp = await client.post(
        CONFIGS,
        headers=_hdr(USER_ADMIN_ONLY),
        json={**_body(), "created_by": str(USER_ADMIN_ONLY)},
    )
    assert resp.status_code == 201
    assert resp.json()["created_by"] == str(USER_CONSULTANT)


async def test_create_personal_scope_no_project(client):
    resp = await client.post(
        CONFIGS,
        headers=_hdr(USER_ADMIN_ONLY),
        json=_body(target_scope="personal", target_project_id=None),
    )
    assert resp.status_code == 201
    assert resp.json()["related_project_id"] is None
    assert resp.json()["created_by"] == str(USER_CONSULTANT)


# ---------------- 权限 ----------------
async def test_governance_can_read_not_write(client):
    # 先由 admin 建一条。
    await client.post(CONFIGS, headers=_hdr(USER_ADMIN_ONLY), json=_body())
    # boss / director 可读 configs + project-options。
    assert (await client.get(CONFIGS, headers=_hdr(USER_BOSS))).status_code == 200
    assert (await client.get(OPTIONS, headers=_hdr(USER_DIRECTOR))).status_code == 200
    # 但不可创建。
    denied = await client.post(CONFIGS, headers=_hdr(USER_BOSS), json=_body(name="x"))
    assert denied.status_code == 403
    assert denied.json()["detail"]["denied_reason"] == "wecom_scan_admin_required"


async def test_consultant_cannot_read(client):
    assert (await client.get(CONFIGS, headers=_hdr(USER_CONSULTANT))).status_code == 403
    assert (await client.get(OPTIONS, headers=_hdr(USER_CONSULTANT))).status_code == 403


# ---------------- 校验 ----------------
async def test_invalid_directory_format_422(client):
    resp = await client.post(
        CONFIGS, headers=_hdr(USER_ADMIN_ONLY), json=_body(directory_path="/微盘/Alpha")
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["denied_reason"] == "wecom_invalid_directory"
    _assert_no_leak(resp.text)


async def test_project_scope_missing_project_422(client):
    resp = await client.post(
        CONFIGS,
        headers=_hdr(USER_ADMIN_ONLY),
        json=_body(target_scope="project", target_project_id=None),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["denied_reason"] == "target_project_required"


async def test_invalid_scope_422(client):
    resp = await client.post(
        CONFIGS, headers=_hdr(USER_ADMIN_ONLY), json=_body(target_scope="weird")
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["denied_reason"] == "wecom_scan_invalid_scope"


async def test_project_not_found_422(client):
    resp = await client.post(
        CONFIGS,
        headers=_hdr(USER_ADMIN_ONLY),
        json=_body(target_project_id=str(uuid.uuid4())),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["denied_reason"] == "target_project_not_found"


async def test_personal_with_project_id_422(client):
    resp = await client.post(
        CONFIGS,
        headers=_hdr(USER_ADMIN_ONLY),
        json=_body(target_scope="company", target_project_id=str(PROJECT_ALPHA)),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["denied_reason"] == "target_project_not_allowed"


async def test_empty_name_422(client):
    resp = await client.post(CONFIGS, headers=_hdr(USER_ADMIN_ONLY), json=_body(name="   "))
    assert resp.status_code == 422
    assert resp.json()["detail"]["denied_reason"] == "wecom_scan_name_required"


# ---------------- 列表 / 编辑 ----------------
async def test_created_config_visible_in_list(client):
    created = (await client.post(CONFIGS, headers=_hdr(USER_ADMIN_ONLY), json=_body())).json()
    listed = await client.get(CONFIGS, headers=_hdr(USER_ADMIN_ONLY))
    assert listed.status_code == 200
    items = listed.json()["items"]
    match = next((i for i in items if i["id"] == created["id"]), None)
    assert match is not None
    assert match["name"] == "Alpha 交付目录"
    assert match["related_project_name"]


async def test_patch_edits_enabled_name_scope(client):
    cid = (await client.post(CONFIGS, headers=_hdr(USER_ADMIN_ONLY), json=_body())).json()["id"]
    url = f"{CONFIGS}/{cid}"
    # 改 name + 停用。
    r1 = await client.patch(
        url, headers=_hdr(USER_ADMIN_ONLY), json={"name": "改名后", "enabled": False}
    )
    assert r1.status_code == 200
    assert r1.json()["name"] == "改名后"
    assert r1.json()["enabled"] is False
    # 改 scope 为 company（应清空 project）：company 归属人须为治理角色，故同时改归属人为 boss。
    r2 = await client.patch(
        url,
        headers=_hdr(USER_ADMIN_ONLY),
        json={"target_scope": "company", "task_owner_user_id": str(USER_BOSS)},
    )
    assert r2.status_code == 200
    assert r2.json()["scope_type"] == "company"
    assert r2.json()["related_project_id"] is None
    assert r2.json()["created_by"] == str(USER_BOSS)


async def test_patch_admin_only(client):
    cid = (await client.post(CONFIGS, headers=_hdr(USER_ADMIN_ONLY), json=_body())).json()["id"]
    denied = await client.patch(
        f"{CONFIGS}/{cid}", headers=_hdr(USER_DIRECTOR), json={"enabled": False}
    )
    assert denied.status_code == 403


async def test_patch_invalid_directory_422(client):
    cid = (await client.post(CONFIGS, headers=_hdr(USER_ADMIN_ONLY), json=_body())).json()["id"]
    resp = await client.patch(
        f"{CONFIGS}/{cid}", headers=_hdr(USER_ADMIN_ONLY), json={"directory_path": "bad-format"}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["denied_reason"] == "wecom_invalid_directory"


# ---------------- 扫描复用 ----------------
class _FakeDrive(WeComDriveClient):
    def __init__(self, files):
        self._files = files

    async def list_files(self, directory_path):
        return [
            WeComDriveFile(
                file_id=fid, name=name, mime="text/plain", size=len(name), content_hash=h
            )
            for (fid, name, h) in self._files
        ]

    async def download_file(self, file_id):
        return f"内容-{file_id}".encode()


async def test_created_config_can_trigger_scan(client):
    cid = (await client.post(CONFIGS, headers=_hdr(USER_ADMIN_ONLY), json=_body())).json()["id"]
    app.dependency_overrides[get_wecom_drive_client] = lambda: _FakeDrive(
        [("f1", "交付报告.txt", "h1"), ("f2", "方法论.txt", "h2")]
    )
    try:
        resp = await client.post(f"{CONFIGS}/{cid}/scan", headers=_hdr(USER_ADMIN_ONLY))
    finally:
        app.dependency_overrides.pop(get_wecom_drive_client, None)
    assert resp.status_code == 200, resp.text
    rec = resp.json()
    assert rec["discovered_count"] == 2
    assert rec["new_count"] == 2
    _assert_no_leak(resp.text)


# ---------------- 审计 / no-leak ----------------
async def test_audit_created_and_updated_safe(client, db_session):
    created = await client.post(
        CONFIGS, headers={**_hdr(USER_ADMIN_ONLY), "X-Trace-Id": "trc-cfg-create"}, json=_body()
    )
    cid = created.json()["id"]
    await client.patch(
        f"{CONFIGS}/{cid}",
        headers={**_hdr(USER_ADMIN_ONLY), "X-Trace-Id": "trc-cfg-update"},
        json={"name": "审计改名"},
    )
    rows = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.target_type == "wecom_scan_config")
            )
        )
        .scalars()
        .all()
    )
    actions = {r.action for r in rows}
    assert "wecom_scan.config_created" in actions
    assert "wecom_scan.config_updated" in actions
    for r in rows:
        blob = f"{r.before_snapshot}{r.after_snapshot}{r.extra}"
        _assert_no_leak(blob)
        # 审计不写 directory_path 原值，只写 set/changed 标记。
        assert VALID_DIR not in blob
    # 配置确实落库且 created_by 为业务归属人（顾问 A），不是配置操作人 admin。
    cfg = await db_session.get(WecomScanConfig, uuid.UUID(cid))
    assert cfg is not None and cfg.created_by == USER_CONSULTANT
    # 审计 actor 为 admin（操作人），与业务归属人不混淆。
    created_evt = next(r for r in rows if r.action == "wecom_scan.config_created")
    assert created_evt.actor_user_id == USER_ADMIN_ONLY
    assert created_evt.after_snapshot.get("task_owner_user_id") == str(USER_CONSULTANT)


# ================= 业务归属人 =================
async def test_owner_required(client):
    body = _body()
    body.pop("task_owner_user_id")
    resp = await client.post(CONFIGS, headers=_hdr(USER_ADMIN_ONLY), json=body)
    assert resp.status_code == 422  # pydantic 必填校验


async def test_owner_not_found_422(client):
    resp = await client.post(
        CONFIGS,
        headers=_hdr(USER_ADMIN_ONLY),
        json=_body(task_owner_user_id=str(uuid.uuid4())),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["denied_reason"] == "task_owner_not_found"


async def test_owner_inactive_422(client, db_session):
    # 造一个 inactive 业务用户（有 active 顾问角色，但 user.status=inactive）。
    uid = uuid.uuid4()
    u = User(id=uid, name="停用顾问", email=f"inactive-{uid}@dev.local", status="inactive")
    u.company_roles.append(UserCompanyRole(company_role="consultant", status="active"))
    db_session.add(u)
    await db_session.commit()
    resp = await client.post(
        CONFIGS,
        headers=_hdr(USER_ADMIN_ONLY),
        json=_body(target_scope="personal", target_project_id=None, task_owner_user_id=str(uid)),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["denied_reason"] == "task_owner_inactive"


async def test_owner_pure_admin_422(client):
    # 纯 admin（admin active + consultant inactive）不是业务用户 → 拒绝。
    resp = await client.post(
        CONFIGS,
        headers=_hdr(USER_ADMIN_ONLY),
        json=_body(
            target_scope="personal", target_project_id=None, task_owner_user_id=str(USER_ADMIN_ONLY)
        ),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["denied_reason"] == "task_owner_not_business"


async def test_project_owner_not_member_422(client):
    # boss 不是 Alpha active 成员 → 项目级归属人非法。
    resp = await client.post(
        CONFIGS,
        headers=_hdr(USER_ADMIN_ONLY),
        json=_body(task_owner_user_id=str(USER_BOSS)),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["denied_reason"] == "task_owner_not_project_member"


async def test_company_owner_not_governance_422(client):
    # 顾问不是治理角色 → company 级归属人非法。
    resp = await client.post(
        CONFIGS,
        headers=_hdr(USER_ADMIN_ONLY),
        json=_body(
            target_scope="company", target_project_id=None, task_owner_user_id=str(USER_CONSULTANT)
        ),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["denied_reason"] == "task_owner_not_governance"


async def test_company_owner_governance_ok(client):
    resp = await client.post(
        CONFIGS,
        headers=_hdr(USER_ADMIN_ONLY),
        json=_body(
            target_scope="company", target_project_id=None, task_owner_user_id=str(USER_BOSS)
        ),
    )
    assert resp.status_code == 201
    assert resp.json()["created_by"] == str(USER_BOSS)


async def test_owner_options_api(client):
    resp = await client.get(OWNER_OPTIONS, headers=_hdr(USER_ADMIN_ONLY))
    assert resp.status_code == 200
    items = resp.json()["items"]
    ids = {i["user_id"] for i in items}
    assert str(USER_CONSULTANT) in ids  # 业务用户在候选内
    assert str(USER_ADMIN_ONLY) not in ids  # 纯 admin 不在候选内
    # boss 候选标注 governance。
    boss = next(i for i in items if i["user_id"] == str(USER_BOSS))
    assert boss["is_governance"] is True
    _assert_no_leak(resp.text)
    assert "ww_" not in resp.text  # 不泄露 wecom_user_id 明文
    # 治理角色可读 owner-options；consultant 403。
    assert (await client.get(OWNER_OPTIONS, headers=_hdr(USER_DIRECTOR))).status_code == 200
    assert (await client.get(OWNER_OPTIONS, headers=_hdr(USER_CONSULTANT))).status_code == 403


class _FakeDrive2(WeComDriveClient):
    def __init__(self, files):
        self._files = files

    async def list_files(self, directory_path):
        return [
            WeComDriveFile(file_id=fid, name=name, mime="text/plain", size=len(b), content_hash=h)
            for (fid, name, h, b) in self._files
        ]

    async def download_file(self, file_id):
        for fid, _n, _h, b in self._files:
            if fid == file_id:
                return b
        return b""


async def test_scan_task_owned_by_business_owner_end_to_end(client, db_session):
    """端到端：admin 创建（owner=顾问）→ 扫描 → IngestTask.created_by=顾问 →
    顾问在 Path A pending 看到并 confirm 成功；纯 admin 看不到 AI 正文、confirm 403。"""
    cid = (await client.post(CONFIGS, headers=_hdr(USER_ADMIN_ONLY), json=_body())).json()["id"]
    app.dependency_overrides[get_wecom_drive_client] = lambda: _FakeDrive2(
        [("f1", "Alpha 渠道方案.txt", "h1", "渠道融合落地方案正文若干。".encode())]
    )
    try:
        scan = await client.post(f"{CONFIGS}/{cid}/scan", headers=_hdr(USER_ADMIN_ONLY))
    finally:
        app.dependency_overrides.pop(get_wecom_drive_client, None)
    assert scan.status_code == 200
    assert scan.json()["new_count"] == 1

    # IngestTask.created_by 为业务归属人（顾问），不是 admin。
    task = (
        (await db_session.execute(select(IngestTask).where(IngestTask.source == "path_a_wecom")))
        .scalars()
        .first()
    )
    assert task is not None and task.created_by == USER_CONSULTANT

    # 顾问在 Path A pending 看到该任务。
    pending = await client.get(PENDING, headers=_hdr(USER_CONSULTANT))
    assert pending.status_code == 200
    tids = [i["id"] for i in pending.json()["items"]]
    assert str(task.id) in tids

    # 纯 admin 看 AI result 只得运营元数据（无业务正文），且 confirm 被拒。
    ar = await client.get(f"/api/v1/ingest/{task.id}/ai-result", headers=_hdr(USER_ADMIN_ONLY))
    assert ar.status_code == 200
    assert ar.json()["suggested_title"] is None
    bad = await client.post(
        f"/api/v1/ingest/{task.id}/confirm",
        headers=_hdr(USER_ADMIN_ONLY),
        json={
            "title": "x",
            "summary": "y",
            "tags": [],
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "asset_type": "deliverable",
            "confidentiality_level": "L2",
            "ai_access_level": "A2",
        },
    )
    assert bad.status_code == 403

    # 业务归属人（顾问）可复用 confirm 提交项目经理审批。
    ok = await client.post(
        f"/api/v1/ingest/{task.id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json={
            "title": "Alpha 渠道方案",
            "summary": "渠道融合落地方案摘要",
            "tags": ["渠道"],
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "target_zone": "material",
            "asset_type": "deliverable",
            "confidentiality_level": "L2",
            "ai_access_level": "A2",
            "lifecycle_phase_key": "诊断",
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "waiting_review"
    assert ok.json()["result_asset_id"] is None
    review_id = ok.json()["review_id"]
    approved = await client.post(
        f"/api/v1/reviews/{review_id}/approve",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={},
    )
    assert approved.status_code == 200
    assert approved.json()["target_asset_id"]


# ================= 扫描运行时归属人保护 =================
async def _count_path_a_tasks(db_session):
    rows = (
        (await db_session.execute(select(IngestTask).where(IngestTask.source == "path_a_wecom")))
        .scalars()
        .all()
    )
    return len(rows)


def _install_drive():
    app.dependency_overrides[get_wecom_drive_client] = lambda: _FakeDrive2(
        [("f1", "文件.txt", "h1", "正文内容若干。".encode())]
    )


async def test_scan_blocked_when_owner_inactive(client, db_session):
    cid = (await client.post(CONFIGS, headers=_hdr(USER_ADMIN_ONLY), json=_body())).json()["id"]
    # 业务归属人（顾问）被全局停用。
    user = await db_session.get(User, USER_CONSULTANT)
    user.status = "inactive"
    await db_session.commit()
    _install_drive()
    try:
        r = await client.post(f"{CONFIGS}/{cid}/scan", headers=_hdr(USER_ADMIN_ONLY))
    finally:
        app.dependency_overrides.pop(get_wecom_drive_client, None)
    assert r.status_code == 409
    assert r.json()["detail"]["denied_reason"] == "wecom_scan_owner_invalid"
    assert await _count_path_a_tasks(db_session) == 0


async def test_scan_blocked_when_project_member_removed(client, db_session):
    cid = (await client.post(CONFIGS, headers=_hdr(USER_ADMIN_ONLY), json=_body())).json()["id"]
    # 顾问在 Alpha 的 active 成员关系被置 inactive（移出项目）。
    member = (
        (
            await db_session.execute(
                select(ProjectMember).where(
                    ProjectMember.user_id == USER_CONSULTANT,
                    ProjectMember.project_id == PROJECT_ALPHA,
                    ProjectMember.status == "active",
                )
            )
        )
        .scalars()
        .first()
    )
    member.status = "inactive"
    await db_session.commit()
    _install_drive()
    try:
        r = await client.post(f"{CONFIGS}/{cid}/scan", headers=_hdr(USER_ADMIN_ONLY))
    finally:
        app.dependency_overrides.pop(get_wecom_drive_client, None)
    assert r.status_code == 409
    assert r.json()["detail"]["denied_reason"] == "wecom_scan_owner_invalid"
    assert await _count_path_a_tasks(db_session) == 0


async def test_scan_blocked_when_company_owner_loses_governance(client, db_session):
    # company scope，归属人 boss。
    cid = (
        await client.post(
            CONFIGS,
            headers=_hdr(USER_ADMIN_ONLY),
            json=_body(
                target_scope="company", target_project_id=None, task_owner_user_id=str(USER_BOSS)
            ),
        )
    ).json()["id"]
    # boss 的治理 company role 被停用（失去 boss 角色）。
    (await db_session.execute(select(User).where(User.id == USER_BOSS).options())).scalars().first()
    for role in (
        (
            await db_session.execute(
                select(UserCompanyRole).where(UserCompanyRole.user_id == USER_BOSS)
            )
        )
        .scalars()
        .all()
    ):
        role.status = "inactive"
    await db_session.commit()
    _install_drive()
    try:
        r = await client.post(f"{CONFIGS}/{cid}/scan", headers=_hdr(USER_ADMIN_ONLY))
    finally:
        app.dependency_overrides.pop(get_wecom_drive_client, None)
    assert r.status_code == 409
    assert r.json()["detail"]["denied_reason"] == "wecom_scan_owner_invalid"
    assert await _count_path_a_tasks(db_session) == 0


async def test_run_scan_fail_closed_on_invalid_owner_worker_path(client, db_session):
    """直接调用 run_scan（Celery worker 共同路径）：归属人失效 → 记录 failed + 无任务，
    不触碰 drive/storage（owner 校验在列目录之前短路）。"""
    cid = (await client.post(CONFIGS, headers=_hdr(USER_ADMIN_ONLY), json=_body())).json()["id"]
    user = await db_session.get(User, USER_CONSULTANT)
    user.status = "inactive"
    await db_session.commit()
    config = await db_session.get(WecomScanConfig, uuid.UUID(cid))
    record = WecomScanRecord(config_id=config.id, trace_id="t-worker", scan_status="running")
    db_session.add(record)
    await db_session.commit()
    # drive/storage/llm/desensitizer 传 None：归属人失效在使用它们之前已短路返回。
    await scan_service.run_scan(
        db_session,
        config,
        record,
        drive=None,
        storage=None,
        llm=None,
        desensitizer=None,
        trace_id="t-worker",
        actor_caller=None,
    )
    assert record.scan_status == "failed"
    assert record.error_type == "wecom_scan_owner_invalid"
    assert await _count_path_a_tasks(db_session) == 0


async def test_scan_owner_invalid_no_leak(client, db_session):
    cid = (await client.post(CONFIGS, headers=_hdr(USER_ADMIN_ONLY), json=_body())).json()["id"]
    user = await db_session.get(User, USER_CONSULTANT)
    user.status = "inactive"
    await db_session.commit()
    _install_drive()
    try:
        r = await client.post(
            f"{CONFIGS}/{cid}/scan",
            headers={**_hdr(USER_ADMIN_ONLY), "X-Trace-Id": "trc-owner-invalid"},
        )
    finally:
        app.dependency_overrides.pop(get_wecom_drive_client, None)
    assert r.status_code == 409
    _assert_no_leak(r.text)
