"""Read private rehearsal logs locally and emit only allow-listed diagnostic labels."""

import argparse
import json
from pathlib import Path
import re

EXCEPTIONS = (
    "WeKnoraError",
    "ReadTimeout",
    "ConnectTimeout",
    "PoolTimeout",
    "WriteTimeout",
    "ConnectError",
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
    "dns_failure": ("no such host", "name resolution", "name or service not known"),
    "connection_refused": ("connection refused",),
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
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    args = parser.parse_args()
    stage = args.stage.resolve(strict=True)
    app_stage = stage.parent if stage.name.startswith("search-plan-") else stage
    if app_stage.parent.parent != Path(
        "/data/weknora/upgrade-rehearsals"
    ) or not app_stage.name.startswith("app090-"):
        raise SystemExit("Unexpected rehearsal directory")
    result = {"read_only": True, "raw_logs_included": False, "logs": {}}
    for name in ["probe-private.log", "private.log"]:
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
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
