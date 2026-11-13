"""Finish an already-opened stage rollout without restarting services or restoring data."""

import argparse
import json
import os
from pathlib import Path
import re
import traceback

import deploy_stage_release as deploy
from prepare_production_release import Runner, require
from production_cutover_runtime import LABEL, Runtime
from rollout_vision_fix import public_health, write


def validate_records(out):
    state = json.loads((out / "state-private.json").read_text())
    report = json.loads((out / "report.json").read_text())
    old = json.loads((out / "runtime-private.json").read_text())
    images = json.loads((out / "candidate-image-ids.json").read_text())
    configs = json.loads((out / "candidate-runtime-private.json").read_text())
    require(
        report.get("phase") == "production_stage_rollout"
        and report.get("revision") == deploy.REVISION
        and report.get("version") == deploy.VERSION
        and report.get("production_switched") is True,
        "unexpected_release_record",
    )
    require(
        state.get("traffic_opening") is True
        and state.get("backup_complete") is True
        and state.get("data_mutated") is True
        and not state.get("recovered")
        and not state.get("recovery_opening"),
        "not_opened_rollout",
    )
    require(
        set(state["new"]) == set(configs) == set(deploy.START)
        and set(old)
        == set(deploy.ORIGINAL_START)
        | {"kap-migrate-1"}
        | {"WeKnora-" + s for s in ("app", "frontend", "docreader", "postgres", "redis")}
        and state["originals"] == {n: old[n] for n in deploy.ORIGINAL_START},
        "runtime_journal_mismatch",
    )
    require(set(images) == {"backend", "frontend"}, "unexpected_candidate_images")
    require(
        all(re.fullmatch(r"sha256:[a-f0-9]{64}", value) for value in images.values()),
        "invalid_candidate_image_identity",
    )
    require(
        all(re.fullmatch(r"[a-f0-9]{64}", value) for value in state["new"].values()),
        "invalid_container_identity",
    )
    for name, config in configs.items():
        expected = (
            old[name]["Image"]
            if name in deploy.INFRA
            else images["frontend" if name == "kap-frontend-1" else "backend"]
        )
        require(
            config["Image"] == expected and config["Labels"].get(LABEL) == out.name,
            "candidate_runtime_changed",
        )
    return state, old, images, configs


def verify_live(r, out, state, old, configs):
    rows = []
    for name in deploy.START:
        item = r.inspect(name)
        require(
            item["Id"] == state["new"][name]
            and item["Name"] == "/" + name
            and item["Image"] == configs[name]["Image"]
            and item["Config"].get("Labels", {}).get(LABEL) == out.name,
            "live_container_identity_changed",
        )
        require(
            item["State"]["Running"] and item["State"].get("Health", {}).get("Status") == "healthy",
            "live_service_not_healthy",
        )
        rows.append({"container": name, "running": True, "health": "healthy"})
    require(
        deploy.sql(r, old[deploy.INFRA[0]], "SELECT version_num FROM alembic_version;")
        == deploy.SCHEMA,
        "live_schema_changed",
    )
    require(
        deploy.sql(
            r,
            old[deploy.INFRA[0]],
            "SELECT count(*) FROM release_notes WHERE version='"
            + deploy.VERSION
            + "' AND source_commit='"
            + deploy.REVISION
            + "' AND deployed_at IS NOT NULL;",
        )
        == "1",
        "release_registration_missing",
    )
    public_health(r, state["new"]["kap-backend-1"], deploy.REVISION, deploy.VERSION)
    deploy.unchanged(r, {n: item for n, item in old.items() if n not in deploy.ORIGINAL_START})
    return rows


def check_managed_compose(r, out, configs):
    managed = out / "kap-compose-private.json"
    require(managed.is_file() and not managed.is_symlink(), "managed_compose_missing")
    rendered = json.loads(
        r.docker("compose", "-p", "kap", "-f", str(managed), "config", "--format", "json")
    )
    require(set(rendered["services"]) == {n[4:-2] for n in configs}, "managed_services_changed")
    for name, config in configs.items():
        service = rendered["services"][name[4:-2]]
        require(service["image"] == config["Image"], "managed_image_changed")
        expected_env = dict(x.split("=", 1) for x in config["Env"])
        environment = service["environment"]
        require(
            environment == expected_env
            or {
                k: v.replace("$$", "$") if isinstance(v, str) else v for k, v in environment.items()
            }
            == expected_env,
            "managed_environment_changed",
        )
    return managed


def source_state(r):
    require(deploy.REPO.resolve(strict=True) == deploy.REPO, "unexpected_repository_path")
    head = deploy.git(r, "rev-parse", "HEAD")
    require(head in {deploy.BASELINE, deploy.REVISION}, "repository_revision_changed")
    require(not deploy.git(r, "status", "--porcelain"), "repository_has_changes")
    return head


def source_owner():
    import pwd

    return pwd.getpwuid(deploy.REPO.stat().st_uid).pw_name


def finalize(r, out, result):
    state, old, images, configs = validate_records(out)
    result["services"] = verify_live(r, out, state, old, configs)
    managed = check_managed_compose(r, out, configs)
    head = source_state(r)
    # Preserve the failed rollout report once; subsequent retries keep its evidence.
    original_report = out / "report-before-finalization.json"
    if not original_report.exists():
        with original_report.open("xb") as stream:
            stream.write((out / "report.json").read_bytes())
    result["checkpoint"] = "source_sync"
    print("=== 2/3 同步源码与运维镜像引用；保持所有服务运行 ===", flush=True)
    if head != deploy.REVISION:
        owner = source_owner()
        r.capture(
            "runuser",
            "-u",
            owner,
            "--",
            "git",
            "-c",
            "safe.directory=" + str(deploy.REPO),
            "-C",
            str(deploy.REPO),
            "merge",
            "--ff-only",
            deploy.REVISION,
        )
    require(source_state(r) == deploy.REVISION, "source_sync_incomplete")
    runtime = object.__new__(Runtime)
    runtime.r, runtime.directory, runtime.token, runtime.state = r, out, out.name, state
    roles = {n[4:-2]: configs[n]["Image"] for n in deploy.START if n not in deploy.INFRA}
    roles["migrate"] = images["backend"]
    result["checkpoint"] = "operational_tags"
    runtime.configure_entrypoints([], managed, roles)
    result["checkpoint"] = "release_record"
    write(
        deploy.ROOT / "current-release.json",
        {
            "version": deploy.VERSION,
            "revision": deploy.REVISION,
            "managed_compose_file": str(managed),
            "record_directory": str(out),
        },
    )
    result["services"] = verify_live(r, out, state, old, configs)
    state["passed"] = True
    runtime.save()
    print("=== 3/3 核对上线结果，清理本轮已停止的旧容器 ===", flush=True)
    pending = []
    for name in deploy.ORIGINAL_START:
        previous = old[name]
        try:
            present = r.docker("ps", "-aq", "--no-trunc", "--filter", "id=" + previous["Id"])
            if not present:
                continue
            require(present == previous["Id"], "old_container_identity_changed")
            item = r.inspect(previous["Id"])
            require(
                not item["State"]["Running"]
                and item["Name"] == "/" + name + "-previous-" + out.name[-10:]
                and item["Image"] == previous["Image"],
                "old_container_identity_changed",
            )
            r.docker("rm", previous["Id"])  # No -v: keep every runtime and backup volume.
        except Exception:
            pending.append("retained_original:" + name)
    result.update(
        passed=True,
        checkpoint="complete",
        version=deploy.VERSION,
        revision=deploy.REVISION,
        migration_target=deploy.SCHEMA,
        source_updated=True,
        release_recorded=True,
        operational_image_references_updated=True,
        managed_compose_file=str(managed),
        old_images_and_cold_copies_retained=True,
        post_deployment_tasks_pending=pending,
    )
    updated = json.loads((out / "report.json").read_text())
    for key in ("error", "manual_recovery_required", "automatic_data_restore_skipped"):
        updated.pop(key, None)
    updated.update({k: v for k, v in result.items() if k not in {"phase", "services"}})
    write(out / "report.json", updated)


def main():
    import fcntl

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    os.environ["GIT_OPTIONAL_LOCKS"] = "0"
    out = args.record.resolve(strict=True)
    require(
        out.parent == deploy.ROOT and re.fullmatch(r"release-[A-Za-z0-9]{10}", out.name),
        "unexpected_record_directory",
    )
    result = {
        "phase": "production_stage_finalization",
        "passed": False,
        "production_switched": True,
        "raw_logs_included": False,
        "checkpoint": "verification",
        "containers_restarted": False,
        "database_migration_performed": False,
        "data_restored": False,
    }
    with (deploy.ROOT / "deployment.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with (out / "finalization-private.log").open("ab") as log:
            try:
                print("=== 1/3 核对新版容器、数据库、正式入口与部署记录 ===", flush=True)
                finalize(Runner(log), out, result)
            except Exception as exc:
                log.write(traceback.format_exc().encode())
                safe = {
                    "unexpected_release_record",
                    "not_opened_rollout",
                    "runtime_journal_mismatch",
                    "unexpected_candidate_images",
                    "invalid_candidate_image_identity",
                    "invalid_container_identity",
                    "candidate_runtime_changed",
                    "live_container_identity_changed",
                    "live_service_not_healthy",
                    "live_schema_changed",
                    "release_registration_missing",
                    "managed_compose_missing",
                    "managed_services_changed",
                    "managed_image_changed",
                    "managed_environment_changed",
                    "unexpected_repository_path",
                    "repository_revision_changed",
                    "repository_has_changes",
                    "source_sync_incomplete",
                    "unexpected operational image",
                    "duplicate operational tag journal",
                    "operational tag target changed",
                    "operational tag concurrently changed",
                    "operational image tag changed",
                }
                result["error"] = str(exc) if str(exc) in safe else type(exc).__name__
                print("收尾停止；保留运行中的新版和当前数据，不执行回退。", flush=True)
            finally:
                write(out / "finalization-report.json", result)
                print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0 if result["passed"] and not result.get("post_deployment_tasks_pending") else 1


if __name__ == "__main__":
    raise SystemExit(main())
