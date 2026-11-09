"""Inventory a prepared release for cutover; no service, volume or database mutations.

Only fixed labels, counts, image IDs and allowlisted infrastructure fields reach stdout.
Private configuration remains in the restricted preparation directory. This inventory
is NOT a consistent backup, a cutover implementation, or a deployment success report.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import traceback
import uuid

from prepare_production_release import Runner, fingerprint, require
from resume_production_build import ROOT, local_file, read, validate_records

REVISION = "b85ca9816771e5bfdb964019546c542d5964e2b8"
SERVICES = ("backend", "worker", "ocr_worker", "beat", "frontend", "migrate")
KNOWN_DESTINATIONS = {
    "/var/lib/postgresql/data",
    "/data",
    "/data/uploads",
    "/data/files",
    "/tmp/docreader",
    "/app/config/config.yaml",
    "/app/skills/preloaded",
    "/data/workbuddy-connectors",
}
CRITICAL_ENV = {
    "DATABASE_URL",
    "POSTGRES_PASSWORD",
    "REDIS_URL",
    "WEKNORA_BASE_URL",
    "WEKNORA_API_KEY",
    "SECRET_KEY",
    "JWT_SECRET_KEY",
    "MODEL_ENCRYPTION_KEY",
    "GENERATION_MODEL_ENCRYPTION_KEY",
}


def environment(item):
    return dict(line.split("=", 1) for line in item["Config"].get("Env", []) if "=" in line)


def mount_key(mount):
    return (mount["Type"], mount.get("Name") if mount["Type"] == "volume" else mount["Source"])


def overlap(left, right):
    """Detect RW consumers, including ancestor/descendant bind mounts."""
    if left[0] != right[0]:
        return False
    if left[0] != "bind":
        return left == right
    from pathlib import PurePosixPath

    a, b = PurePosixPath(left[1]), PurePosixPath(right[1])
    return a == b or a in b.parents or b in a.parents


def storage_inventory(runtime, active):
    stores = {}
    for name, item in sorted(runtime.items()):
        for mount in item.get("Mounts", []):
            if not mount.get("RW") or mount["Type"] not in {"bind", "volume"}:
                continue
            key = mount_key(mount)
            entry = stores.setdefault(key, {"owners": [], "mount": mount, "unknown_writers": 0})
            entry["owners"].append((name, mount["Destination"]))
    known_ids = {item["Id"] for item in runtime.values()}
    for item in active:
        if item["Id"] in known_ids:
            continue
        for key, entry in stores.items():
            if any(
                mount.get("RW")
                and mount["Type"] in {"bind", "volume"}
                and (
                    overlap(key, mount_key(mount))
                    or overlap(("bind", entry["mount"]["Source"]), ("bind", mount["Source"]))
                )
                for mount in item.get("Mounts", [])
            ):
                entry["unknown_writers"] += 1
    return list(stores.values())


def storage_summary(runner, stores):
    result = []
    for index, entry in enumerate(stores):
        name, destination = next((n, d) for n, d in entry["owners"] if n != "kap-migrate-1")
        # Paths are an allowlist, never commands interpolated from private records.
        require(destination in KNOWN_DESTINATIONS, "发现未覆盖的可写挂载")
        raw = runner.docker(
            "exec", "--user", "0", name, "du", "-sk", "--", destination, timeout=120
        )
        kib = int(raw.split()[0])
        free = runner.docker("exec", "--user", "0", name, "df", "-Pk", destination, timeout=30)
        free_kib = int(free.splitlines()[-1].split()[-3])
        require(free_kib >= 0, "文件系统容量输出无效")
        require(kib >= 0, "存储容量输出无效")
        result.append(
            {
                "index": index,
                "type": entry["mount"]["Type"],
                "used_mib": round(kib / 1024, 2),
                "filesystem_free_gib": round(free_kib / 1024**2, 2),
                "known_writers": sorted({n for n, _ in entry["owners"]}),
                "destinations": sorted(
                    {d if d in KNOWN_DESTINATIONS else "unrecognized" for _, d in entry["owners"]}
                ),
                "additional_running_writers": entry["unknown_writers"],
            }
        )
    return result


def bindings(item):
    result = []
    for port, values in sorted((item["HostConfig"].get("PortBindings") or {}).items()):
        require(re.fullmatch(r"\d{1,5}/(?:tcp|udp)", port), "端口记录无效")
        for value in values or []:
            host = value.get("HostIp", "")
            published = value.get("HostPort", "")
            require(published.isdecimal(), "端口记录无效")
            result.append(
                {
                    "container_port": port,
                    "host_port": int(published),
                    "binding": "loopback" if host in {"127.0.0.1", "::1"} else "other",
                }
            )
    return result


def database_state(runner, name, item):
    env = environment(item)
    user, db = env.get("POSTGRES_USER", "postgres"), env.get("POSTGRES_DB", "postgres")
    query = (
        "SELECT json_build_object('version',version,'dirty',dirty) FROM schema_migrations"
        if name == "WeKnora-postgres"
        else "SELECT json_build_object('version',version_num) FROM alembic_version"
    )
    prefix = [
        "exec",
        "-e",
        "PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=20000 -c lock_timeout=5000",
        name,
        "psql",
        "-XqAt",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        user,
        "-d",
        db,
        "-c",
    ]
    state = json.loads(runner.docker(*prefix, query, timeout=45))
    if name == "WeKnora-postgres":
        require(
            type(state.get("version")) is int and type(state.get("dirty")) is bool, "迁移状态无效"
        )
        version = state["version"]
    else:
        # Only the numeric migration prefix is public, never arbitrary DB text.
        match = re.fullmatch(r"(\d{4})_[a-z0-9_]+", str(state.get("version", "")))
        require(match is not None, "KAP 迁移标识无效")
        version = match[1]
    ext = json.loads(
        runner.docker(
            *prefix,
            "SELECT coalesce(json_object_agg(extname,extversion),'{}'::json) FROM pg_extension "
            "WHERE extname IN ('pg_search','vector')",
            timeout=45,
        )
    )
    require(
        all(
            k in {"pg_search", "vector"} and re.fullmatch(r"\d+\.\d+(?:\.\d+)?", v)
            for k, v in ext.items()
        ),
        "扩展版本无效",
    )
    sessions = int(
        runner.docker(
            *prefix,
            "SELECT count(*) FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid()",
            timeout=45,
        )
    )
    return {
        "migration": version,
        "dirty": state.get("dirty", False),
        "extensions": ext,
        "other_client_sessions": sessions,
    }


def verify_candidates(runner, stage, report):
    images = read(stage / "candidate-image-ids.json")
    require(
        set(images) == set(SERVICES) and images == report.get("candidate_images"),
        "候选镜像清单不一致",
    )
    overlay = read(stage / "candidate-images.json")["services"]
    for service, image in images.items():
        require(re.fullmatch(r"sha256:[a-f0-9]{64}", image), "候选镜像 ID 无效")
        require(runner.image_identity(overlay[service]["image"]) == image, "候选镜像标签已变化")
    wk = read(stage / "weknora-candidate.json")
    require(wk["app"] == report.get("weknora_image"), "底座镜像记录不一致")
    for key in ("database", "app", "app_original"):
        image = wk[key]
        require(re.fullmatch(r"sha256:[a-f0-9]{64}", image), "底座镜像 ID 无效")
        require(runner.image_identity(image) == image, "底座镜像缺失")
    return {"kap": images, "weknora_app": wk["app"], "weknora_database": wk["database"]}


def collect(runner, stage, out, report):
    report["checkpoint"] = "prepared_records"
    source, _, prepared = validate_records(runner, stage, REVISION, prepared=True)
    report["candidate_images"] = verify_candidates(runner, stage, prepared)
    original = read(stage / "runtime-private.json")
    report["checkpoint"] = "storage_and_writers"
    ids = runner.docker("ps", "-q").splitlines()
    active = [runner.inspect(container_id) for container_id in ids]
    stores = storage_inventory(original, active)
    (out / "storage-private.json").write_text(json.dumps(stores, ensure_ascii=False))
    report["storage"] = storage_summary(runner, stores)
    report["preparation_disk_free_gib"] = round(shutil.disk_usage(stage).free / 1024**3, 2)
    report["storage_estimate_is_live_not_consistent_backup"] = True
    report["checkpoint"] = "database_versions"
    report["databases"] = {
        name: database_state(runner, name, original[name])
        for name in ("kap-postgres-1", "WeKnora-postgres")
    }
    report["services"] = {
        name: {"ports": bindings(item), "network_count": len(item["NetworkSettings"]["Networks"])}
        for name, item in sorted(original.items())
        if name != "kap-migrate-1"
    }
    # Resolve without creating/updating services. Keep all interpolated secrets private.
    report["checkpoint"] = "candidate_compose"
    command = ["compose", "-p", "kap"]
    for path in (
        source / "docker-compose.yml",
        source / "docker-compose.prod.yml",
        stage / "candidate-images.json",
    ):
        command += ["-f", str(path)]
    candidate = json.loads(runner.docker(*command, "config", "--format", "json", cwd=source))
    (out / "candidate-compose-private.json").write_text(json.dumps(candidate))
    comparison = {}
    for service in SERVICES:
        item = original["kap-" + service + "-1"]
        env = environment(item)
        resolved = candidate["services"][service]
        changed = {
            key
            for key in env.keys() | resolved.get("environment", {}).keys()
            if env.get(key) != resolved.get("environment", {}).get(key)
        }
        comparison[service] = {
            "critical_environment_unchanged": not bool(changed & CRITICAL_ENV),
            "environment_difference_count": len(changed),
            "command_changed": item["Config"].get("Cmd") != resolved.get("command"),
            "mount_count": len(resolved.get("volumes", [])),
        }
    report["candidate_runtime_comparison"] = comparison
    sources = read(stage / "compose-sources-private.json")
    report["compose_source_count"] = len(sources)
    for record in sources:
        local_file(stage, record["resolved"])
    report["checkpoint"] = "final_identity_check"
    # Check there has been no service replacement while inventory was collected.
    for name, old in original.items():
        current = runner.inspect(name)
        require(fingerprint(old) == fingerprint(current), "核对期间生产容器发生变化")
        require(
            current["State"]["Running"] == (name != "kap-migrate-1"), "核对期间服务运行状态变化"
        )
    report["blockers"] = []
    if any(entry["additional_running_writers"] for entry in report["storage"]):
        report["blockers"].append("additional_volume_writers")
    if any(
        not item["critical_environment_unchanged"]
        for service, item in comparison.items()
        if service != "migrate"
    ):
        report["blockers"].append("critical_environment_difference")
    wk = report["databases"]["WeKnora-postgres"]
    if wk["migration"] != 74 or wk["dirty"] or wk["extensions"].get("pg_search") != "0.22.2":
        report["blockers"].append("weknora_baseline_differs_from_rehearsal")
    report.update(
        passed=True,
        production_identity_unchanged=True,
        consistent_backup_completed=False,
        cutover_completed=False,
        next_step="review inventory and execute controlled cutover",
        checkpoint="complete",
    )


def main():
    import fcntl

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    report = {
        "phase": "production_cutover_inventory",
        "read_only": True,
        "raw_logs_included": False,
        "production_switched": False,
        "passed": False,
    }
    try:
        stage = args.stage.resolve(strict=True)
        require(
            stage.parent == ROOT / "production-preparations"
            and re.fullmatch(r"\d{8}-\d{6}-[a-f0-9]{6}", stage.name),
            "准备目录不匹配",
        )
        out = stage / ("cutover-inventory-" + uuid.uuid4().hex[:10])
        out.mkdir(mode=0o700)
        report["checked_at_utc"] = datetime.now(timezone.utc).isoformat()
        with (
            (stage.parent / "prepare.lock").open("a") as lock,
            (out / "private.log").open("ab") as log,
        ):
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                print("只读核对当前存储、数据库及服务配置；生产持续运行。", flush=True)
                collect(Runner(log), stage, out, report)
            except Exception:
                log.write(traceback.format_exc().encode())
                report["error"] = "inventory_failed_private_details_retained"
            (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    except Exception:
        report["error"] = "inventory_setup_failed"
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
