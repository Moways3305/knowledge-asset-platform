"""生产部署守卫与安全烟测测试。

覆盖：
- 会话 / OAuth state cookie 的 Secure 生产守卫（prod 强制 Secure，本地不强制）；
- `/health/config` 生产就绪诊断（blocker / warning 只回安全项名）；
- trace_id 跨 HTTP → 后台作业 → WeKnora / 审计的链路连续性；
- 响应 / 审计 / 脚本输出不泄露明文 token / state / secret / 内部 id。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.config import Settings, session_cookie_secure, session_cookie_secure_misconfigured
from app.main import app
from app.models.audit import AuditEvent
from app.models.indexing_job import IndexingOperationJob
from app.seed.dev_seed import (
    DEV_PASSWORD,
    USER_ADMIN_ONLY,
    USER_CONSULTANT,
)

LOGIN = "/api/v1/auth/login"
WECOM_START = "/api/v1/auth/wecom/start"
WECOM_CALLBACK = "/api/v1/auth/wecom/callback"
CONFIG = "/health/config"
UPLOAD = "/api/v1/ingest/upload"
RETRY = "/admin/ops/indexing/retry"

BOSS_EMAIL = "boss.c@dev.local"


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


def _set_cookies(resp):
    return resp.headers.get_list("set-cookie")


def _cookie_for(resp, name):
    for c in _set_cookies(resp):
        if c.startswith(name + "="):
            return c
    return None


# ---------------------------------------------------------------------------
# 1. Cookie Secure 生产守卫
# ---------------------------------------------------------------------------
def test_session_cookie_secure_helper_rules():
    """prod 强制 True（即使显式 false）；非 prod 读配置，未配置默认 False。"""
    assert session_cookie_secure(Settings(app_env="prod")) is True
    assert session_cookie_secure(Settings(app_env="prod", session_cookie_secure=False)) is True
    assert session_cookie_secure(Settings(app_env="local")) is False
    assert session_cookie_secure(Settings(app_env="local", session_cookie_secure=True)) is True
    # 显式 prod + false → 配置诊断标记 misconfigured（运行时仍被强制安全）。
    assert (
        session_cookie_secure_misconfigured(Settings(app_env="prod", session_cookie_secure=False))
        is True
    )
    assert session_cookie_secure_misconfigured(Settings(app_env="prod")) is False
    assert (
        session_cookie_secure_misconfigured(Settings(app_env="local", session_cookie_secure=False))
        is False
    )


async def test_login_cookie_not_secure_in_local(client):
    """本地登录 Set-Cookie 不强制 Secure（便于 http://localhost）。"""
    resp = await client.post(LOGIN, json={"email": BOSS_EMAIL})
    assert resp.status_code == 200, resp.text
    cookie = _cookie_for(resp, "kap_session")
    assert cookie is not None
    assert "secure" not in cookie.lower()
    # 明文 token 不进 JSON 响应体。
    assert "kap_session" not in resp.text


async def test_login_cookie_secure_in_prod(client, monkeypatch):
    """prod 密码登录 Set-Cookie 必含 Secure。"""
    monkeypatch.setattr("app.api.auth.get_settings", lambda: Settings(app_env="prod"))
    resp = await client.post(LOGIN, json={"email": BOSS_EMAIL, "password": DEV_PASSWORD})
    assert resp.status_code == 200, resp.text
    cookie = _cookie_for(resp, "kap_session")
    assert cookie is not None
    assert "secure" in cookie.lower()
    # 明文 token / 密码不进 JSON 响应体。
    assert DEV_PASSWORD not in resp.text


class _FakeOAuth:
    """fake 企微 OAuth 客户端：生成安全 URL（不含 secret），按 code 换取已绑定身份。"""

    corp_id = "test_corp"

    def build_authorize_url(self, *, state: str, mode: str = "client") -> str:
        # 真实实现含 corp_id/redirect/state，但**绝不含 app_secret**。
        return f"https://open.weixin.qq.com/connect/oauth2/authorize?state={state}"

    async def exchange_code(self, code: str):
        from app.services.wecom_client import WeComIdentity

        return WeComIdentity(wecom_user_id="ww_consultant_a")

    async def get_member_status(self, wecom_user_id: str):
        from app.services.wecom_client import WeComMemberStatus

        return WeComMemberStatus(wecom_user_id, True, "active", "企微成员有效")


@pytest.fixture
def _fake_oauth():
    from app.services.wecom_client import get_wecom_oauth_client

    app.dependency_overrides[get_wecom_oauth_client] = lambda: _FakeOAuth()
    yield
    app.dependency_overrides.pop(get_wecom_oauth_client, None)


async def test_wecom_start_state_cookie_secure_in_prod(client, monkeypatch, _fake_oauth):
    """prod 下 OAuth start 的 kap_oauth_state cookie 必含 Secure，且 state 不进 JSON。"""
    monkeypatch.setattr("app.api.auth.get_settings", lambda: Settings(app_env="prod"))
    resp = await client.get(WECOM_START)
    assert resp.status_code == 200, resp.text
    cookie = _cookie_for(resp, "kap_oauth_state")
    assert cookie is not None
    assert "secure" in cookie.lower()
    # CSRF 防护的 state 副本走 httpOnly cookie（authorize_url 里按 OAuth 协议带 state 属正常）。
    assert "httponly" in cookie.lower()


async def test_wecom_callback_session_cookie_secure_in_prod(client, monkeypatch, _fake_oauth):
    """prod 下 OAuth callback 成功换取后下发的会话 cookie 必含 Secure。"""
    monkeypatch.setattr("app.api.auth.get_settings", lambda: Settings(app_env="prod"))
    state = "st-prod-123"
    resp = await client.get(
        WECOM_CALLBACK + f"?code=code-xyz&state={state}",
        headers={"Cookie": f"kap_oauth_state={state}"},
    )
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"] == "/"
    cookie = _cookie_for(resp, "kap_session")
    assert cookie is not None
    assert "secure" in cookie.lower()
    # code / state 绝不进响应体。
    assert "code-xyz" not in resp.text
    assert state not in resp.text


# ---------------------------------------------------------------------------
# 2. /health/config 生产就绪诊断
# ---------------------------------------------------------------------------
_SECRET_TOKENS = [
    "devpassword",
    "postgresql+asyncpg",
    "redis://",
    "sk-",
    "Bearer",
    "api_key",
    "jwt_secret",
    "token_hash",
    "storage_ref",
]


def _assert_no_secret(text):
    for t in _SECRET_TOKENS:
        assert t not in text, f"config 响应不应泄露 {t}"


async def test_config_non_prod_not_production_ready_but_no_blockers(client):
    """非 prod：production_ready=False，blockers 为空（本地 eager 不算失败）。"""
    r = await client.get(CONFIG)
    assert r.status_code == 200
    body = r.json()
    assert body["production_ready"] is False
    assert body["production_blockers"] == []
    assert "production_warnings" in body
    _assert_no_secret(r.text)


async def test_config_prod_eager_is_blocker(client, monkeypatch):
    """prod + eager=true → blocker 含 CELERY_TASK_ALWAYS_EAGER，production_ready=False。"""
    monkeypatch.setattr(
        "app.api.ops.get_settings",
        lambda: Settings(app_env="prod", celery_task_always_eager=True),
    )
    r = await client.get(CONFIG)
    assert r.status_code == 200
    body = r.json()
    assert "CELERY_TASK_ALWAYS_EAGER" in body["production_blockers"]
    assert body["production_ready"] is False
    _assert_no_secret(r.text)


async def test_config_prod_insecure_cookie_is_blocker(client, monkeypatch):
    """prod + 显式 SESSION_COOKIE_SECURE=false → blocker 含 SESSION_COOKIE_SECURE。"""
    monkeypatch.setattr(
        "app.api.ops.get_settings",
        lambda: Settings(
            app_env="prod", celery_task_always_eager=False, session_cookie_secure=False
        ),
    )
    r = await client.get(CONFIG)
    body = r.json()
    assert "SESSION_COOKIE_SECURE" in body["production_blockers"]
    _assert_no_secret(r.text)


async def test_config_prod_weknora_missing_default_embedding_blocker(client, monkeypatch):
    """PBC-38：prod + WeKnora 启用但未配置平台默认 embedding（DB 无行）→ blocker
    含 WEKNORA_DEFAULT_EMBEDDING_MODEL；旧 WEKNORA_EMBEDDING_MODEL_ID 不再是 blocker。"""
    monkeypatch.setattr("app.api.ops.weknora_enabled", lambda: True)
    monkeypatch.setattr(
        "app.api.ops.get_settings",
        lambda: Settings(
            app_env="prod",
            celery_task_always_eager=False,
            session_cookie_secure=True,
            weknora_embedding_model_id="",  # legacy 留空，已不再作为 blocker
            weknora_model_ref_secret="",
        ),
    )
    r = await client.get(CONFIG)
    body = r.json()
    assert "WEKNORA_DEFAULT_EMBEDDING_MODEL" in body["production_blockers"]
    assert "WEKNORA_DEFAULT_KNOWLEDGE_QA_MODEL" in body["production_blockers"]
    assert "WEKNORA_EMBEDDING_MODEL_ID" not in body["production_blockers"]
    assert "WEKNORA_DEFAULT_EMBEDDING_MODEL" in body["missing_config"]
    assert "WEKNORA_DEFAULT_KNOWLEDGE_QA_MODEL" in body["missing_config"]
    assert "WEKNORA_MODEL_REF_SECRET" in body["production_blockers"]
    assert body["production_ready"] is False
    _assert_no_secret(r.text)


async def test_config_prod_weknora_default_configured_no_blocker(client, db_session, monkeypatch):
    """PBC-38：prod + WeKnora 启用 + 平台默认 embedding 已配置（DB）→ 不报该 blocker；
    即便 WEKNORA_EMBEDDING_MODEL_ID 为空也不报旧 blocker；响应不泄露真实 model_id。"""
    from app.services import weknora_defaults

    await weknora_defaults.set_defaults(
        db_session,
        embedding_model_id="emb-real-secret-id",
        rerank_model_id=None,
        chat_model_id="chat-real-secret-id",
        multimodal_id=None,
        updated_by=None,
    )
    await db_session.commit()
    monkeypatch.setattr("app.api.ops.weknora_enabled", lambda: True)
    monkeypatch.setattr(
        "app.api.ops.get_settings",
        lambda: Settings(
            app_env="prod",
            celery_task_always_eager=False,
            session_cookie_secure=True,
            auth_attempt_hash_secret="real",
            csrf_token_secret="real",
            weknora_embedding_model_id="",  # legacy 空，但 DB 默认已配 → 不应报阻断
            weknora_model_ref_secret="real-ref",
        ),
    )
    r = await client.get(CONFIG)
    body = r.json()
    assert "WEKNORA_DEFAULT_EMBEDDING_MODEL" not in body["production_blockers"]
    assert "WEKNORA_DEFAULT_KNOWLEDGE_QA_MODEL" not in body["production_blockers"]
    assert "WEKNORA_EMBEDDING_MODEL_ID" not in body["production_blockers"]
    assert "WEKNORA_DEFAULT_EMBEDDING_MODEL" not in body["missing_config"]
    assert "WEKNORA_DEFAULT_KNOWLEDGE_QA_MODEL" not in body["missing_config"]
    # /health/config 只回配置项名，绝不回真实 model_id。
    assert "emb-real-secret-id" not in r.text
    assert "chat-real-secret-id" not in r.text
    _assert_no_secret(r.text)


async def test_config_prod_ready_when_clean(client, monkeypatch):
    """prod + 无阻断项（worker 真实、cookie secure、外部集成关闭）→ production_ready=True。"""
    monkeypatch.setattr("app.api.ops.weknora_enabled", lambda: False)
    monkeypatch.setattr(
        "app.api.ops.get_settings",
        lambda: Settings(
            app_env="prod",
            celery_task_always_eager=False,
            session_cookie_secure=True,
            auth_attempt_hash_secret="real-secret",
            csrf_token_secret="real-csrf",
        ),
    )
    r = await client.get(CONFIG)
    body = r.json()
    assert body["production_blockers"] == []
    assert body["production_ready"] is True
    _assert_no_secret(r.text)


async def test_config_onlyoffice_origin_mismatch_is_safe_blocker(client, monkeypatch):
    monkeypatch.setattr("app.api.ops.onlyoffice_enabled", lambda: True)
    monkeypatch.setattr(
        "app.api.ops.get_settings",
        lambda: Settings(
            app_env="prod",
            celery_task_always_eager=False,
            session_cookie_secure=True,
            auth_attempt_hash_secret="configured",
            csrf_token_secret="configured",
            onlyoffice_enabled=True,
            onlyoffice_document_server_url="https://browser-docs.invalid",
            onlyoffice_origin="https://different-docs.invalid",
            onlyoffice_internal_base_url="https://controlled-fetch.invalid",
            onlyoffice_jwt_secret="configured",
        ),
    )

    response = await client.get(CONFIG)
    body = response.json()

    assert "ONLYOFFICE_ORIGIN_MISMATCH" in body["production_blockers"]
    assert body["integrations"]["onlyoffice_config"] == {
        "document_server_origin_valid": True,
        "internal_base_configured": True,
        "csp_origin_valid": True,
        "browser_origin_matches": False,
    }
    assert "browser-docs.invalid" not in response.text
    assert "different-docs.invalid" not in response.text
    assert "controlled-fetch.invalid" not in response.text
    _assert_no_secret(response.text)


async def test_config_onlyoffice_origins_match_without_exposing_values(client, monkeypatch):
    monkeypatch.setattr("app.api.ops.onlyoffice_enabled", lambda: True)
    monkeypatch.setattr(
        "app.api.ops.get_settings",
        lambda: Settings(
            onlyoffice_enabled=True,
            onlyoffice_document_server_url="https://browser-docs.invalid/",
            onlyoffice_origin="https://browser-docs.invalid",
            onlyoffice_internal_base_url="https://controlled-fetch.invalid",
            onlyoffice_jwt_secret="configured",
        ),
    )

    response = await client.get(CONFIG)
    status = response.json()["integrations"]["onlyoffice_config"]

    assert status["document_server_origin_valid"] is True
    assert status["internal_base_configured"] is True
    assert status["csp_origin_valid"] is True
    assert status["browser_origin_matches"] is True
    assert "browser-docs.invalid" not in response.text
    assert "controlled-fetch.invalid" not in response.text


def test_onlyoffice_csp_uses_one_explicit_origin_without_unsafe_expansion():
    root = Path(__file__).resolve().parents[2]
    nginx = (root / "deploy" / "nginx.conf.template").read_text(encoding="utf-8")
    dockerfile = (root / "Dockerfile.frontend").read_text(encoding="utf-8")

    csp_lines = [line for line in nginx.splitlines() if "Content-Security-Policy" in line]
    assert len(csp_lines) == 2
    for line in csp_lines:
        assert "script-src 'self' ${ONLYOFFICE_ORIGIN}" in line
        assert "frame-src 'self' ${ONLYOFFICE_ORIGIN}" in line
        assert "connect-src 'self' ${ONLYOFFICE_ORIGIN}" in line
        assert "unsafe-eval" not in line
        assert " *" not in line
    assert "NGINX_ENVSUBST_FILTER=ONLYOFFICE_ORIGIN" in dockerfile
    assert "19-validate-onlyoffice-origin.sh" in dockerfile


def test_upload_proxy_limits_are_scoped_and_aligned_at_both_nginx_layers():
    root = Path(__file__).resolve().parents[2]
    inner = (root / "deploy" / "nginx.conf.template").read_text(encoding="utf-8")
    outer_path = root / "deploy" / "nginx-host-upload-rules.conf"
    installer_path = root / "deploy" / "install-host-nginx.sh"
    runbook = (root / "docs" / "deployment" / "PRODUCTION_DEPLOYMENT_RUNBOOK.md").read_text(
        encoding="utf-8"
    )
    outer = outer_path.read_text(encoding="utf-8")
    installer = installer_path.read_text(encoding="utf-8")

    assert inner.count("client_max_body_size 32m;") == 2
    assert outer.count("client_max_body_size 32m;") == 2
    for config in (inner, outer):
        assert "location = /api/v1/ingest/upload" in config
        assert "location ^~ /api/v1/ingest/upload-sessions" in config
        assert config.count("client_body_timeout 120s;") == 2
        assert config.count("proxy_send_timeout 120s;") == 2
        assert config.count("proxy_read_timeout 120s;") == 2
        assert "client_max_body_size 200m" not in config
    assert "nginx-host-upload-rules.conf" in installer
    assert "--check|--install|--verify" in installer
    assert "/etc/nginx/sites-available/kap" in installer
    assert "/etc/nginx/snippets/kap-upload-rules.conf" in installer
    assert "nginx -t" in installer
    assert "nginx -s reload" in installer
    assert "install-host-nginx.sh" in runbook
    assert "nginx-host-upload-rules.conf" in runbook


def test_host_nginx_installer_is_read_only_by_default_and_idempotent(tmp_path):
    shell = shutil.which("sh")
    if shell is None:
        pytest.skip("POSIX sh is required for the host-nginx installer integration test")

    def shell_path(path: Path) -> str:
        if os.name != "nt":
            return str(path)
        converted = subprocess.run(
            [shell, "-c", 'cygpath -u "$1"', "sh", str(path)],
            capture_output=True,
            text=True,
            check=True,
        )
        return converted.stdout.strip()

    root = Path(__file__).resolve().parents[2]
    installer = root / "deploy" / "install-host-nginx.sh"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_nginx = fake_bin / "nginx"
    fake_nginx.write_text(
        "#!/bin/sh\nexit 0\n",
        encoding="utf-8",
    )
    fake_nginx.chmod(0o755)
    site = tmp_path / "kap.conf"
    snippet_dir = tmp_path / "snippets"
    snippet_dir.mkdir()
    snippet = snippet_dir / "kap-upload-rules.conf"
    original = """server {
    listen 443 ssl;
    server_name kap.example.com;
    ssl_certificate /etc/letsencrypt/live/kap/fullchain.pem;
    location = /.well-known/wecom-verification.txt { return 200 'proof'; }
    location /onlyoffice/ { proxy_pass https://127.0.0.1:8443; }
    location / { proxy_pass http://127.0.0.1:18080; }
}
"""
    site.write_text(original, encoding="utf-8")

    env = {
        **os.environ,
        "PATH": (
            f"{shell_path(fake_bin)}:/usr/bin:/bin"
            if os.name == "nt"
            else f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}"
        ),
        "KAP_SERVER_NAME": "kap.example.com",
        "KAP_NGINX_SITE_PATH": shell_path(site),
        "KAP_NGINX_SNIPPET_PATH": shell_path(snippet),
        "KAP_NGINX_INCLUDE_PATH": shell_path(snippet),
    }

    checked = subprocess.run(
        [shell, shell_path(installer), "--check"], env=env, capture_output=True, text=True
    )
    assert checked.returncode == 0, checked.stderr
    assert site.read_text(encoding="utf-8") == original
    assert not snippet.exists()

    first = subprocess.run(
        [shell, shell_path(installer), "--install"], env=env, capture_output=True, text=True
    )
    assert first.returncode == 0, first.stderr
    installed_site = site.read_text(encoding="utf-8")
    assert installed_site.count(f"include {shell_path(snippet)};") == 1
    assert "127.0.0.1:8443" in installed_site
    assert "wecom-verification" in installed_site
    assert "ssl_certificate /etc/letsencrypt" in installed_site
    assert snippet.read_text(encoding="utf-8").count("client_max_body_size 32m;") == 2

    second = subprocess.run(
        [shell, shell_path(installer), "--install"], env=env, capture_output=True, text=True
    )
    assert second.returncode == 0, second.stderr
    assert site.read_text(encoding="utf-8") == installed_site

    verified = subprocess.run(
        [shell, shell_path(installer), "--verify"], env=env, capture_output=True, text=True
    )
    assert verified.returncode == 0, verified.stderr
    assert "KAP_UPLOAD_RULES_BEGIN" in verified.stdout

    missing_env = {**env, "KAP_SERVER_NAME": "missing.example.com"}
    before_missing_check = site.read_text(encoding="utf-8")
    missing = subprocess.run(
        [shell, shell_path(installer), "--check"],
        env=missing_env,
        capture_output=True,
        text=True,
    )
    assert missing.returncode != 0
    assert "manual" in missing.stderr.lower() or "人工" in missing.stderr
    assert site.read_text(encoding="utf-8") == before_missing_check


def test_host_nginx_installer_restores_site_and_snippet_when_reload_fails(tmp_path):
    shell = shutil.which("sh")
    if shell is None:
        pytest.skip("POSIX sh is required for the host-nginx installer integration test")

    def shell_path(path: Path) -> str:
        if os.name != "nt":
            return str(path)
        converted = subprocess.run(
            [shell, "-c", 'cygpath -u "$1"', "sh", str(path)],
            capture_output=True,
            text=True,
            check=True,
        )
        return converted.stdout.strip()

    root = Path(__file__).resolve().parents[2]
    installer = root / "deploy" / "install-host-nginx.sh"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_nginx = fake_bin / "nginx"
    reload_log = tmp_path / "reload.log"
    fake_nginx.write_text(
        """#!/bin/sh
if [ "${1:-}" = "-s" ] && [ "${2:-}" = "reload" ]; then
    if [ ! -f "$FAKE_NGINX_RELOAD_LOG" ]; then
        echo first > "$FAKE_NGINX_RELOAD_LOG"
        exit 1
    fi
    echo rollback >> "$FAKE_NGINX_RELOAD_LOG"
fi
exit 0
""",
        encoding="utf-8",
    )
    fake_nginx.chmod(0o755)
    site = tmp_path / "kap.conf"
    snippet_dir = tmp_path / "snippets"
    snippet_dir.mkdir()
    snippet = snippet_dir / "kap-upload-rules.conf"
    original_site = """server {
    server_name kap.example.com;
    location / { proxy_pass http://127.0.0.1:18080; }
}
"""
    site.write_text(original_site, encoding="utf-8")
    snippet.write_text("# previous upload rules\n", encoding="utf-8")

    result = subprocess.run(
        [shell, shell_path(installer), "--install"],
        env={
            **os.environ,
            "PATH": (
                f"{shell_path(fake_bin)}:/usr/bin:/bin"
                if os.name == "nt"
                else f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}"
            ),
            "FAKE_NGINX_RELOAD_LOG": shell_path(reload_log),
            "KAP_SERVER_NAME": "kap.example.com",
            "KAP_NGINX_SITE_PATH": shell_path(site),
            "KAP_NGINX_SNIPPET_PATH": shell_path(snippet),
            "KAP_NGINX_INCLUDE_PATH": shell_path(snippet),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert site.read_text(encoding="utf-8") == original_site
    assert snippet.read_text(encoding="utf-8") == "# previous upload rules\n"
    assert reload_log.read_text(encoding="utf-8").splitlines() == ["first", "rollback"]
    assert not list(tmp_path.glob("kap.conf.new.*"))
    assert not list(tmp_path.glob("kap.conf.rollback.*"))
    assert "site and snippet restored and reloaded" in result.stderr


@pytest.mark.parametrize(
    "origin",
    [
        "https://docs.invalid https://extra.invalid",
        "https://docs.invalid; script-src *",
        "https://user@docs.invalid",
        "https://docs.invalid/path",
        "https://docs.invalid:70000",
        "javascript:alert(1)",
    ],
)
def test_onlyoffice_entrypoint_rejects_unsafe_csp_sources(origin):
    root = Path(__file__).resolve().parents[2]
    validator = root / "deploy" / "validate-onlyoffice-origin.sh"
    result = subprocess.run(
        ["sh", str(validator)],
        env={**os.environ, "ONLYOFFICE_ORIGIN": origin},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert origin not in result.stderr


@pytest.mark.parametrize("origin", ["", "https://docs.invalid", "http://127.0.0.1:8080"])
def test_onlyoffice_runtime_rendered_csp_contains_only_validated_origin(origin):
    root = Path(__file__).resolve().parents[2]
    validator = root / "deploy" / "validate-onlyoffice-origin.sh"
    template = (root / "deploy" / "nginx.conf.template").read_text(encoding="utf-8")
    result = subprocess.run(
        ["sh", str(validator)],
        env={**os.environ, "ONLYOFFICE_ORIGIN": origin},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    rendered = template.replace("${ONLYOFFICE_ORIGIN}", origin)
    csp_lines = [line for line in rendered.splitlines() if "Content-Security-Policy" in line]
    assert len(csp_lines) == 2
    for line in csp_lines:
        assert "${ONLYOFFICE_ORIGIN}" not in line
        assert f"script-src 'self' {origin}" in line
        assert f"frame-src 'self' {origin}" in line
        assert f"connect-src 'self' {origin}" in line
        assert "unsafe-eval" not in line
        assert " *" not in line


# ---------------------------------------------------------------------------
# 3. trace_id 跨 HTTP → 后台作业 → WeKnora / 审计
# ---------------------------------------------------------------------------
async def test_trace_id_flows_http_to_worker_audit_on_upload(client, db_session):
    """上传带 X-Trace-Id → 入库处理（eager worker）写审计沿用同一 trace_id。"""
    trace = "trc-prod-smoke"
    r = await client.post(
        UPLOAD,
        headers={**_hdr(USER_CONSULTANT), "X-Trace-Id": trace},
        files={"file": ("doc.txt", b"trace upload body", "text/plain")},
    )
    assert r.status_code == 200, r.text
    # 回声头沿用同一 trace_id。
    assert r.headers.get("X-Trace-Id") == trace
    # worker service 入库处理审计（ingest.ai_extracted / ingest.failed）使用同一 trace_id。
    events = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.trace_id == trace)))
        .scalars()
        .all()
    )
    actions = {e.action for e in events}
    assert any(a and a.startswith("ingest.") for a in actions), actions
    # 至少含入库处理产物之一（证明 HTTP → enqueue → worker → audit 同链路）。
    assert ("ingest.ai_extracted" in actions) or ("ingest.failed" in actions)


class _TraceWK:
    """记录每次 WeKnora 调用收到的 trace_id 的 fake（用于断言后台作业传递 trace）。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.upload_traces: list[str | None] = []
        self._kb = 0
        self._doc = 0

    async def create_kb(self, *, name, embedding_model_id, trace_id=None, **_):
        self._kb += 1
        return f"kb-{self._kb}"

    async def initialize_kb(self, kb_id, **_):
        return None

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
        return {"success": True}

    async def get_initialization_config(self, kb_id, *, trace_id=None):
        return {}

    async def list_models(self, *, trace_id=None):
        return [
            {
                "id": "test-embed",
                "name": "text-embedding-test",
                "type": "Embedding",
                "source": "remote",
                "parameters": {"base_url": "https://controlled.invalid/v1"},
            }
        ]

    async def get_model(self, model_id, *, trace_id=None):
        return (await self.list_models(trace_id=trace_id))[0]

    async def get_model_credentials(self, model_id, *, trace_id=None):
        return {"fields": {"api_key": {"configured": True}}}

    async def test_embedding_model(self, **_):
        return {"available": True}

    async def upload_file(
        self, *, kb_id, content, file_name, mime, metadata=None, channel=None, trace_id=None
    ):
        self.upload_traces.append(trace_id)
        if self.fail:
            from app.services.weknora_client import WeKnoraError

            raise WeKnoraError("weknora_down", "底座不可用")
        self._doc += 1
        return {"id": f"doc-{self._doc}", "parse_status": "processing", "file_hash": "h"}

    async def get_knowledge(self, knowledge_id, *, trace_id=None):
        return {"id": knowledge_id, "parse_status": "completed"}

    async def delete_knowledge(self, knowledge_id, *, trace_id=None):
        return None

    async def reparse_knowledge(
        self,
        *,
        kb_id,
        knowledge_id,
        content,
        file_name,
        mime,
        metadata=None,
        channel=None,
        trace_id=None,
    ):
        return await self.upload_file(
            kb_id=kb_id, content=content, file_name=file_name, mime=mime, trace_id=trace_id
        )

    async def search(self, **_):
        return []

    async def hybrid_search(self, **_):
        return []


def _enable_wk(monkeypatch, fake):
    from app.services.weknora_client import get_weknora_client
    from app.services.weknora_model_selection import ResolvedModels

    monkeypatch.setattr("app.services.ingest.weknora_enabled", lambda: True)
    monkeypatch.setattr("app.services.knowledge_index_commands.weknora_enabled", lambda: True)
    monkeypatch.setattr("app.services.jobs.indexing_operations.weknora_enabled", lambda: True)
    # PBC-38：建库模型经 resolver 解析（不再读 settings）；测试直接返回固定 ResolvedModels，
    # 绕过 DB 默认模型配置（本套件专注 trace 链路，不验证模型选择）。
    _resolved = ResolvedModels(
        embedding_model_id="test-embed", explicit_embedding=False, chat_model_id="test-chat"
    )

    async def _resolve(*_a, **_k):
        return _resolved

    monkeypatch.setattr("app.services.indexing.resolve_models_for_kb", _resolve)
    monkeypatch.setattr(
        "app.services.weknora_defaults.get_defaults",
        lambda *_a, **_k: _resolve_default_embedding(),
    )
    app.dependency_overrides[get_weknora_client] = lambda: fake


async def _resolve_default_embedding():
    return SimpleNamespace(default_embedding_model_id="test-embed")


@pytest.fixture(autouse=True)
def _wk_cleanup():
    yield
    from app.services.weknora_client import get_weknora_client

    app.dependency_overrides.pop(get_weknora_client, None)


async def _make_index_failed(client, monkeypatch, user):
    """走 confirm（失败底座）生成一个 index_failed 资产，返回 asset_id。"""
    _enable_wk(monkeypatch, _TraceWK(fail=True))
    up = await client.post(
        UPLOAD, headers=_hdr(user), files={"file": ("d.txt", b"trace idx body", "text/plain")}
    )
    task_id = up.json()["ingest_task_id"]
    payload = {
        "title": "trace 索引资产",
        "summary": "摘要",
        "tags": ["t"],
        "target_scope": "personal",
        "directory_key": "personal.learning_notes",
        "confidentiality_level": "L2",
    }
    r = await client.post(f"/api/v1/ingest/{task_id}/confirm", headers=_hdr(user), json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["index_status"] == "index_failed"
    return r.json()["result_asset_id"]


async def test_trace_id_flows_to_indexing_job_and_weknora(client, db_session, monkeypatch):
    """retry 带 X-Trace-Id → job.trace_id 保存该值 + fake WeKnora upload 收到同一 trace_id +
    完成审计沿用该 trace_id。"""
    await _make_index_failed(client, monkeypatch, USER_CONSULTANT)
    trace = "trc-idx-0017"
    rec = _TraceWK()
    _enable_wk(monkeypatch, rec)
    r = await client.post(
        RETRY,
        headers={**_hdr(USER_ADMIN_ONLY), "X-Trace-Id": trace},
        json={"scope": "all", "statuses": ["index_failed"], "limit": 50},
    )
    assert r.status_code == 202, r.text
    # job.trace_id 保存请求 trace。
    jobs = (
        (
            await db_session.execute(
                select(IndexingOperationJob).where(IndexingOperationJob.trace_id == trace)
            )
        )
        .scalars()
        .all()
    )
    assert jobs, "indexing_operation_job 应保存请求 trace_id"
    # fake WeKnora 重传收到同一 trace_id（HTTP → job → 底座调用同链路）。
    assert trace in rec.upload_traces
    # 完成审计沿用该 trace_id。
    audits = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.trace_id == trace)))
        .scalars()
        .all()
    )
    assert any(a.action and a.action.startswith("knowledge.index_batch_retry") for a in audits)
