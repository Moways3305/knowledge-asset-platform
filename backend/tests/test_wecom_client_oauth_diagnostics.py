"""WeCom OAuth code exchange safe diagnostics."""

from __future__ import annotations

import logging

import httpx
import pytest

from app.services.wecom_client import WeComError, WeComOAuthClient


class _FakeAsyncClient:
    def __init__(self, identity_payload):
        self._identity_payload = identity_payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def get(self, url, params=None):
        if url.endswith("/cgi-bin/gettoken"):
            return httpx.Response(200, json={"errcode": 0, "access_token": "token-secret"})
        assert url.endswith("/cgi-bin/auth/getuserinfo")
        return httpx.Response(200, json=self._identity_payload)


def _install_httpx(monkeypatch, identity_payload):
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *_args, **_kwargs: _FakeAsyncClient(identity_payload)
    )


def _client() -> WeComOAuthClient:
    return WeComOAuthClient(
        corp_id="corp-a",
        agent_id="1000014",
        app_secret="app-secret",
        redirect_uri="https://kap.example/auth/wecom/callback",
        base_url="https://qyapi.weixin.qq.com",
    )


def _oauth_record(caplog):
    records = [r for r in caplog.records if getattr(r, "operation", None) == "oauth_exchange"]
    assert len(records) == 1
    return records[0]


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"errcode": 0, "userid": "u1"}, "has_userid"),
        ({"errcode": 0, "UserId": "u1"}, "has_UserId"),
    ],
)
async def test_exchange_code_success_logs_safe_identity_metadata(
    monkeypatch, caplog, payload, field
):
    _install_httpx(monkeypatch, payload)
    caplog.set_level(logging.INFO, logger="app.services.wecom_client")

    identity = await _client().exchange_code("oauth-code-secret")

    assert identity.wecom_user_id == "u1"
    record = _oauth_record(caplog)
    assert record.status == 200
    assert record.errcode == 0
    assert getattr(record, field) is True
    assert "u1" not in caplog.text
    assert "oauth-code-secret" not in caplog.text
    assert "token-secret" not in caplog.text


async def test_exchange_code_openid_without_userid_fails_and_logs_shape(monkeypatch, caplog):
    _install_httpx(monkeypatch, {"errcode": 0, "openid": "o1"})
    caplog.set_level(logging.INFO, logger="app.services.wecom_client")

    with pytest.raises(WeComError) as exc:
        await _client().exchange_code("oauth-code-openid")

    assert exc.value.code == "wecom_userinfo_failed"
    record = _oauth_record(caplog)
    assert record.errcode == 0
    assert record.has_openid is True
    assert record.has_userid is False
    assert record.has_UserId is False
    assert "o1" not in caplog.text
    assert "oauth-code-openid" not in caplog.text
    assert "token-secret" not in caplog.text


async def test_exchange_code_nonzero_errcode_logs_code_without_errmsg(monkeypatch, caplog):
    _install_httpx(
        monkeypatch,
        {"errcode": 40014, "errmsg": "invalid access_token SECRET-LIKE"},
    )
    caplog.set_level(logging.INFO, logger="app.services.wecom_client")

    with pytest.raises(WeComError) as exc:
        await _client().exchange_code("oauth-code-bad")

    assert exc.value.code == "wecom_userinfo_failed"
    record = _oauth_record(caplog)
    assert record.errcode == 40014
    assert record.has_userid is False
    assert record.has_UserId is False
    assert "errmsg" not in caplog.text
    assert "SECRET-LIKE" not in caplog.text
    assert "oauth-code-bad" not in caplog.text
    assert "token-secret" not in caplog.text


async def test_exchange_code_string_errcode_must_be_numeric_to_log(monkeypatch, caplog):
    _install_httpx(
        monkeypatch,
        {"errcode": "SECRET-LIKE", "errmsg": "invalid access_token SECRET-LIKE"},
    )
    caplog.set_level(logging.INFO, logger="app.services.wecom_client")

    with pytest.raises(WeComError) as exc:
        await _client().exchange_code("oauth-code-string-errcode")

    assert exc.value.code == "wecom_userinfo_failed"
    record = _oauth_record(caplog)
    assert record.errcode is None
    assert record.has_userid is False
    assert record.has_UserId is False
    assert "SECRET-LIKE" not in caplog.text
    assert "errmsg" not in caplog.text
    assert "oauth-code-string-errcode" not in caplog.text
    assert "token-secret" not in caplog.text
