#!/usr/bin/env python3
"""生产部署安全烟测。

对一个**已部署**的实例做只读探活：liveness / readiness / 安全配置诊断 / 前端入口 /
未登录 admin 鉴权。**只用标准库**（urllib / json / argparse），不引第三方依赖，也不读取
`.env`、不调用会展开 secrets 的 `docker compose config`。

安全红线：本脚本输出**绝不**打印响应正文、Authorization / Cookie 头、api_key、连接串、
URL secret。`/health/config` 只摘取白名单安全字段（项名 / 布尔 / 枚举）。

用法：
    python scripts/production_smoke.py --base-url http://localhost:18080
    python scripts/production_smoke.py --fail-on-production-blockers --json
    python scripts/production_smoke.py --expect-prod-ready --json   # 同上别名（更清晰入口）

退出码：
    0  health + ready 通过（且未要求阻断 / 无阻断项）；
    1  health 或 ready 不通过，或 --fail-on-production-blockers / --expect-prod-ready
       且存在生产阻断项。
未登录 admin 返回 401/403 视为鉴权生效（不影响退出码）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "http://localhost:18080"

# `/health/config` 仅摘取这些**安全**字段（项名 / 布尔 / 枚举）。绝不回显其余正文。
_SAFE_CONFIG_FIELDS = (
    "app_env",
    "version",
    "production_ready",
    "production_blockers",
    "production_warnings",
    "missing_config",
)


def build_url(base_url: str, path: str) -> str:
    """拼接 base-url 与路径（避免重复 / 缺失斜杠）。"""
    return base_url.rstrip("/") + "/" + path.lstrip("/")


def _fetch(opener, url: str, *, timeout: float = 10.0):
    """GET 请求；返回 (status, content_type, body_text)。连接失败 → (None, None, None)。

    `opener` 形如 urllib.request.urlopen，便于单测注入 fake。4xx/5xx 经 HTTPError 取状态码。
    """
    req = urllib.request.Request(url, method="GET", headers={"Accept": "*/*"})
    try:
        resp = opener(req, timeout=timeout)
        body = resp.read()
        ctype = resp.headers.get("Content-Type", "") if hasattr(resp, "headers") else ""
        return resp.status, ctype, body.decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:  # 4xx/5xx 仍是一次"成功的探测"
        body = exc.read() if hasattr(exc, "read") else b""
        ctype = exc.headers.get("Content-Type", "") if getattr(exc, "headers", None) else ""
        return exc.code, ctype, body.decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError):
        return None, None, None


def looks_like_html(content_type: str | None, body: str | None) -> bool:
    """前端入口判定：Content-Type 为 html 或正文以 <!doctype/<html 起头。"""
    if content_type and "html" in content_type.lower():
        return True
    if not body:
        return False
    head = body.lstrip()[:200].lower()
    return head.startswith("<!doctype html") or head.startswith("<html")


def safe_config_summary(body_text: str | None) -> dict:
    """从 /health/config 正文只提取白名单安全字段；非法 JSON → 空摘要。

    绝不返回密钥 / URL / 连接串：白名单内的项本就是项名 / 布尔 / 枚举（按后端契约安全）。
    """
    if not body_text:
        return {}
    try:
        data = json.loads(body_text)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    summary = {k: data[k] for k in _SAFE_CONFIG_FIELDS if k in data}
    integ = data.get("integrations")
    if isinstance(integ, dict):
        # 只保留布尔启用标记 + provider 名（契约已规定为安全，无值/密钥）。
        summary["integrations"] = {
            k: v for k, v in integ.items() if isinstance(v, bool) or (k == "llm_provider")
        }
        onlyoffice = integ.get("onlyoffice_config")
        if isinstance(onlyoffice, dict):
            summary["integrations"]["onlyoffice_config"] = {
                key: value for key, value in onlyoffice.items() if isinstance(value, bool)
            }
    return summary


def safe_status_summary(body_text: str | None) -> dict:
    """从 /health 或 /health/ready 只取 status / checks 布尔（无密钥）。"""
    if not body_text:
        return {}
    try:
        data = json.loads(body_text)
    except (json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict = {}
    if "status" in data:
        out["status"] = data["status"]
    checks = data.get("checks")
    if isinstance(checks, dict):
        out["checks"] = {k: v for k, v in checks.items() if isinstance(v, (bool, type(None)))}
    return out


def run_checks(
    base_url: str, *, opener=urllib.request.urlopen, fail_on_blockers: bool = False
) -> dict:
    """跑全部探测并返回**只含安全字段**的结构化结果 + 退出码。"""
    checks: list[dict] = []
    exit_code = 0

    # 1) liveness
    s, _ct, body = _fetch(opener, build_url(base_url, "/health"))
    checks.append({"endpoint": "/health", "status": s, "summary": safe_status_summary(body)})
    if s != 200:
        exit_code = 1

    # 2) readiness
    s, _ct, body = _fetch(opener, build_url(base_url, "/health/ready"))
    checks.append({"endpoint": "/health/ready", "status": s, "summary": safe_status_summary(body)})
    if s != 200:
        exit_code = 1

    # 3) 安全配置诊断
    s, _ct, body = _fetch(opener, build_url(base_url, "/health/config"))
    cfg = safe_config_summary(body)
    checks.append({"endpoint": "/health/config", "status": s, "summary": cfg})
    blockers = cfg.get("production_blockers") or []
    if fail_on_blockers and blockers:
        exit_code = 1

    # 4) 前端入口（部署经反代提供 /）。HTML + 200 视为通过；不阻断退出码（前端 404 仅告警）。
    s, ct, body = _fetch(opener, build_url(base_url, "/"))
    checks.append(
        {
            "endpoint": "/",
            "status": s,
            "summary": {"html": looks_like_html(ct, body)},
        }
    )

    # 5) 未登录 admin ops → 期望 401/403（鉴权生效）；不影响退出码。
    s, _ct, _body = _fetch(opener, build_url(base_url, "/admin/ops/summary"))
    checks.append(
        {
            "endpoint": "/admin/ops/summary",
            "status": s,
            "summary": {"auth_enforced": s in (401, 403)},
        }
    )

    return {
        "base_url": base_url,
        "production_ready": cfg.get("production_ready"),
        "production_blockers": blockers,
        "checks": checks,
        "exit_code": exit_code,
    }


def format_human(result: dict) -> str:
    """人读摘要（每个端点一行：名称 + 状态 + 安全摘要）。绝不打印正文 / 密钥。"""
    lines = [f"production_smoke @ {result['base_url']}"]
    for c in result["checks"]:
        status = c["status"] if c["status"] is not None else "UNREACHABLE"
        lines.append(
            f"  {c['endpoint']:<24} {status}  {json.dumps(c['summary'], ensure_ascii=False)}"
        )
    pr = result.get("production_ready")
    lines.append(f"  production_ready: {pr}")
    if result.get("production_blockers"):
        lines.append(f"  production_blockers: {result['production_blockers']}")
    lines.append(f"  exit_code: {result['exit_code']}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """命令行参数解析器（独立函数便于单测，不触网络）。"""
    parser = argparse.ArgumentParser(description="生产部署安全烟测。")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("KAP_BASE_URL", DEFAULT_BASE_URL),
        help=f"目标实例基址（默认 ${{KAP_BASE_URL}} 或 {DEFAULT_BASE_URL}）",
    )
    parser.add_argument(
        "--fail-on-production-blockers",
        action="store_true",
        help="存在生产阻断项时退出码非 0",
    )
    parser.add_argument(
        "--expect-prod-ready",
        action="store_true",
        help="--fail-on-production-blockers 的别名（更清晰入口：期望目标实例无生产阻断项）",
    )
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON 摘要")
    return parser


def fail_on_blockers_from_args(args) -> bool:
    """把 --fail-on-production-blockers / --expect-prod-ready 合并为单一布尔（别名等价）。"""
    return bool(args.fail_on_production_blockers or args.expect_prod_ready)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    result = run_checks(args.base_url, fail_on_blockers=fail_on_blockers_from_args(args))
    if args.json:
        # 仅安全字段（run_checks 已只含安全摘要）。
        print(
            json.dumps(
                {k: v for k, v in result.items() if k != "exit_code"},
                ensure_ascii=False,
            )
        )
    else:
        print(format_human(result))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
