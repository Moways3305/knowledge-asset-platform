"""Read-only, allowlisted diagnostics for a failed production cutover."""

import argparse
import json
from pathlib import Path
import re
import subprocess

FILES = {
    "execute_production_cutover.py",
    "production_cutover_runtime.py",
    "prepare_production_release.py",
    "weknora_pg_upgrade_rehearsal.py",
    "weknora_schema_upgrade_rehearsal.py",
}
KINDS = (
    "RuntimeError",
    "KeyError",
    "ValueError",
    "PermissionError",
    "FileNotFoundError",
    "TimeoutExpired",
    "JSONDecodeError",
    "AssertionError",
)
SIGNALS = {
    "database_start_timeout": r"database did not become ready",
    "database_container_not_running": r"container .{0,100} is not running",
    "database_authentication": r"password authentication failed|no password supplied|peer authentication failed",
    "database_connection_refused": r"connection refused|could not connect to server",
    "extension_update_path_missing": r"has no update path|no migration path|no update path",
    "extension_library_missing": r"could not (?:access|open|load).{0,100}(?:library|extension|pg_search|vector)",
    "database_transaction_block": r"cannot .*?(?:inside|within) a transaction block",
    "database_ownership_or_privilege": r"must be owner|must be superuser|permission denied",
    "database_object_missing": r"(?:database|relation|role|extension) .{0,150} does not exist",
    "database_object_exists": r"(?:relation|column|constraint|index) .{0,150} already exists",
    "shared_memory": r"shared memory|shared_memory|/dev/shm",
    "disk_or_memory_exhausted": r"no space left on device|out of memory|cannot allocate memory",
    "extension_version_mismatch": r"pg_search version differs|vector version differs",
    "dirty_migration": r"dirty database version|dirty schema",
    "migration_files_missing": r"no migration found|first .{0,100} file does not exist",
    "weknora_target_not_reached": r"WeKnora migration target not reached",
    "kap_target_not_reached": r"KAP migration target not reached",
    "weknora_data_comparison": r"WeKnora core data comparison failed|unexpected chunk deletion during migration",
    "kap_data_comparison": r"KAP original data comparison failed",
    "multiline_environment": r"multiline environment unsupported",
    "helper_failure": r"cutover helper failed|准备步骤失败",
}


def classify(raw):
    frames = []
    for path, line in re.findall(r'File "([^"\n]+)", line (\d+)', raw):
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        if name in FILES:
            frame = {"file": name, "line": int(line)}
            if frame not in frames:
                frames.append(frame)
    return {
        "exception_types": [
            name for name in KINDS if re.search(r"(?m)^(?:subprocess\.)?" + name + r":", raw)
        ],
        "missing_environment_fields": [
            key
            for key in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
            if re.search(r"(?m)^KeyError: ['\"]" + key + r"['\"]", raw)
        ],
        "signals": [key for key, pattern in SIGNALS.items() if re.search(pattern, raw, re.I)],
        "code_locations": frames[:20],
    }


def inspect(identity):
    result = subprocess.run(
        ["docker", "inspect", identity], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20
    )
    if result.returncode:
        return None
    return json.loads(result.stdout)[0]


def diagnose(stage):
    report = {"read_only": True, "raw_logs_included": False}
    log = stage / "private.log"
    with log.open("rb") as stream:
        size = log.stat().st_size
        stream.seek(max(0, size - 2 * 1024 * 1024))
        report["log_tail_truncated"] = size > 2 * 1024 * 1024
        report.update(classify(stream.read().decode(errors="replace")))
    state = json.loads((stage / "state-private.json").read_text())
    report["state"] = {
        key: state.get(key) is True
        for key in (
            "backup_complete",
            "data_mutated",
            "traffic_opening",
            "recovery_opening",
            "recovered",
        )
    }
    report["migration_helpers"] = []
    report["helper_inspection_unavailable"] = 0
    for identity in state.get("helpers", []):
        if not re.fullmatch(r"[a-f0-9]{64}", identity):
            continue
        item = inspect(identity)
        if item is None:
            report["helper_inspection_unavailable"] += 1
            continue
        command = item.get("Config", {}).get("Cmd") or []
        kind = None
        if command[:4] == ["-m", "alembic", "upgrade", "head"]:
            kind = "kap_alembic"
        elif any("migrate -path /app/migrations/versioned" in arg for arg in command):
            kind = "weknora_sql"
        if kind:
            report["migration_helpers"].append(
                {
                    "kind": kind,
                    "running": item["State"].get("Running") is True,
                    "exit_code": int(item["State"]["ExitCode"]),
                }
            )
    report["restored_services"] = []
    originals = state["originals"]
    names = [
        "kap-" + service + "-1"
        for service in ("backend", "worker", "ocr_worker", "beat", "frontend", "postgres", "redis")
    ]
    names += [
        "WeKnora-" + service for service in ("app", "frontend", "docreader", "postgres", "redis")
    ]
    for name in names:
        current = inspect(name)
        entry = {"container": name, "present": current is not None}
        if current:
            entry.update(
                running=current["State"].get("Running") is True,
                original_container=current["Id"] == originals[name]["Id"],
                original_image=current["Image"] == originals[name]["Image"],
            )
            status = current["State"].get("Health", {}).get("Status")
            entry["health"] = (
                status if status in (None, "healthy", "unhealthy", "starting") else "unrecognized"
            )
        report["restored_services"].append(entry)
    report["original_database_limits"] = {
        name: {
            "memory_mib": int(originals[name]["HostConfig"].get("Memory", 0)) // 1024**2,
            "shared_memory_mib": int(originals[name]["HostConfig"].get("ShmSize", 0)) // 1024**2,
        }
        for name in ("kap-postgres-1", "WeKnora-postgres")
    }
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cutover", required=True, type=Path)
    args = parser.parse_args()
    try:
        root = Path(
            "/data/weknora/upgrade-rehearsals/run-eDkLxh7B/production-preparations/20261105-160843-7ce5bf"
        )
        stage = args.cutover.resolve(strict=True)
        if stage.parent != root or not re.fullmatch(r"cutover-execute-[a-f0-9]{10}", stage.name):
            raise ValueError("unexpected cutover directory")
        print(json.dumps(diagnose(stage), ensure_ascii=False, indent=2))
    except Exception:
        print(
            json.dumps(
                {"read_only": True, "raw_logs_included": False, "diagnostic_read_failed": True}
            )
        )
        raise SystemExit(1) from None
