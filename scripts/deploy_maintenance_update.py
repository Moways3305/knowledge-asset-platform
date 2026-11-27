"""Pinned v1.3.1 delivery; verify an allowlisted live baseline under both locks."""

import json
from pathlib import Path
import re
import sys

import deploy_stage_release as stage
from prepare_production_release import require
from production_cutover_inventory import environment
from rollout_vision_fix import write

REVISION = "cf9d4a232c005e18f89de281561eb20e8528c79f"
VERSION = "v1.3.1"
BASELINES = {
    "6f410db1ff1e8479d32470edccc046ccffd7e6be": ("v1.2.1", "0089_maintenance_agent"),
    "c7c29430219933c0336e8280788dcb799f6253ab": ("v1.3.0", "0090_maintenance_run_details"),
}
_validate_inventory = stage.validate_inventory
_deployment_configs = stage.deployment_configs
_build_command = stage.build_command
_execute = stage.execute
_recover_record = stage.recover_record


def read_record(path):
    require(path.resolve(strict=True) == path and path.is_file(), "record_path_changed")
    return json.loads(path.read_text(encoding="utf-8"))


def select_profile(record):
    revision = record.get("revision")
    require(revision != REVISION, "release_already_deployed")
    profile = BASELINES.get(revision)
    require(profile is not None and record.get("version") == profile[0], "unsupported_baseline")
    stage.BASELINE = revision
    stage.BASELINE_VERSION, stage.BASELINE_SCHEMA = profile
    fragments = ["maintenance-agent-run-management.json"]
    if stage.BASELINE_SCHEMA == "0089_maintenance_agent":
        fragments.insert(0, "unified-knowledge-and-scan-details.json")
    stage.RELEASE_ENTRIES = [
        entry
        for fragment in fragments
        for entry in read_record(Path(__file__).resolve().parents[1] / "release-notes" / fragment)
    ]


def managed_path(record):
    managed = Path(record.get("managed_compose_file", ""))
    require(
        managed.parent.parent == stage.ROOT
        and re.fullmatch(r"release-[A-Za-z0-9]{10}", managed.parent.name)
        and managed.name == "kap-compose-private.json"
        and record.get("record_directory") == str(managed.parent),
        "managed_compose_path_changed",
    )
    require(
        managed.resolve(strict=True) == managed and managed.is_file(),
        "managed_compose_path_changed",
    )
    return managed


def check_managed(r, record, old):
    require(
        record.get("revision") == stage.BASELINE
        and record.get("version") == stage.BASELINE_VERSION,
        "current_release_record_changed",
    )
    managed = managed_path(record)
    previous = read_record(managed.parent / "report.json")
    require(
        previous.get("passed") is True
        and previous.get("checkpoint") == "complete"
        and previous.get("production_switched") is True
        and previous.get("revision") == stage.BASELINE
        and previous.get("version") == stage.BASELINE_VERSION
        and previous.get("managed_compose_file") == str(managed)
        and not previous.get("manual_recovery_required")
        and not previous.get("post_deployment_tasks_pending"),
        "previous_release_incomplete",
    )
    config = json.loads(
        r.docker("compose", "-p", "kap", "-f", str(managed), "config", "--format", "json")
    )
    require(set(config["services"]) == {n[4:-2] for n in stage.START}, "managed_services_changed")
    for name in stage.START:
        item, service = old[name], config["services"][name[4:-2]]
        require(
            item["State"]["Running"] and item["State"].get("Health", {}).get("Status") == "healthy",
            "baseline_service_not_healthy",
        )
        require(service["image"] == item["Image"], "managed_image_changed")
        require(
            item["Config"]["Labels"].get("com.docker.compose.project.config_files") == str(managed),
            "runtime_compose_reference_changed",
        )
        actual, expected = service["environment"], environment(item)
        require(
            actual == expected
            or {k: v.replace("$$", "$") if isinstance(v, str) else v for k, v in actual.items()}
            == expected,
            "managed_environment_changed",
        )


def capture_inventory(r, directory):
    # Called by stage.execute only after the exclusive deployment lock is held.
    require(not any(directory.iterdir()), "inventory_directory_not_empty")
    record = read_record(stage.ROOT / "current-release.json")
    select_profile(record)
    names = (
        *stage.START,
        "kap-migrate-1",
        *("WeKnora-" + s for s in ("app", "frontend", "docreader", "postgres", "redis")),
    )
    old = {name: r.inspect(name) for name in names}
    check_managed(r, record, old)
    write(directory / "runtime-private.json", old)
    write(directory / "current-release-before.json", record)
    write(
        directory / "report.json",
        {
            "running_release": {"version": record["version"], "commit": record["revision"]},
            "migration": stage.sql(
                r, old[stage.INFRA[0]], "SELECT version_num FROM alembic_version;"
            ),
            "repository_clean": not stage.git(r, "status", "--porcelain"),
        },
    )
    # Recheck identities, database/schema, repository, external tablespaces,
    # writable PG paths, runtime environment and the public release identity.
    return _validate_inventory(r, directory)


def deployment_configs(r, old, images, out):
    configs = _deployment_configs(r, old, images, out)
    for name, config in configs.items():
        previous = old[name]
        require(
            sorted(config["Env"]) == sorted(previous["Config"]["Env"]),
            "unexpected_environment_change",
        )
        for key in ("Cmd", "Entrypoint", "User", "WorkingDir", "Healthcheck", "StopSignal"):
            require(config.get(key) == previous["Config"].get(key), "runtime_default_changed")
        for key in (
            "NanoCpus",
            "Memory",
            "MemorySwap",
            "MemoryReservation",
            "CpuPeriod",
            "CpuQuota",
            "ShmSize",
        ):
            require(
                config["HostConfig"].get(key) == previous["HostConfig"].get(key),
                "runtime_resource_changed",
            )
    return configs


def build_command(component, source, tag, encoded):
    command = _build_command(component, source, tag, encoded)
    if component == "backend":
        # Build-only network tuning. The archived application and requirements
        # lock remain untouched; pip still checks every locked hash over HTTPS.
        dockerfile = source / "backend" / "Dockerfile"
        original = dockerfile.read_text(encoding="utf-8")
        line = "RUN pip install --no-cache-dir --require-hashes -r requirements.lock"
        require(original.count(line) == 1, "pip_build_step_changed")
        replacement = (
            "RUN pip install --no-cache-dir --require-hashes "
            "--index-url https://mirrors.cloud.tencent.com/pypi/simple "
            "--timeout 120 --retries 5 -r requirements.lock"
        )
        tuned = source / "backend" / "Dockerfile.maintenance-build"
        with tuned.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(original.replace(line, replacement))
        command[-1:-1] = ["-f", str(tuned)]
        print("Python 依赖：腾讯云 HTTPS 镜像，120 秒超时，保留锁定版本和哈希校验。", flush=True)
    return command


def execute(r, inventory, out, report, holder):
    _execute(r, inventory, out, report, holder)
    # Compare the pre-migration columns of every existing business table. The
    # additive nullable columns must not rewrite existing business data.
    require(report.get("business_data_preserved") is True, "existing_data_verification_missing")
    report.update(
        existing_agent_configuration_preserved=True,
        database_schema_changed=stage.SCHEMA != stage.BASELINE_SCHEMA,
        previous_revision=stage.BASELINE,
        previous_version=stage.BASELINE_VERSION,
    )


def restore_profile(inventory, out):
    require(
        inventory.parent == stage.ROOT and inventory.resolve(strict=True) == inventory,
        "unexpected_record_directory",
    )
    select_profile(read_record(inventory / "current-release-before.json"))
    manifest = read_record(out / "release-manifest.json")
    require(
        manifest.get("commit") == REVISION
        and manifest.get("version") == VERSION
        and manifest.get("previous_commit") == stage.BASELINE,
        "recovery_release_mismatch",
    )


def recover_record(r, inventory, out):
    restore_profile(inventory, out)
    return _recover_record(r, inventory, out)


def configure():
    stage.REVISION, stage.VERSION = REVISION, VERSION
    stage.BASELINE = stage.BASELINE_VERSION = stage.BASELINE_SCHEMA = "unselected"
    stage.SCHEMA = "0091_maintenance_batch_progress"
    stage.RELEASE_TITLE = "巡检管理、后台更新与多尺寸布局优化"
    stage.RELEASE_ENTRIES = []
    stage.ADDED = ()
    stage.ORIGINAL_START = stage.START
    stage.STOP_APPS = ("kap-frontend-1", "kap-backend-1", "kap-beat-1", *stage.CONSUMERS)
    # Every consumer already exists on v1.2.1. Keep its current queues/resources.
    stage.COMMANDS, stage.RESOURCES = {}, {}
    stage.validate_inventory = capture_inventory
    stage.deployment_configs = deployment_configs
    stage.build_command = build_command
    stage.execute = execute
    stage.recover_record = recover_record


def main(configure_profile=None):
    (configure_profile or configure)()
    if "--finalize" in sys.argv:
        # Retry only post-opening housekeeping; no rebuild, restart or restore.
        sys.argv.remove("--finalize")
        import finalize_stage_release

        finalize = finalize_stage_release.finalize

        def with_profile(r, out, result):
            pointer = out / "inventory-path.txt"
            require(pointer.resolve(strict=True) == pointer, "record_path_changed")
            restore_profile(Path(pointer.read_text().strip()), out)
            return finalize(r, out, result)

        finalize_stage_release.finalize = with_profile
        return finalize_stage_release.main()
    return stage.main()


if __name__ == "__main__":
    raise SystemExit(main())
