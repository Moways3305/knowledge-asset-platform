"""PBC-17 安全烟测脚本单元测试（scripts/production_smoke.py）。

不真实启动 Docker / 服务：用 fake opener 注入响应，验证脚本的安全字段摘要、redaction、
HTML 判定、退出码规则，以及输出绝不含密钥 / 正文 / cookie。
"""

from __future__ import annotations

import importlib.util
import io
import json
import urllib.error
from pathlib import Path

import pytest

# 从仓库根加载脚本模块（脚本不是包）。
_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "production_smoke.py"
_spec = importlib.util.spec_from_file_location("production_smoke", _SCRIPT)
smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke)


class _FakeResp:
    def __init__(self, status, body, content_type="application/json"):
        self.status = status
        self._body = body.encode("utf-8") if isinstance(body, str) else body
        self.headers = {"Content-Type": content_type}

    def read(self):
        return self._body


def _opener_from_map(mapping):
    """构造 fake opener：按 URL 路径返回预置响应；4xx 抛 HTTPError；缺失 → 连接失败。"""

    def _opener(req, timeout=10.0):
        url = req.full_url if hasattr(req, "full_url") else req.get_full_url()
        path = url.split("//", 1)[-1].split("/", 1)[-1]
        path = "/" + path if not path.startswith("/") else path
        entry = mapping.get(path)
        if entry is None:
            raise urllib.error.URLError("connection refused")
        status, body, ctype = entry
        if status >= 400:
            raise urllib.error.HTTPError(url, status, "err", {"Content-Type": ctype}, io.BytesIO(
                body.encode("utf-8") if isinstance(body, str) else body
            ))
        return _FakeResp(status, body, ctype)

    return _opener


def _healthy_config_body(**over):
    base = {
        "app_env": "prod",
        "version": "0.1.0",
        "integrations": {"weknora_enabled": True, "llm_enabled": True, "llm_provider": "deepseek", "celery_eager": False},
        "missing_config": [],
        "production_ready": True,
        "production_blockers": [],
        "production_warnings": [],
        # 故意混入"看似敏感"的额外字段，验证脚本白名单不会回显它。
        "database_url": "postgresql+asyncpg://dev:devpassword@db/x",
        "weknora_api_key": "sk-should-never-appear",
    }
    base.update(over)
    return base


def _default_map(config_body):
    return {
        "/health": (200, json.dumps({"status": "ok"}), "application/json"),
        "/health/ready": (200, json.dumps({"status": "ready", "checks": {"database": True, "redis": None}}), "application/json"),
        "/health/config": (200, json.dumps(config_body), "application/json"),
        "/": (200, "<!doctype html><html><body>app</body></html>", "text/html"),
        "/admin/ops/summary": (401, json.dumps({"detail": "not_authenticated"}), "application/json"),
    }


# ---------------------------------------------------------------------------
# 安全字段摘要 / redaction
# ---------------------------------------------------------------------------
def test_safe_config_summary_whitelists_fields():
    body = json.dumps(_healthy_config_body())
    summary = smoke.safe_config_summary(body)
    # 只保留白名单安全字段。
    assert summary["production_ready"] is True
    assert summary["production_blockers"] == []
    assert "missing_config" in summary
    # 敏感字段绝不出现。
    assert "database_url" not in summary
    assert "weknora_api_key" not in summary
    assert "sk-should-never-appear" not in json.dumps(summary)
    # integrations 只保留布尔 + provider 名。
    assert summary["integrations"]["weknora_enabled"] is True
    assert summary["integrations"]["llm_provider"] == "deepseek"


def test_safe_config_summary_handles_bad_json():
    assert smoke.safe_config_summary("not json") == {}
    assert smoke.safe_config_summary(None) == {}


def test_looks_like_html():
    assert smoke.looks_like_html("text/html; charset=utf-8", None) is True
    assert smoke.looks_like_html(None, "<!doctype html><html></html>") is True
    assert smoke.looks_like_html("application/json", '{"a":1}') is False


# ---------------------------------------------------------------------------
# 退出码规则
# ---------------------------------------------------------------------------
def test_run_checks_all_healthy_exit_zero():
    opener = _opener_from_map(_default_map(_healthy_config_body()))
    result = smoke.run_checks("http://x:18080", opener=opener)
    assert result["exit_code"] == 0
    # admin ops 401 → 鉴权生效。
    admin = [c for c in result["checks"] if c["endpoint"] == "/admin/ops/summary"][0]
    assert admin["summary"]["auth_enforced"] is True


def test_run_checks_health_down_exit_nonzero():
    m = _default_map(_healthy_config_body())
    m["/health"] = (503, json.dumps({"status": "down"}), "application/json")
    result = smoke.run_checks("http://x:18080", opener=_opener_from_map(m))
    assert result["exit_code"] == 1


def test_run_checks_unreachable_exit_nonzero():
    # 空映射 → 所有请求连接失败（health/ready 不通过 → 退出非 0）。
    result = smoke.run_checks("http://x:18080", opener=_opener_from_map({}))
    assert result["exit_code"] == 1
    health = [c for c in result["checks"] if c["endpoint"] == "/health"][0]
    assert health["status"] is None


def test_run_checks_blockers_fail_only_when_flagged():
    body = _healthy_config_body(production_ready=False, production_blockers=["CELERY_TASK_ALWAYS_EAGER"])
    m = _default_map(body)
    # 未传 --fail-on-production-blockers → 退出 0。
    assert smoke.run_checks("http://x:18080", opener=_opener_from_map(m))["exit_code"] == 0
    # 传了 → 退出非 0。
    res = smoke.run_checks("http://x:18080", opener=_opener_from_map(m), fail_on_blockers=True)
    assert res["exit_code"] == 1
    assert res["production_blockers"] == ["CELERY_TASK_ALWAYS_EAGER"]


def test_admin_ops_403_also_auth_enforced():
    m = _default_map(_healthy_config_body())
    m["/admin/ops/summary"] = (403, json.dumps({"detail": "forbidden"}), "application/json")
    res = smoke.run_checks("http://x:18080", opener=_opener_from_map(m))
    admin = [c for c in res["checks"] if c["endpoint"] == "/admin/ops/summary"][0]
    assert admin["summary"]["auth_enforced"] is True
    assert res["exit_code"] == 0


# ---------------------------------------------------------------------------
# 输出不泄露密钥 / 正文
# ---------------------------------------------------------------------------
def test_human_and_json_output_no_secret_leak(capsys):
    body = _healthy_config_body()
    result = smoke.run_checks("http://x:18080", opener=_opener_from_map(_default_map(body)))
    human = smoke.format_human(result)
    machine = json.dumps({k: v for k, v in result.items() if k != "exit_code"}, ensure_ascii=False)
    for blob in (human, machine):
        assert "devpassword" not in blob
        assert "postgresql+asyncpg" not in blob
        assert "sk-should-never-appear" not in blob
        assert "weknora_api_key" not in blob
        # 不打印 cookie / Authorization 头。
        assert "Authorization" not in blob
        assert "Cookie" not in blob


def test_build_url():
    assert smoke.build_url("http://x:18080/", "/health") == "http://x:18080/health"
    assert smoke.build_url("http://x:18080", "health") == "http://x:18080/health"


# ---------------------------------------------------------------------------
# --expect-prod-ready 别名（PBC-23）：与 --fail-on-production-blockers 等价
# ---------------------------------------------------------------------------
def test_expect_prod_ready_is_alias_of_fail_on_blockers():
    parser = smoke.build_parser()
    # 两个入口分别置位时都应解析为 fail_on=True。
    assert smoke.fail_on_blockers_from_args(parser.parse_args(["--expect-prod-ready"])) is True
    assert smoke.fail_on_blockers_from_args(parser.parse_args(["--fail-on-production-blockers"])) is True
    # 都不传 → False（默认不因 blockers 失败）。
    assert smoke.fail_on_blockers_from_args(parser.parse_args([])) is False
