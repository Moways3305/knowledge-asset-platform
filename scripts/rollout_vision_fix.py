"""Replace only the two verified KAP application images; never restore business data."""

import argparse
import copy
import json
import os
import signal
import traceback
import uuid
from pathlib import Path

from execute_production_cutover import START, health, wait_services
from prepare_production_release import Runner, fingerprint, preserve_rollback_image, require
from prepare_vision_fix import BASELINE, PROBE, verify_images
from production_cutover_runtime import Engine, Runtime, endpoints, payload

REVISION = "36fb851aa3e940cba0e877bf7c3429b6ba4c1d56"
STAGE = Path("/data/kap/vision-fix-preparations/run-5PJvWL")
TARGETS = ("kap-backend-1", "kap-frontend-1")
IMAGES = {
    "backend": "sha256:7d83b98ca787cb5e8e34cfa017836fb340ff23052bffc68825d712af94f230e5",
    "frontend": "sha256:16745de9cb48646805ed72dccef4cd5d54d9b8cbf1531533cdeccc02f3480dfa",
}
MANAGED = Path(
    "/data/weknora/upgrade-rehearsals/run-eDkLxh7B/production-preparations/"
    "20261105-160843-7ce5bf/cutover-execute-e94a8db7a6/kap-compose-private.json"
)
REPO = Path("/data/kap/repo")
ORIGIN = "https://kap.moways.com.cn"


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def check_unchanged(r, old, excluded=()):
    for name, previous in old.items():
        if name in excluded:
            continue
        current = r.inspect(name)
        require(
            fingerprint(current) == fingerprint(previous)
            and endpoints(current) == endpoints(previous)
            and current["State"]["Running"],
            "production container changed",
        )


def next_compose(original, old, images):
    require(set(images) == {"backend", "frontend"}, "unexpected patch component")
    expected = {name[4:-2]: item for name, item in old.items() if name.startswith("kap-")}
    require(set(original["services"]) == set(expected), "managed service list changed")
    result = copy.deepcopy(original)
    for service, item in expected.items():
        require(
            result["services"][service]["image"] == item["Image"],
            "managed image differs from running image",
        )
    for service, image in images.items():
        result["services"][service]["image"] = image
    return result


class ApplicationRuntime(Runtime):
    """Reuse exact-container recovery only; prohibit every storage rollback path."""

    def recover(self, start_order):
        require(
            set(self.state["originals"]) == set(TARGETS)
            and tuple(start_order) == TARGETS
            and not self.state["data_mutated"]
            and not self.state["backup_complete"]
            and not self.state["backups"]
            and not self.state["config_replacements"]
            and not self.state["passed"],
            "application-only recovery guard failed",
        )
        # No database/filesystem snapshot exists in this transaction. New writes
        # remain in place even if the application has already accepted traffic.
        super().recover(start_order)


def public_health(r, identity, revision, version):
    code = (
        "import asyncio,httpx; from app.services.release_deployment import verify_deployment; "
        "from types import SimpleNamespace; "
        "m=SimpleNamespace(version=" + repr(version) + ",commit=" + repr(revision) + ");\n"
        "async def run():\n"
        " async with httpx.AsyncClient(base_url="
        + repr(ORIGIN)
        + ",timeout=20,follow_redirects=False) as c:\n"
        "  await verify_deployment(c,m)\n"
        "asyncio.run(run())"
    )
    r.docker("exec", identity, "python", "-c", code, timeout=100)


def validate(r, stage, out):
    require((stage / "VERIFIED").read_text().strip() == REVISION, "candidate not verified")
    report = read(stage / "report.json")
    manifest = read(stage / "release-manifest.json")
    images = read(stage / "candidate-image-ids.json")
    require(
        report.get("passed") is True
        and report.get("production_unchanged") is True
        and report.get("production_switched") is False
        and report.get("revision") == REVISION
        and report.get("candidate_images") == images == IMAGES
        and manifest.get("version") == "v1.0.1"
        and manifest.get("commit") == REVISION
        and manifest.get("previous_commit") == BASELINE,
        "candidate records differ from accepted evidence",
    )
    source = stage / "source"
    require(
        r.capture("git", "-C", str(source), "rev-parse", "HEAD") == REVISION
        and not r.capture("git", "-C", str(source), "status", "--porcelain"),
        "candidate source changed",
    )
    changed = set(
        r.capture(
            "git",
            "-C",
            str(source),
            "diff",
            "--name-only",
            BASELINE,
            REVISION,
            "--",
            "backend/app",
            "backend/alembic",
            "backend/requirements.lock",
        ).splitlines()
    )
    require(
        changed
        == {
            "backend/app/services/vision_check.py",
            "backend/app/services/weknora_client.py",
            "backend/app/services/weknora_models.py",
        },
        "patch changes unexpected backend or schema files",
    )
    require(
        r.capture("git", "-C", str(REPO), "rev-parse", "HEAD") == BASELINE
        and not r.capture("git", "-C", str(REPO), "status", "--porcelain"),
        "production checkout changed",
    )
    old = read(stage / "runtime-private.json")
    require(set(old) == set(START), "incomplete preparation runtime")
    check_unchanged(r, old)
    health(r, revision=BASELINE)
    verify_images(r, images, manifest)
    managed = out / "kap-compose-private.json"
    write(managed, next_compose(read(MANAGED), old, images))
    # Validate only. Actual replacement uses preserved Docker runtime, not Compose.
    r.docker("compose", "-p", "kap", "-f", str(managed), "config", "--quiet")
    configs = {}
    rollback = {}
    for service, image in images.items():
        name = "kap-" + service + "-1"
        previous = old[name]
        require(r.image_identity("kap-" + service + ":latest") == previous["Image"], "tag changed")
        before = json.loads(r.docker("image", "inspect", previous["Image"]))[0]["Config"]
        after = json.loads(r.docker("image", "inspect", image))[0]["Config"]
        config = payload(previous, image, after, before, out.name, publish=True)
        for key in ("Cmd", "Entrypoint", "User", "WorkingDir", "Healthcheck", "StopSignal"):
            require(config.get(key) == previous["Config"].get(key), "runtime default changed")
        require(
            sorted(config["Env"]) == sorted(previous["Config"]["Env"]),
            "application environment changed",
        )
        configs[name] = config
        rollback[name] = preserve_rollback_image(r, name, previous, out.name)
    write(out / "rollback-images.json", rollback)
    write(out / "candidate-runtime-private.json", configs)
    return old, configs, managed


def replace(runtime, configs, verify):
    """Health callbacks can fail; caller must invoke guarded application recovery."""
    require(set(configs) == set(TARGETS), "unexpected replacement target")
    runtime.freeze(tuple(reversed(TARGETS)))
    runtime.detach_originals()
    for name in TARGETS:
        runtime.create(name, configs[name])
        runtime.start(name)
        verify(name)


def finish(r, runtime, report):
    """After the commit marker, housekeeping failures never roll back live data/code."""
    pending = []
    try:
        require(
            r.capture("git", "-C", str(REPO), "rev-parse", "HEAD") == BASELINE
            and not r.capture("git", "-C", str(REPO), "status", "--porcelain"),
            "production checkout changed",
        )
        r.capture("git", "-C", str(REPO), "merge", "--ff-only", REVISION)
        report["production_source_updated"] = True
    except Exception:
        pending.append("production_source_sync")
    try:
        r.docker(
            "exec",
            "kap-backend-1",
            "python",
            "-m",
            "app.commands.sync_release_notes",
            "--origin",
            ORIGIN,
            timeout=120,
        )
        report["release_recorded"] = True
    except Exception:
        pending.append("release_record")
    try:
        # Retained Compose labels would collide with future deployments. Remove
        # only these stopped originals; immutable rollback images/configs stay.
        for name, previous in runtime.state["originals"].items():
            current = r.inspect(previous["Id"])
            require(
                not current["State"]["Running"]
                and current["Image"] == previous["Image"]
                and current["Name"] == "/" + name + "-previous-" + runtime.token[-10:],
                "old application cleanup identity changed",
            )
            r.docker("rm", previous["Id"])
        report["old_application_containers_removed"] = True
    except Exception:
        pending.append("old_application_container_cleanup")
    report["post_deployment_tasks_pending"] = pending


def interrupted(signum, frame):
    raise RuntimeError("deployment interrupted")


def main():
    import fcntl

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    stage = args.stage.resolve(strict=True)
    require(stage == STAGE, "unexpected accepted preparation")
    with (stage.parent / "prepare.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(
            not (stage / "ROLLOUT_STARTED").exists(), "deployment already attempted; do not repeat"
        )
        out = stage / ("deploy-" + uuid.uuid4().hex[:10])
        out.mkdir(mode=0o700)
        report = {
            "phase": "vision_fix_rollout",
            "passed": False,
            "production_switched": False,
            "raw_logs_included": False,
            "checkpoint": "preflight",
            "version": "v1.0.1",
            "revision": REVISION,
        }
        runtime = None
        with (out / "private.log").open("ab") as log:
            r = Runner(log)
            try:
                signal.signal(signal.SIGTERM, interrupted)
                signal.signal(signal.SIGINT, interrupted)
                print("补丁切换记录目录：" + str(out), flush=True)
                print("=== 1/4 核对验收镜像及当前生产，保留前后端回退配置 ===", flush=True)
                old, configs, managed = validate(r, stage, out)
                runtime = ApplicationRuntime(
                    r, Engine(log), out, {name: old[name] for name in TARGETS}, IMAGES["backend"]
                )
                check_unchanged(r, old)
                with (stage / "ROLLOUT_STARTED").open("x") as marker:
                    marker.write(str(out) + "\n")
                    marker.flush()
                    os.fsync(marker.fileno())
                report["checkpoint"] = "application_replacement"
                print("=== 2/4 仅替换 KAP 前后端，等待服务就绪 ===", flush=True)

                def verify(name):
                    if name == "kap-backend-1":
                        health(r, revision=REVISION)
                    wait_services(runtime, [name])

                replace(runtime, configs, verify)
                report["production_switched"] = True
                report["checkpoint"] = "live_verification"
                print("=== 3/4 验证正式入口版本与两款模型的图片理解 ===", flush=True)
                public_health(r, runtime.state["new"]["kap-backend-1"], REVISION, "v1.0.1")
                result = json.loads(
                    r.docker(
                        "exec",
                        "-i",
                        runtime.state["new"]["kap-backend-1"],
                        "python",
                        "-",
                        data=PROBE.encode(),
                        timeout=180,
                    )
                )
                report["checks"] = result.get("checks", [])
                require(result.get("passed") is True, "deployed vision check failed")
                r.docker(
                    "exec",
                    "kap-backend-1",
                    "python",
                    "-m",
                    "app.commands.sync_release_notes",
                    "--check-only",
                    timeout=60,
                )
                check_unchanged(r, old, TARGETS)
                report["other_services_unchanged"] = True
                report["checkpoint"] = "operational_references"
                runtime.configure_entrypoints([], managed, IMAGES)
                # Both application versions share the same schema. No database
                # or file backup is made/restored by this patch at any point.
                runtime.state["passed"] = True
                runtime.save()
                report.update(
                    passed=True,
                    checkpoint="complete",
                    candidate_images=IMAGES,
                    operational_image_references_updated=True,
                    managed_compose_file=str(managed),
                    rollback_images_preserved=True,
                    database_migration_performed=False,
                    model_configuration_changed=False,
                )
                print("=== 4/4 同步发布记录与源码，清理已退出的旧前后端容器 ===", flush=True)
                finish(r, runtime, report)
            except BaseException as exc:
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
                signal.signal(signal.SIGINT, signal.SIG_IGN)
                log.write(traceback.format_exc().encode())
                report["error"] = "rollout_failed_private_details_retained"
                safe_reasons = {
                    "candidate records differ from accepted evidence": "candidate_evidence_changed",
                    "candidate source changed": "candidate_source_changed",
                    "production checkout changed": "production_checkout_changed",
                    "production container changed": "production_container_changed",
                    "managed service list changed": "managed_service_list_changed",
                    "managed image differs from running image": "managed_image_changed",
                    "tag changed": "operational_tag_changed",
                    "runtime default changed": "runtime_default_changed",
                    "application environment changed": "runtime_environment_changed",
                    "deployed vision check failed": "deployed_vision_check_failed",
                    "deployment interrupted": "deployment_interrupted",
                }
                if str(exc) in safe_reasons:
                    report["diagnostic"] = safe_reasons[str(exc)]
                if runtime is not None and not runtime.state["passed"]:
                    try:
                        print(
                            "切换未通过，正在恢复旧前后端容器；保留当前数据库和文件。", flush=True
                        )
                        runtime.recover(TARGETS)
                        health(r, revision=BASELINE)
                        public_health(r, old["kap-backend-1"]["Id"], BASELINE, "v1.0.0")
                        check_unchanged(r, old)
                        report.update(
                            previous_applications_recovered=True, production_switched=False
                        )
                    except BaseException:
                        log.write(traceback.format_exc().encode())
                        report["previous_applications_recovered"] = False
                        report["manual_recovery_required"] = True
                        report["production_switched"] = None
                report["passed"] = False
            finally:
                write(out / "report.json", report)
                print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
                print("补丁切换记录目录：" + str(out), flush=True)
    return 0 if report["passed"] and not report.get("post_deployment_tasks_pending") else 1


if __name__ == "__main__":
    raise SystemExit(main())
