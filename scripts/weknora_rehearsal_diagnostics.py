"""Read private rehearsal logs locally and emit only allow-listed diagnostic labels."""

import argparse
import json
from pathlib import Path
import re
import subprocess

EXCEPTIONS = (
    "WeKnoraError",
    "ReadTimeout",
    "ConnectTimeout",
    "PoolTimeout",
    "WriteTimeout",
    "ConnectError",
    "ProxyError",
    "ReadError",
    "RemoteProtocolError",
    "HTTPStatusError",
    "AttributeError",
    "TypeError",
    "ValueError",
    "KeyError",
    "RuntimeError",
    "InvalidTag",
)
UPSTREAM_CODES = {
    "1000": "bad_request",
    "1001": "unauthorized",
    "1002": "forbidden",
    "1003": "not_found",
    "1004": "method_not_allowed",
    "1005": "conflict",
    "1006": "rate_limited",
    "1007": "internal_server_error",
    "1008": "service_unavailable",
    "1009": "timeout",
    "1010": "validation",
    "2200": "vector_store_binding_invalid",
    "2201": "vector_store_unavailable",
}
SIGNALS = {
    "parameter_execution_error": (
        "no value found for parameter",
        "no parameter",
        "parameter has no value",
        "unresolved parameter",
        "could not evaluate",
        "cannot evaluate",
        "param node",
        "paramkind",
        "param_extern",
    ),
    "generic_plan_error": (
        "generic plan",
        "generic prepared",
    ),
    "score_execution_error": (
        "must be evaluated by a paradedb scan",
        "score function",
    ),
    "unsupported_query_shape": ("unsupported query shape",),
    "shared_memory_error": (
        "could not resize shared memory",
        "could not map dynamic shared memory",
    ),
    "disk_full": ("no space left on device",),
    "out_of_memory": ("out of memory", "memory allocation failed"),
    "index_rebuild_required": ("reindex", "index format", "incompatible index"),
    "parallel_worker_failure": ("parallel worker", "parallel context"),
    "timeout": ("timed out", "timeout", "deadline exceeded"),
    "network_unreachable": ("network is unreachable", "no route to host"),
    "dns_failure": (
        "no such host",
        "name resolution",
        "name or service not known",
        "dns resolution failed",
    ),
    "ssrf_validation_failed": ("ssrf validation failed",),
    "model_call_failed": ("failed to call embedder", "调用embedding失败", "创建embedder失败"),
    "model_credentials_rejected": (
        "invalid api key",
        "invalid_api_key",
        "invalidapikey",
        "incorrect api key",
    ),
    "model_quota_exhausted": (
        "insufficient_quota",
        "arrearage",
        "quota exceeded",
        "insufficient balance",
    ),
    "tls_failure": (
        "certificate verify failed",
        "certificate signed by unknown authority",
        "tls handshake timeout",
    ),
    "outbound_dial": ("dial tcp", "proxyconnect tcp"),
    "upstream_eof": ("unexpected eof",),
    "connection_refused": ("connection refused",),
    "script_permission_denied": ("[errno 13] permission denied",),
    "script_open_failed": ("can't open file", "cannot open file"),
    "gateway_not_ready": ("egress gateway exited", "egress gateway readiness timeout"),
    "embedding_failure": ("embedding model", "get embedding", "query embedding", "failed to embed"),
    "rerank_failure": ("rerank model", "reranking failed"),
    "no_keyword_fallback": ("no keyword fallback",),
    "search_target_failure": ("build search targets",),
    "kb_not_initialized": ("not initialized", "not configured", "uninitialized"),
    "missing_database_object": ("does not exist", "undefined column", "undefined table"),
    "database_permission": ("permission denied for",),
    "database_syntax": ("syntax error",),
    "database_recovery": ("database system is in recovery", "database system is starting"),
    "index_error": ("bm25", "pg_search", "tantivy", "index not found", "no index found"),
    "invalid_scope": ("not allowed", "access denied", "forbidden", "out of scope"),
    "response_shape": (
        "has no attribute",
        "indices must be",
        "not subscriptable",
        "could not convert string to float",
    ),
    "invalid_json": ("invalid_response", "jsondecodeerror", "响应非 json"),
    "crypto_error": (
        "decrypt failed",
        "authentication tag",
        "invalidtag",
        "cipher: message authentication failed",
    ),
}
PROVIDER_CODES = {
    "Arrearage",
    "AccessDenied",
    "access_denied",
    "AccessDenied.Unpurchased",
    "Model.AccessDenied",
    "Workspace.AccessDenied",
    "Endpoint.AccessDenied",
    "App.AccessDenied",
    "AllocationQuota.FreeTierOnly",
    "InvalidApiKey",
    "invalid_api_key",
    "InvalidParameter",
    "Throttling.AllocationQuota",
    "Throttling.RateQuota",
    "BudgetLimitExceeded",
    "insufficient_quota",
    "WorkSpaceNotFound",
    "ModelNotFound",
}
PROVIDER_MESSAGES = {
    "api_key_model_restriction": "access denied by api-key restrictions",
    "workspace_access_denied": "workspace access denied",
    "workspace_endpoint_denied": "workspace endpoint access denied",
    "model_access_denied": "model access denied",
    "free_tier_only": "use free tier only",
    "account_standing": "account is in good standing",
    "asynchronous_not_supported": "does not support asynchronous calls",
    "synchronous_not_supported": "does not support synchronous calls",
}
SQLSTATES = {
    "XX000",
    "XX001",
    "XX002",
    "42703",
    "42883",
    "42P01",
    "42501",
    "42601",
    "22023",
    "22P02",
    "57014",
    "53300",
    "08006",
    "57P01",
}


def classify(text):
    lowered = text.lower()
    found = []
    for line in text.splitlines():
        for name in EXCEPTIONS:
            if re.match(r"^(?:[A-Za-z_]\w*\.)*" + name + r"(?:\:|$)", line):
                found.append(name)
    codes = re.findall(r"WeKnoraError:\s*(\d{4})\s*:", text)
    return {
        "provider_error_codes": sorted(
            set(re.findall(r'"(?:code|type)"\s*:\s*"([^"\r\n]+)"', text)) & PROVIDER_CODES
        ),
        "provider_message_flags": sorted(
            label for label, phrase in PROVIDER_MESSAGES.items() if phrase in lowered
        ),
        "exception_type": found[-1] if found else "unclassified",
        "upstream_error_categories": sorted(
            {UPSTREAM_CODES[c] for c in codes if c in UPSTREAM_CODES}
        ),
        "sqlstates": sorted(
            {
                c
                for c in re.findall(r"(?:SQLSTATE\s+|ERROR:\s+)([A-Z0-9]{5})(?:\b|:)", text)
                if c in SQLSTATES
            }
        ),
        "signals": sorted(
            label for label, patterns in SIGNALS.items() if any(p in lowered for p in patterns)
        ),
        "upstream_http_statuses": sorted(
            {
                int(code)
                for code in re.findall(
                    r"(?:status(?:[ _]code)?[\s:=]+|http[\s/\d.]+)(400|401|403|404|408|429|500|502|503|504)\b",
                    lowered,
                )
            }
        ),
    }


def compare_model_credentials(data):
    """Compare stored keys in memory; return no keys, hashes, headers or exception details."""
    import base64
    import hmac

    def params(slot):
        value = data["models"][slot].get("parameters") or {}
        return json.loads(value) if isinstance(value, str) else value

    def plaintext(value):
        if not isinstance(value, str) or not value:
            raise ValueError("missing credential")
        if value.startswith("enc:v1:"):
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM

            raw = base64.urlsafe_b64decode(value[7:] + "=" * (-len(value[7:]) % 4))
            return AESGCM(data["aes_key"].encode()).decrypt(raw[:12], raw[12:], None)
        return value.encode()

    try:
        embedding, rerank = params("embedding"), params("rerank")
        result = {
            "custom_authorization_header_present": {
                slot: any(str(k).lower() == "authorization" for k in p.get("custom_headers", {}))
                for slot, p in (("embedding", embedding), ("rerank", rerank))
            },
        }
        try:
            result["stored_api_keys_equal"] = hmac.compare_digest(
                plaintext(embedding.get("api_key")), plaintext(rerank.get("api_key"))
            )
            result["comparison_completed"] = True
        except Exception:
            result["comparison_completed"] = False
        return result
    except Exception:
        return {"comparison_completed": False}


def model_diagnostics(stage):
    result = {"checks": {}}
    for slot in ("embedding", "chat", "rerank"):
        path = stage / ("model-check-" + slot + "-private.json")
        if path.is_file():
            response = json.loads(path.read_text())
            result["checks"][slot] = classify(str(response.get("message", "")))
    data = json.loads((stage / "live-private.json").read_text())
    result["credential_comparison"] = compare_model_credentials(data)
    return result


def isolated_logs(stage):
    token = stage.name.removeprefix("live090-")
    if not re.fullmatch(r"[0-9a-f]{10}", token):
        raise ValueError("Unexpected live rehearsal token")
    resources = json.loads((stage / "resources.json").read_text())
    results = {}
    for role, suffix in (("app", "app"), ("gateway", "egress")):
        name = resources[role]
        if name != f"wk-live-{token}-{suffix}":
            raise ValueError("Unexpected isolated container name")
        inspected = subprocess.run(
            ["docker", "inspect", name],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if inspected.returncode:
            results[role] = {"inspect_succeeded": False}
            continue
        item = json.loads(inspected.stdout)[0]
        if item["Config"].get("Labels", {}).get("kap.weknora.rehearsal") != str(stage.parent):
            raise ValueError("Isolated container label mismatch")
        logs = subprocess.run(
            ["docker", "logs", "--tail", "300", name],
            capture_output=True,
            text=True,
            timeout=20,
        )
        results[role] = {
            "log_read_succeeded": logs.returncode == 0,
            "status": item["State"].get("Status"),
            **classify((logs.stdout + logs.stderr)[-1024 * 1024 :]),
        }
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--stage", type=Path)
    choice.add_argument("--latest-live-run", type=Path)
    parser.add_argument("--container-logs", action="store_true")
    parser.add_argument("--model-checks", action="store_true")
    args = parser.parse_args()
    if args.latest_live_run:
        run = args.latest_live_run.resolve(strict=True)
        if run.parent != Path("/data/weknora/upgrade-rehearsals") or not run.name.startswith(
            "run-"
        ):
            raise SystemExit("Unexpected rehearsal root")
        candidates = [
            p for p in run.glob("live090-*") if not p.is_symlink() and (p / "exit-code").is_file()
        ]
        if not candidates:
            raise SystemExit("No completed live rehearsal found")
        stage = max(candidates, key=lambda p: (p / "exit-code").stat().st_mtime)
    else:
        stage = args.stage.resolve(strict=True)
    app_stage = stage.parent if stage.name.startswith("search-plan-") else stage
    if app_stage.parent.parent != Path(
        "/data/weknora/upgrade-rehearsals"
    ) or not app_stage.name.startswith(("app090-", "live090-")):
        raise SystemExit("Unexpected rehearsal directory")
    result = {"read_only": True, "raw_logs_included": False, "stage": stage.name, "logs": {}}
    for name in ["probe-private.log", "private.log", "kap-role-private.log"]:
        path = stage / name
        if not path.is_file():
            result["logs"][name] = {"present": False}
            continue
        with path.open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - 1024 * 1024))
            text = stream.read().decode("utf-8", errors="replace")
        result["logs"][name] = {
            "present": True,
            "tail_truncated": size > 1024 * 1024,
            **classify(text),
        }
    if args.container_logs:
        result["isolated_containers"] = isolated_logs(stage)
    if args.model_checks:
        result["model_diagnostics"] = model_diagnostics(stage)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
