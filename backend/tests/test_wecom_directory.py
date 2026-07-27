"""WeCom 微盘目录浏览测试。

覆盖：治理身份可操作、顾问拒绝；未配置安全 503；spaces/directories 只回安全字段；目录归一只留文件夹；
非法 ref 安全失败；选择器生成的 directory_ref 可直接用于现有 create config；上游 leaky 错误不泄露。
归一静态方法（_to_spaces/_to_directories）直接单测（不打网络）。
"""

from __future__ import annotations

import pytest

from app.main import app
from app.seed.dev_seed import USER_ADMIN_ONLY, USER_BOSS, USER_CONSULTANT, USER_DIRECTOR
from app.services.wecom_client import (
    WeComDriveClient,
    WeComDriveDirectory,
    WeComDriveSpace,
    WeComError,
    get_wecom_drive_client,
)

SPACES = "/api/v1/admin/wecom-scan/drive/spaces"
DIRS = "/api/v1/admin/wecom-scan/drive/directories"
CONFIGS = "/api/v1/admin/wecom-scan/configs"

# 任何响应都不得出现的敏感 token。
_FORBIDDEN = [
    "access_token",
    "app_secret",
    "cookie",
    "download_url",
    "fileid",
    "file_id",
    "raw_payload",
    "sk-",
]


def _hdr(u):
    return {"X-Dev-User-Id": str(u)}


class FakeDrive:
    """fake 微盘 client：返回安全 DTO；可模拟 leaky 错误。"""

    def __init__(self, *, leaky: bool = False):
        self.leaky = leaky

    async def list_spaces(self):
        if self.leaky:
            raise WeComError(
                "wecom_api_40058", "errmsg access_token=XYZ download_url=http://x cookie=c fileid=F"
            )
        return [
            WeComDriveSpace(space_ref="sp-1", name="交付空间"),
            WeComDriveSpace(space_ref="sp-2", name="售前空间"),
        ]

    async def list_directories(self, space_ref, parent_ref=None):
        if self.leaky:
            raise WeComError("wecom_api_40058", "errmsg access_token=XYZ download_url=http://x")
        base = f"spaceid:{space_ref};fatherid:"
        return [
            WeComDriveDirectory(
                directory_ref=base + "d10", name="客户A", parent_ref=parent_ref, has_children=True
            ),
            WeComDriveDirectory(
                directory_ref=base + "d11", name="客户B", parent_ref=parent_ref, has_children=False
            ),
        ]


def _install(drive):
    app.dependency_overrides[get_wecom_drive_client] = lambda: drive


# ---------------------------------------------------------------------------
# 归一静态方法（不打网络）
# ---------------------------------------------------------------------------
def test_to_spaces_safe():
    raw = [
        {"spaceid": "sp-1", "space_name": "S1", "access_token": "T", "download_url": "http://x"},
        {"no_id": True},  # 无 id → 丢弃
    ]
    spaces = WeComDriveClient._to_spaces(raw)
    assert [s.space_ref for s in spaces] == ["sp-1"]
    assert spaces[0].name == "S1"


def test_to_directories_filters_files_only_folders():
    raw = [
        {"fileid": "d1", "file_name": "目录1", "file_type": 1},  # 文件夹
        {
            "fileid": "f1",
            "file_name": "报告.pdf",
            "file_type": 2,
            "download_url": "http://x",
            "cookie_value": "c",
        },  # 普通文件 → 丢弃
        {"fileid": "d2", "file_name": "目录2", "is_dir": True},  # 文件夹（兼容 is_dir）
    ]
    dirs = WeComDriveClient._to_directories("sp-1", raw)
    names = [d.name for d in dirs]
    assert names == ["目录1", "目录2"]  # 普通文件不出现
    assert dirs[0].directory_ref == "spaceid:sp-1;fatherid:d1"
    # 普通文件名 / 下载 url / cookie 不出现在任何 directory_ref / name。
    blob = str([(d.directory_ref, d.name) for d in dirs])
    for token in ["报告.pdf", "http://x", "cookie", "f1"]:
        assert token not in blob


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------
async def test_admin_can_browse(client):
    _install(FakeDrive())
    try:
        s = await client.get(SPACES, headers=_hdr(USER_ADMIN_ONLY))
        assert s.status_code == 200
        assert {i["space_ref"] for i in s.json()["items"]} == {"sp-1", "sp-2"}
        d = await client.get(f"{DIRS}?space_ref=sp-1", headers=_hdr(USER_ADMIN_ONLY))
        assert d.status_code == 200
        assert d.json()["space_ref"] == "sp-1"
        assert d.json()["items"][0]["directory_ref"] == "spaceid:sp-1;fatherid:d10"
    finally:
        app.dependency_overrides.pop(get_wecom_drive_client, None)


@pytest.mark.parametrize("user", [USER_BOSS, USER_DIRECTOR])
async def test_governance_can_browse(client, user):
    _install(FakeDrive())
    try:
        s = await client.get(SPACES, headers=_hdr(user))
        assert s.status_code == 200
        d = await client.get(f"{DIRS}?space_ref=sp-1", headers=_hdr(user))
        assert d.status_code == 200
    finally:
        app.dependency_overrides.pop(get_wecom_drive_client, None)


async def test_consultant_cannot_browse(client):
    _install(FakeDrive())
    try:
        s = await client.get(SPACES, headers=_hdr(USER_CONSULTANT))
        assert s.status_code == 403
        assert s.json()["detail"]["denied_reason"] == "wecom_scan_operator_required"
    finally:
        app.dependency_overrides.pop(get_wecom_drive_client, None)


# ---------------------------------------------------------------------------
# 未配置 / 非法 ref / leaky
# ---------------------------------------------------------------------------
async def test_not_configured_safe_503(client):
    # 不 override → 默认 Null drive（wecom 未配置）。
    s = await client.get(SPACES, headers=_hdr(USER_ADMIN_ONLY))
    assert s.status_code == 503
    detail = s.json()["detail"]
    assert detail["denied_reason"] == "wecom_not_configured"
    assert "WECOM_CORP_ID" in detail["missing_config"]
    for token in _FORBIDDEN:
        assert token not in s.text


async def test_invalid_space_ref_422(client):
    _install(FakeDrive())
    try:
        # 传入整串 directory_path 当 space_ref → 422（space_ref 必须裸 spaceid）。
        r = await client.get(
            f"{DIRS}?space_ref=spaceid:sp-1;fatherid:d1", headers=_hdr(USER_ADMIN_ONLY)
        )
        assert r.status_code == 422
        assert r.json()["detail"]["denied_reason"] == "wecom_invalid_space"
    finally:
        app.dependency_overrides.pop(get_wecom_drive_client, None)


async def test_invalid_parent_ref_422(client):
    _install(FakeDrive())
    try:
        r = await client.get(
            f"{DIRS}?space_ref=sp-1&parent_ref=not-a-valid-ref", headers=_hdr(USER_ADMIN_ONLY)
        )
        assert r.status_code == 422
        assert r.json()["detail"]["denied_reason"] == "wecom_invalid_directory_ref"
    finally:
        app.dependency_overrides.pop(get_wecom_drive_client, None)


async def test_drill_with_parent_ref(client):
    _install(FakeDrive())
    try:
        r = await client.get(
            f"{DIRS}?space_ref=sp-1&parent_ref=spaceid:sp-1;fatherid:d10",
            headers=_hdr(USER_ADMIN_ONLY),
        )
        assert r.status_code == 200
        assert r.json()["items"][0]["directory_ref"].startswith("spaceid:sp-1;fatherid:")
    finally:
        app.dependency_overrides.pop(get_wecom_drive_client, None)


async def test_upstream_leaky_error_not_exposed(client):
    _install(FakeDrive(leaky=True))
    try:
        s = await client.get(SPACES, headers=_hdr(USER_ADMIN_ONLY))
        assert s.status_code == 502
        assert s.json()["detail"]["denied_reason"] == "wecom_api_40058"
        for token in _FORBIDDEN + ["XYZ", "http://x"]:
            assert token not in s.text
        d = await client.get(f"{DIRS}?space_ref=sp-1", headers=_hdr(USER_ADMIN_ONLY))
        assert d.status_code == 502
        for token in _FORBIDDEN + ["XYZ", "http://x"]:
            assert token not in d.text
    finally:
        app.dependency_overrides.pop(get_wecom_drive_client, None)


# ---------------------------------------------------------------------------
# 保存兼容：选择器生成的 directory_ref 可直接用于现有 create config
# ---------------------------------------------------------------------------
async def test_directory_ref_usable_in_create_config(client, db_session):
    from app.seed.dev_seed import USER_CONSULTANT as OWNER

    body = {
        "name": "选择器配置",
        "directory_path": "spaceid:sp-1;fatherid:d10",
        "target_scope": "personal",
        "task_owner_user_id": str(OWNER),
        "enabled": True,
    }
    r = await client.post(CONFIGS, headers=_hdr(USER_ADMIN_ONLY), json=body)
    assert r.status_code == 201, r.text
    assert r.json()["directory_path"] == "spaceid:sp-1;fatherid:d10"


async def test_legacy_directory_path_still_valid(client):
    # 旧手填串（无 fatherid）仍可保存。
    body = {
        "name": "旧配置",
        "directory_path": "spaceid:legacy-space;fatherid:",
        "target_scope": "personal",
        "task_owner_user_id": str(USER_CONSULTANT),
        "enabled": True,
    }
    r = await client.post(CONFIGS, headers=_hdr(USER_ADMIN_ONLY), json=body)
    assert r.status_code == 201, r.text
    assert r.json()["directory_path"].startswith("spaceid:legacy-space")
