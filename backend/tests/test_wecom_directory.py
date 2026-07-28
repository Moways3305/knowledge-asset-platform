from __future__ import annotations

import json

import httpx
import pytest

from app.services.wecom_client import WeComDriveClient, WeComError
from app.services.wecom_scan import _wrap_wecom


def _response(status: int, payload) -> httpx.Response:
    return httpx.Response(
        status,
        json=payload,
        request=httpx.Request("POST", "https://example.invalid"),
    )


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"errcode": 40014, "errmsg": "token=secret"}, "wecom_token_rejected"),
        ({"errcode": 48002, "errmsg": "raw permission detail"}, "wecom_drive_permission_denied"),
        ({"errcode": 999999, "errmsg": "raw upstream detail"}, "wecom_drive_upstream_rejected"),
    ],
)
def test_drive_business_failures_use_stable_safe_categories(payload, code):
    with pytest.raises(WeComError) as caught:
        WeComDriveClient._check(payload, stage="file_list")
    assert caught.value.code == code
    assert caught.value.stage == "file_list"
    assert payload["errmsg"] not in caught.value.message


def test_drive_http_and_bad_json_failures_are_safe():
    with pytest.raises(WeComError, match="wecom_drive_http_error"):
        WeComDriveClient._response_json(_response(503, {"secret": "raw"}), stage="file_list")
    response = httpx.Response(
        200,
        content=b"token=secret",
        request=httpx.Request("POST", "https://example.invalid"),
    )
    with pytest.raises(WeComError, match="wecom_drive_bad_response") as caught:
        WeComDriveClient._response_json(response, stage="file_list")
    assert "token=secret" not in caught.value.message


def test_safe_failure_log_contains_categories_but_not_raw_payload(caplog):
    exc = WeComError(
        "wecom_drive_permission_denied",
        "Authorization=Bearer secret download_url=https://secret.invalid",
        stage="file_list",
        http_status=403,
        upstream_errcode=48002,
    )
    response = _wrap_wecom(exc, trace_id="trace-safe")
    assert response.status_code == 502
    combined = " ".join(record.getMessage() for record in caplog.records)
    assert "Authorization" not in combined
    assert "secret.invalid" not in combined
    record = caplog.records[-1]
    assert record.stage == "file_list"
    assert record.safe_code == "wecom_drive_permission_denied"
    assert record.http_category == "4xx"
    assert record.upstream_errcode == 48002
    assert record.trace_id == "trace-safe"


async def test_space_create_uses_official_contract_and_manager_only(monkeypatch):
    requests: list[tuple[str, dict]] = []

    async def handler(request: httpx.Request):
        if request.url.path.endswith("/gettoken"):
            return httpx.Response(200, json={"errcode": 0, "access_token": "server-token"})
        requests.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"errcode": 0, "spaceid": "server-space"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    client = WeComDriveClient(
        corp_id="corp",
        app_secret="secret",
        base_url="https://qyapi.weixin.qq.com",
    )
    result = await client.create_project_space(
        space_name="Alpha - 项目扫描空间",
        manager_user_ids=["manager-a"],
    )
    assert result == "server-space"
    assert requests == [
        (
            "/cgi-bin/wedrive/space_create",
            {
                "space_name": "Alpha - 项目扫描空间",
                "auth_info": [{"type": 1, "userid": "manager-a", "auth": 7}],
                "space_sub_type": 0,
            },
        )
    ]


async def test_file_listing_recurses_from_project_space_root(monkeypatch):
    seen_fathers: list[str] = []

    async def handler(request: httpx.Request):
        if request.url.path.endswith("/gettoken"):
            return httpx.Response(200, json={"errcode": 0, "access_token": "server-token"})
        body = json.loads(request.content)
        seen_fathers.append(body["fatherid"])
        if body["fatherid"] == "":
            files = [
                {"fileid": "folder-1", "file_name": "子目录", "file_type": 1},
                {"fileid": "file-root", "file_name": "root.txt", "file_type": 2},
            ]
        else:
            files = [{"fileid": "file-child", "file_name": "child.txt", "file_type": 2}]
        return httpx.Response(200, json={"errcode": 0, "file_list": files, "has_more": False})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    client = WeComDriveClient(
        corp_id="corp",
        app_secret="secret",
        base_url="https://qyapi.weixin.qq.com",
    )
    files = await client.list_files("spaceid:server-space;fatherid:")
    assert seen_fathers == ["", "folder-1"]
    assert [item.name for item in files] == ["root.txt", "child.txt"]
