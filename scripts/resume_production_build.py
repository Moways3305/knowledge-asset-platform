"""Resume only candidate builds in a validated preparation; never migrate or switch production."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import traceback

from prepare_production_release import (
    BASELINE,
    KAP_NAMES,
    WK_NAMES,
    Runner,
    build_candidates,
    fingerprint,
    require,
)

MIRROR = "https://mirrors.cloud.tencent.com/debian"
SECURITY = "https://mirrors.cloud.tencent.com/debian-security"
ROOT = Path("/data/weknora/upgrade-rehearsals/run-eDkLxh7B")


def read(path):
    return json.loads(path.read_text())


def local_file(stage, value):
    path = Path(value).resolve(strict=True)
    require(path.is_relative_to(stage) and path.is_file(), "准备记录引用了目录外文件")
    return path


def digest(path):
    with path.open("rb") as stream:
        result = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
        return result.digest()


def validate_records(runner, stage, revision):
    require(not (stage / "PREPARED").exists(), "该轮已准备完成，无需续建")
    report = read(stage / "prepare-report.json")
    require(
        report.get("production_switched") is False and report.get("passed") is False,
        "不是未切换的失败准备记录",
    )
    require(
        report.get("database_archives_readable") is True
        and report.get("running_service_rollback_images_preserved") is True,
        "备份或运行服务回滚镜像尚未完成",
    )
    source = (stage / "source").resolve(strict=True)
    require(source.parent == stage, "候选源码目录不匹配")
    require(
        runner.capture("git", "-C", str(source), "rev-parse", "HEAD") == revision, "候选提交已变化"
    )
    require(
        not runner.capture("git", "-C", str(source), "status", "--porcelain"),
        "候选源码有未提交修改",
    )
    require(
        runner.capture("git", "-C", "/data/kap/repo", "rev-parse", "HEAD") == BASELINE,
        "生产源码基线已变化",
    )
    require(
        not runner.capture("git", "-C", "/data/kap/repo", "status", "--porcelain"),
        "生产源码有未提交修改",
    )
    manifest = read(stage / "release-manifest.json")
    require(manifest.get("commit") == revision, "版本清单与候选提交不一致")
    originals = read(stage / "runtime-private.json")
    require(set(originals) == KAP_NAMES | WK_NAMES, "生产容器清单不完整")
    rollback = read(stage / "rollback-images.json")
    require(set(rollback) == set(originals), "回滚镜像清单不完整")
    for name, old in originals.items():
        current = runner.inspect(name)
        require(fingerprint(current) == fingerprint(old), "生产容器身份或配置已变化")
        entry = rollback[name]
        require(entry["image_id"] == old["Image"], "回滚镜像记录身份不匹配")
        if name == "kap-migrate-1":
            require(
                current["State"].get("Status") == "exited"
                and current["State"].get("Running") is False
                and current["State"].get("ExitCode") == 0,
                "历史迁移容器状态已变化",
            )
            if entry.get("status") == "completed_job_image_missing":
                require(
                    entry.get("tag") is None and entry.get("recreate_on_rollback") is False,
                    "历史迁移例外记录不正确",
                )
                continue
        else:
            require(current["State"].get("Running") is True, "存在未运行的生产服务")
        expected_tag = "kap-rollback:" + stage.name + "-" + name.lower().replace("_", "-")
        require(entry.get("tag") == expected_tag, "回滚标签记录不匹配")
        require(runner.image_identity(expected_tag) == old["Image"], "运行服务回滚镜像不可用")
    configs = read(stage / "config-backups-private.json")
    require(
        all(str(Path("/data/kap/repo") / rel) in configs for rel in (".env", "backend/.env")),
        "缺少生产环境配置备份",
    )
    for original, backup in configs.items():
        require(digest(Path(original)) == digest(local_file(stage, backup)), "生产配置文件已变化")
    for relative in (".env", "backend/.env"):
        require(
            digest(source / relative) == digest(Path("/data/kap/repo") / relative),
            "候选环境配置与生产不一致",
        )
    databases = read(stage / "database-backups-private.json")
    require(set(databases) == {"kap-postgres-1", "WeKnora-postgres"}, "数据库备份清单不完整")
    for name, entries in databases.items():
        require(bool(entries), "数据库备份清单为空")
        for entry in entries:
            archive = local_file(stage, entry["archive"])
            require(archive.stat().st_size == entry["bytes"] > 0, "在线备份文件缺失或大小变化")
        require((stage / (name + "-globals-private.sql")).stat().st_size > 0, "数据库角色备份缺失")
    overlay = read(stage / "candidate-images.json")
    services = ("backend", "worker", "ocr_worker", "beat", "frontend", "migrate")
    expected = {
        "services": {
            s: {"image": "kap-candidate:" + stage.name + "-" + s.replace("_", "-")}
            for s in services
        }
    }
    require(overlay == expected, "候选标签记录被修改，拒绝覆盖其他镜像")
    return source, manifest, report


def progress_phase(path):
    try:
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 65536))
            text = stream.read().decode(errors="replace").lower()
        matches = [
            (text.rfind(needle), label)
            for needle, label in (
                ("apt-get", "安装系统组件"),
                ("get:", "下载系统组件"),
                ("unpacking ", "解包系统组件"),
                ("setting up ", "配置系统组件"),
                ("pip install", "安装 Python 依赖"),
                ("collecting ", "下载 Python 依赖"),
                ("exporting layers", "导出镜像"),
                ("npm ", "构建前端"),
            )
        ]
        offset, label = max(matches)
        return label if offset >= 0 else "镜像构建中"
    except OSError:
        return "镜像构建中"


class ResumeRunner(Runner):
    def execute(self, args, *, cwd=None, timeout=1800):
        started = time.monotonic()
        process = subprocess.Popen(
            args, cwd=cwd, stdout=self.log, stderr=self.log, start_new_session=True
        )
        try:
            while True:
                try:
                    code = process.wait(
                        timeout=min(30, max(0.1, timeout - (time.monotonic() - started)))
                    )
                    require(code == 0, "候选构建失败，详见 private 日志；生产未切换")
                    return
                except subprocess.TimeoutExpired:
                    elapsed = int(time.monotonic() - started)
                    require(elapsed < timeout, "候选构建达到本轮时间上限；生产未切换")
                    print(
                        f"{progress_phase(Path(self.log.name))}，已用时 {elapsed} 秒。", flush=True
                    )
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()


def main():
    import fcntl

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    stage = args.stage.resolve(strict=True)
    require(
        stage.parent == ROOT / "production-preparations"
        and re.fullmatch(r"\d{8}-\d{6}-[a-f0-9]{6}", stage.name),
        "准备目录不匹配",
    )
    require(re.fullmatch(r"[a-f0-9]{40}", args.revision), "必须指定完整候选提交")
    report = {"phase": "production_build_resume", "production_switched": False, "passed": False}
    with (
        (stage.parent / "prepare.lock").open("a") as lock,
        (stage / "resume-private.log").open("ab") as log,
    ):
        locked = False
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
            runner = ResumeRunner(log)
            print("=== 1/3 核对原准备记录、备份、源码及运行服务 ===", flush=True)
            source, manifest, previous = validate_records(runner, stage, args.revision)
            # Reuse the same immutable WeKnora candidate and its passed offline evidence.
            sys.path.insert(0, str(source / "scripts"))
            import weknora_pg_upgrade_rehearsal as pg
            import weknora_app_rehearsal as app
            from weknora_keyword_app_rehearsal import passed_offline_for_build

            pg.PRIVATE = log
            build = ROOT / "keyword-build-5320ceda3e"
            offline = passed_offline_for_build(ROOT, build)
            wk = read(offline / "images.json")
            require(wk == read(stage / "weknora-candidate.json"), "底座候选记录已变化")
            patched = app.patched_image(build, ROOT, wk["app_original"])
            require(patched == wk["app"], "底座镜像与已通过离线记录不一致")
            report.update(
                {
                    k: v
                    for k, v in previous.items()
                    if k not in {"phase", "passed", "error", "error_type"}
                }
            )
            report["build_mirrors"] = {"debian": MIRROR, "security": SECURITY}
            (stage / "build-settings.json").write_text(json.dumps(report["build_mirrors"]))
            print("=== 2/3 仅切换构建用软件源，续建六个候选镜像 ===", flush=True)
            images = build_candidates(
                runner,
                stage,
                source,
                manifest,
                report,
                debian_mirror=MIRROR,
                security_mirror=SECURITY,
                timeout=1800,
            )
            print("=== 3/3 核对镜像身份及生产未变 ===", flush=True)
            validate_records(runner, stage, args.revision)
            report.update(
                passed=True,
                revision=args.revision,
                version=manifest["version"],
                production_unchanged=True,
                candidate_source=str(source),
                candidate_images=images,
                weknora_image=patched,
                consistent_files_backup_pending_cutover=True,
                next_step="consistent backup and production cutover",
            )
            archive = stage / "prepare-report-before-resume.json"
            if not archive.exists():
                archive.write_text(json.dumps(previous, ensure_ascii=False, indent=2))
            (stage / "prepare-report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2)
            )
            (stage / "PREPARED").write_text(
                "Artifacts prepared; production has NOT been switched.\n"
            )
        except Exception as exc:
            log.write(traceback.format_exc().encode())
            report.update(error_type=type(exc).__name__, passed=False)
            report["error"] = (
                str(exc) if isinstance(exc, RuntimeError) else "续建未完成，详见受限日志"
            )
            print("续建停止；生产未切换。不要回传 private 文件。", flush=True)
        finally:
            if locked:
                (stage / "resume-report.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2)
                )
            print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
            print("生产部署准备目录：" + str(stage), flush=True)
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
