"""Prepare pinned production artifacts and private recovery material; never switch production."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import traceback
import uuid
from urllib.parse import urlsplit

KAP_SERVICES = (
    "backend",
    "worker",
    "ocr_worker",
    "beat",
    "frontend",
    "migrate",
    "postgres",
    "redis",
)
KAP_NAMES = {"kap-" + s + "-1" for s in KAP_SERVICES}
WK_NAMES = {"WeKnora-" + s for s in ("app", "frontend", "docreader", "postgres", "redis")}
REHEARSAL_LABEL = "kap.weknora.rehearsal"
BASELINE = "ae8be0a2b425dbc8be645e6444bcfba54b0f691b"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def preserve_rollback_image(runner, name, item, token, *, allow_completed_migrate=False):
    image_id = item.get("Image", "")
    require(re.fullmatch(r"sha256:[a-f0-9]{64}", image_id), "生产镜像 ID 格式不正确")
    identity = runner.image_identity(image_id)
    if identity is None:
        state = item.get("State") or {}
        labels = item.get("Config", {}).get("Labels") or {}
        restart = item.get("HostConfig", {}).get("RestartPolicy", {}).get("Name")
        completed_migrate = (
            name == "kap-migrate-1"
            and item.get("Name") == "/kap-migrate-1"
            and state.get("Status") == "exited"
            and state.get("Running") is False
            and state.get("ExitCode") == 0
            and not state.get("Dead")
            and not state.get("Restarting")
            and restart in {"no", ""}
            and labels.get("com.docker.compose.project") == "kap"
            and labels.get("com.docker.compose.service") == "migrate"
            and not labels.get(REHEARSAL_LABEL)
        )
        require(
            allow_completed_migrate and completed_migrate,
            "回滚镜像缺失；仅允许显式豁免已成功结束且不自动重启的历史迁移容器",
        )
        return {
            "image_id": image_id,
            "tag": None,
            "status": "completed_job_image_missing",
            "container_preserved": True,
            "recreate_on_rollback": False,
        }
    require(identity == image_id, "生产镜像身份不匹配")
    tag = "kap-rollback:" + token + "-" + name.lower().replace("_", "-")
    runner.docker("tag", image_id, tag)
    require(runner.image_identity(tag) == image_id, "回滚标签镜像身份不匹配")
    return {
        "image_id": image_id,
        "tag": tag,
        "status": "preserved",
        "recreate_on_rollback": name != "kap-migrate-1",
    }


def fingerprint(item):
    data = {k: item[k] for k in ("Id", "Image", "Config", "HostConfig")}
    data["Mounts"] = sorted(item.get("Mounts", []), key=lambda m: json.dumps(m, sort_keys=True))
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def removable_fixture(item, protected_volumes):
    """Image-inherited Compose labels are never sufficient authorization to remove a container."""
    name = item["Name"].lstrip("/")
    labels = item["Config"].get("Labels") or {}
    root = labels.get(REHEARSAL_LABEL, "")
    if not re.fullmatch(r"wk-live-[a-f0-9]{10}-(probe|egress|ui)", name):
        return False
    if not re.fullmatch(r"/data/weknora/upgrade-rehearsals/run-[A-Za-z0-9]+", root):
        return False
    for mount in item.get("Mounts", []):
        if mount.get("Name") in protected_volumes:
            return False
        if mount["Type"] != "bind" or not Path(mount["Source"]).resolve().is_relative_to(
            Path(root).resolve()
        ):
            return False
        if mount["Destination"] not in {"/probe", "/evidence"}:
            return False
    return True


class Runner:
    def __init__(self, log):
        self.log = log

    def capture(self, *args, cwd=None, data=None, timeout=60):
        result = subprocess.run(
            args, cwd=cwd, input=data, stdout=subprocess.PIPE, stderr=self.log, timeout=timeout
        )
        require(
            result.returncode == 0, "操作失败，详细信息已保存在 private.log；不要粘贴原始日志。"
        )
        return result.stdout.decode().strip()

    def docker(self, *args, **kw):
        return self.capture("docker", *args, **kw)

    def inspect(self, name):
        return json.loads(self.docker("inspect", name))[0]

    def image_identity(self, reference):
        result = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", reference],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
        if result.stderr:
            self.log.write(result.stderr)
        if result.returncode:
            if b"no such image" in result.stderr.lower():
                return None
            raise RuntimeError("镜像检查失败；详见 private.log，不得按镜像缺失跳过")
        identity = result.stdout.decode().strip()
        require(re.fullmatch(r"sha256:[a-f0-9]{64}", identity), "镜像检查返回无效 ID")
        return identity

    def execute(self, args, *, cwd=None, timeout=3600):
        started = time.monotonic()
        notice = started + 60
        process = subprocess.Popen(args, cwd=cwd, stdout=self.log, stderr=self.log)
        try:
            while process.poll() is None:
                now = time.monotonic()
                require(now - started < timeout, "准备步骤超时；生产尚未切换。")
                if now >= notice:
                    print(f"当前步骤仍在运行，已用时 {int(now - started)} 秒。", flush=True)
                    notice = now + 60
                time.sleep(1)
            require(process.returncode == 0, "准备步骤失败；生产尚未切换，详见受限日志。")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def dump_databases(runner, name, item, stage):
    env = dict(line.split("=", 1) for line in item["Config"]["Env"] if "=" in line)
    user = env.get("POSTGRES_USER", "postgres")
    prefix = ["docker", "exec", "-i", name]
    query = "SELECT coalesce(json_agg(datname ORDER BY datname),'[]'::json) FROM pg_database WHERE datallowconn AND NOT datistemplate"
    databases = json.loads(
        runner.capture(
            *prefix,
            "psql",
            "-XqAt",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            user,
            "-d",
            "postgres",
            "-c",
            query,
        )
    )
    entries = []
    for index, database in enumerate(databases):
        archive = stage / f"{name}-database-{index}.dump"
        with archive.open("xb") as output:
            result = subprocess.run(
                [*prefix, "pg_dump", "-U", user, "-d", database, "-Fc", "--lock-wait-timeout=30s"],
                stdout=output,
                stderr=runner.log,
                timeout=1800,
            )
        require(
            result.returncode == 0 and archive.stat().st_size > 0,
            "数据库在线备份失败；生产尚未切换。",
        )
        with archive.open("rb") as source:
            result = subprocess.run(
                [*prefix, "pg_restore", "--list"],
                stdin=source,
                stdout=runner.log,
                stderr=runner.log,
                timeout=120,
            )
        require(result.returncode == 0, "备份归档目录校验失败；生产尚未切换。")
        entries.append(
            {"database": database, "archive": str(archive), "bytes": archive.stat().st_size}
        )
    globals_path = stage / f"{name}-globals-private.sql"
    with globals_path.open("xb") as output:
        result = subprocess.run(
            [*prefix, "pg_dumpall", "-U", user, "--globals-only"],
            stdout=output,
            stderr=runner.log,
            timeout=120,
        )
    require(result.returncode == 0 and globals_path.stat().st_size > 0, "数据库角色备份失败")
    return entries


def main():
    import fcntl

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--build-stage", required=True, type=Path)
    parser.add_argument("--version", default="1.0.0")
    parser.add_argument(
        "--allow-missing-completed-migrate-image",
        action="store_true",
        help="仅允许已成功结束的 kap-migrate-1 缺失原镜像；保留容器且禁止将其作为回滚重建目标",
    )
    args = parser.parse_args()
    require(re.fullmatch(r"[a-f0-9]{40}", args.revision), "必须固定完整提交")
    os.umask(0o077)
    repo = Path("/data/kap/repo")
    build = args.build_stage.resolve(strict=True)
    require(
        build.parent.parent == Path("/data/weknora/upgrade-rehearsals")
        and build.name.startswith("keyword-build-"),
        "构建记录目录不匹配",
    )
    root = build.parent / "production-preparations"
    root.mkdir(mode=0o700, exist_ok=True)
    token = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    stage = root / token
    stage.mkdir()
    print("生产部署准备目录：" + str(stage), flush=True)
    report = {
        "phase": "production_release_preparation",
        "production_switched": False,
        "passed": False,
    }
    with (root / "prepare.lock").open("a") as lock, (stage / "private.log").open("ab") as log:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = Runner(log)
        try:
            build = args.build_stage.resolve(strict=True)
            require(
                build.parent.parent == Path("/data/weknora/upgrade-rehearsals")
                and build.name.startswith("keyword-build-"),
                "构建记录目录不匹配",
            )
            require(
                r.capture("git", "-C", str(repo), "rev-parse", "HEAD") == BASELINE,
                "生产源码基线已变化，停止准备。",
            )
            require(
                not r.capture("git", "-C", str(repo), "status", "--porcelain"),
                "生产工作区存在未提交修改，停止准备。",
            )
            require(shutil.disk_usage(stage).free > 30 * 1024**3, "可用磁盘不足 30 GiB")

            print("=== 1/4 结束隔离 UI，核对生产容器并清理 Compose 标签冲突 ===", flush=True)
            ui_stage = build.parent / "live090-99b59b1df6"
            require(ui_stage.is_dir() and not ui_stage.is_symlink(), "隔离 UI 目录不匹配")
            (ui_stage / "ui-stop").touch()
            rehearsal_lock = (Path.home() / ".weknora-rehearsal.lock").open("a")
            for _ in range(120):
                try:
                    fcntl.flock(rehearsal_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(2)
            else:
                raise RuntimeError("隔离演练仍在运行，未清理任何容器；生产未切换。")
            originals = {name: r.inspect(name) for name in sorted(KAP_NAMES | WK_NAMES)}
            for name, item in originals.items():
                require(
                    not item["Config"].get("Labels", {}).get(REHEARSAL_LABEL),
                    "生产名称指向演练容器",
                )
                if name != "kap-migrate-1":
                    require(item["State"]["Running"], "存在未运行的生产服务，停止准备。")
            before = {name: fingerprint(item) for name, item in originals.items()}
            volumes = {
                m.get("Name")
                for item in originals.values()
                for m in item.get("Mounts", [])
                if m.get("Name")
            }
            ids = r.docker("ps", "-aq", "--filter", "label=com.docker.compose.project=kap").split()
            fixtures = []
            for item in json.loads(r.docker("inspect", *ids)) if ids else []:
                if item["Name"].lstrip("/") in KAP_NAMES:
                    continue
                require(
                    removable_fixture(item, volumes),
                    "发现无法确认归属的 Compose 同名项目容器，停止准备。",
                )
                fixtures.append(item)
            (stage / "removed-fixtures-private.json").write_text(json.dumps(fixtures))
            for item in fixtures:
                name = item["Name"].lstrip("/")
                with (stage / (name + "-private.log")).open("xb") as output:
                    subprocess.run(
                        ["docker", "logs", "--tail", "200", item["Id"]],
                        stdout=output,
                        stderr=output,
                        timeout=30,
                    )
                if item["State"]["Running"]:
                    r.docker("stop", "-t", "30", item["Id"])
                r.docker("rm", item["Id"])  # Deliberately no -v: retain every test volume.
            report["test_containers_removed"] = len(fixtures)

            print("=== 2/4 保留生产镜像、配置和数据库在线备份 ===", flush=True)
            (stage / "runtime-private.json").write_text(json.dumps(originals))
            rollback = {}
            config_paths = {repo / ".env", repo / "backend/.env"}
            for name, item in originals.items():
                rollback[name] = preserve_rollback_image(
                    r,
                    name,
                    item,
                    token,
                    allow_completed_migrate=args.allow_missing_completed_migrate_image,
                )
                (stage / "rollback-images.json").write_text(json.dumps(rollback, indent=2))
                if rollback[name]["status"] == "completed_job_image_missing":
                    report.setdefault("rollback_excluded_completed_jobs", []).append(name)
                    print(
                        "保留已成功结束的历史迁移容器；其原镜像缺失，不用于回滚重建。", flush=True
                    )
                labels = item["Config"].get("Labels") or {}
                workdir = Path(labels["com.docker.compose.project.working_dir"])
                config_paths.add(workdir / ".env")
                for path in labels["com.docker.compose.project.config_files"].split(","):
                    config_paths.add(Path(path))
                for mount in item.get("Mounts", []):
                    if (
                        mount["Type"] == "bind"
                        and mount["Destination"] == "/app/config/config.yaml"
                    ):
                        config_paths.add(Path(mount["Source"]))
            report["running_service_rollback_images_preserved"] = all(
                rollback[name]["status"] == "preserved"
                for name, item in originals.items()
                if item["State"]["Running"]
            )
            saved_configs = {}
            for path in sorted(config_paths):
                if path.is_file():
                    dest = stage / (
                        "config-private-" + hashlib.sha256(str(path).encode()).hexdigest()[:16]
                    )
                    shutil.copyfile(path, dest)
                    dest.chmod(0o600)
                    saved_configs[str(path)] = str(dest)
            (stage / "config-backups-private.json").write_text(json.dumps(saved_configs))
            compose_sources = {}
            for item in originals.values():
                labels = item["Config"]["Labels"]
                project = labels["com.docker.compose.project"]
                workdir = labels["com.docker.compose.project.working_dir"]
                files = labels["com.docker.compose.project.config_files"]
                key = (project, workdir, files)
                if key in compose_sources:
                    continue
                command = ["docker", "compose", "-p", project]
                for filename in files.split(","):
                    command.extend(["-f", filename])
                config = json.loads(r.capture(*command, "config", "--format", "json", cwd=workdir))
                dest = stage / f"compose-private-{len(compose_sources)}.json"
                dest.write_text(json.dumps(config))
                compose_sources[key] = str(dest)
            (stage / "compose-sources-private.json").write_text(
                json.dumps(
                    [
                        {"project": k[0], "directory": k[1], "files": k[2], "resolved": v}
                        for k, v in compose_sources.items()
                    ]
                )
            )
            (stage / "rollback-images.json").write_text(json.dumps(rollback, indent=2))
            backups = {
                name: dump_databases(r, name, originals[name], stage)
                for name in ("kap-postgres-1", "WeKnora-postgres")
            }
            (stage / "database-backups-private.json").write_text(json.dumps(backups))
            report["database_archives_readable"] = True
            report["consistent_files_backup_pending_cutover"] = True

            print("=== 3/4 固定候选源码及已通过验收的 WeKnora 镜像 ===", flush=True)
            source = stage / "source"
            r.capture(
                "git",
                "-C",
                str(repo),
                "worktree",
                "add",
                "--detach",
                str(source),
                args.revision,
                timeout=120,
            )
            for relative in (".env", "backend/.env"):
                require((repo / relative).is_file(), "生产环境配置文件缺失")
                shutil.copyfile(repo / relative, source / relative)
                (source / relative).chmod(0o600)
            sys.path.insert(0, str(source / "scripts"))
            import weknora_pg_upgrade_rehearsal as pg
            import weknora_app_rehearsal as app
            from weknora_keyword_app_rehearsal import passed_offline_for_build

            pg.PRIVATE = log
            offline = passed_offline_for_build(build.parent, build)
            wk_images = json.loads((offline / "images.json").read_text())
            patched = app.patched_image(build, build.parent, wk_images["app_original"])
            require(patched == wk_images["app"], "已通过离线镜像身份不匹配")
            (stage / "weknora-candidate.json").write_text(json.dumps(wk_images, indent=2))
            # Record runtime release identity without printing settings or credentials.
            identity_code = """import json,urllib.request,urllib.error
try:
    value=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health/release',timeout=10))
    print(json.dumps({k:value.get(k) for k in ('version','commit')} if value is not None else None))
except urllib.error.HTTPError as exc:
    if exc.code != 404: raise
    print('null')
"""
            identity = json.loads(r.docker("exec", "kap-backend-1", "python", "-c", identity_code))
            require(
                identity is None or identity.get("commit") == BASELINE,
                "运行版本与源码基线不一致，停止准备。",
            )
            if identity:
                require(
                    identity.get("version", "").lstrip("v") != args.version.lstrip("v"),
                    "目标版本号已在使用",
                )
            report["previous_release"] = identity
            report["legacy_baseline"] = identity is None
            runtime_env = dict(
                line.split("=", 1)
                for line in originals["kap-backend-1"]["Config"]["Env"]
                if "=" in line
            )
            origins = set()
            for key in ("KAP_PUBLIC_BASE_URL", "WECOM_REDIRECT_URI"):
                parsed = urlsplit(runtime_env.get(key, ""))
                if (
                    parsed.scheme == "https"
                    and parsed.hostname
                    and not parsed.username
                    and not parsed.password
                ):
                    origins.add("https://" + parsed.netloc)
            report["configured_https_origins"] = sorted(origins)
            manifest = json.loads(
                r.capture(
                    "python3",
                    str(source / "scripts/deploy_release.py"),
                    "--version",
                    args.version,
                    "--previous",
                    BASELINE,
                    cwd=source,
                )
            )
            (stage / "release-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False))

            print("=== 4/4 构建 KAP 六个发布镜像，保持生产服务运行 ===", flush=True)
            services = ("backend", "worker", "ocr_worker", "beat", "frontend", "migrate")
            tags = {s: "kap-candidate:" + token + "-" + s.replace("_", "-") for s in services}
            overlay = stage / "candidate-images.json"
            overlay.write_text(
                json.dumps({"services": {s: {"image": tag} for s, tag in tags.items()}})
            )
            compose = [
                "docker",
                "compose",
                "-p",
                "kap",
                "-f",
                str(source / "docker-compose.yml"),
                "-f",
                str(source / "docker-compose.prod.yml"),
                "-f",
                str(overlay),
            ]
            encoded = base64.b64encode(json.dumps(manifest, ensure_ascii=False).encode()).decode()
            require(len(encoded) <= 24000, "发布说明过长，停止构建")
            for service in services:
                print("构建：" + service, flush=True)
                r.execute(
                    [
                        *compose,
                        "build",
                        "--build-arg",
                        "KAP_RELEASE_MANIFEST_B64=" + encoded,
                        service,
                    ],
                    cwd=source,
                )
            images = {
                s: json.loads(r.docker("image", "inspect", tag))[0]["Id"] for s, tag in tags.items()
            }
            for service, image_id in images.items():
                entry = (
                    ["cat", "/usr/share/nginx/html/release-identity.json"]
                    if service == "frontend"
                    else [
                        "python",
                        "-c",
                        "import json; print(json.dumps(json.load(open('/app/release-manifest.json'))))",
                    ]
                )
                actual = json.loads(
                    r.docker(
                        "run",
                        "--rm",
                        "--network",
                        "none",
                        "--label",
                        "com.docker.compose.project=kap-release-artifact-check",
                        "--entrypoint",
                        entry[0],
                        image_id,
                        *entry[1:],
                    )
                )
                expected = (
                    {k: manifest[k] for k in ("version", "commit")}
                    if service == "frontend"
                    else manifest
                )
                require(actual == expected, "构建镜像版本身份不一致")
            head = r.docker(
                "run",
                "--rm",
                "--network",
                "none",
                "--label",
                "com.docker.compose.project=kap-release-artifact-check",
                "--entrypoint",
                "python",
                images["migrate"],
                "-m",
                "alembic",
                "heads",
            )
            require(head == "0083_model_registry (head)", "候选数据库迁移图与本轮发布不一致")
            report["migration_target"] = "0083_model_registry"
            report["image_release_identities_verified"] = True
            (stage / "candidate-image-ids.json").write_text(json.dumps(images, indent=2))
            require(
                not r.capture("git", "-C", str(source), "status", "--porcelain"),
                "候选工作区发生变化",
            )
            for name, digest in before.items():
                require(fingerprint(r.inspect(name)) == digest, "构建期间生产配置发生变化")
            report.update(
                passed=True,
                revision=args.revision,
                version=manifest["version"],
                production_unchanged=True,
                candidate_source=str(source),
                candidate_images=images,
                weknora_image=patched,
                next_step="consistent backup and production cutover",
            )
            (stage / "PREPARED").write_text(
                "Artifacts prepared; production has NOT been switched.\n"
            )
        except Exception as exc:
            log.write(traceback.format_exc().encode())
            report["error_type"] = type(exc).__name__
            if isinstance(exc, RuntimeError):
                report["error"] = str(exc)
            print("部署准备停止；生产尚未切换。不要粘贴 private 文件。", flush=True)
        finally:
            (stage / "prepare-report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2)
            )
            print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
            print("生产部署准备目录：" + str(stage), flush=True)
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
