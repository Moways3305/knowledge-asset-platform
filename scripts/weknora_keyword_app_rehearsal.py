"""Build a pinned keyword fix, then validate it against a fresh offline app copy."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import traceback
import uuid

import weknora_pg_upgrade_rehearsal as pg
from weknora_app_rehearsal import production_fingerprint

UPSTREAM = "f17ee8a8da901bd658a4cb25f40b5fd41adbfdd7"
PATCH_SHA = "6323a4d74fd42ad921668121e3e21a227875fd436529fc7036c777f6be55f100"


def dockerfile(upstream):
    # Reuse upstream's complete Go/anydoc builder, but keep the already tested
    # runtime (browser tools, dictionaries, migrations, parsers and extensions).
    pg.require(
        upstream.count("# Build stage\n") == 1 and upstream.count("# Final stage\n") == 1,
        "upstream Dockerfile layout changed",
    )
    builder = upstream.split("# Build stage\n", 1)[1].split("# Final stage\n", 1)[0]
    pg.require("FROM golang:1.26-bookworm AS builder" in builder, "unexpected Go builder")
    builder = builder.replace(
        "FROM golang:1.26-bookworm AS builder",
        "FROM ${KAP_BUILDER_IMAGE} AS builder\nENV GOMAXPROCS=2 GOFLAGS=-p=2 CARGO_BUILD_JOBS=2",
    )
    # These outputs already exist in the original runtime. Avoid fetching an
    # unrelated migrate@latest or re-downloading existing DuckDB extensions.
    for line in (
        "RUN go install -tags 'postgres' github.com/golang-migrate/migrate/v4/cmd/migrate@latest\n",
        "COPY cmd/download cmd/download\n",
        "RUN go run cmd/download/duckdb/duckdb.go\n",
        "RUN --mount=type=cache,target=/go/pkg/mod bash ./scripts/copy-licenses.sh /license-bundle\n",
        "RUN --mount=type=cache,target=/go/pkg/mod cp -r /go/pkg/mod/github.com/yanyiwu/ /app/yanyiwu/\n",
    ):
        pg.require(line in builder, "expected builder line missing")
        builder = builder.replace(line, "")
    tests = (
        "RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build "
        "gofmt -w internal/application/repository/retriever/postgres/keyword_plan.go "
        "internal/application/repository/retriever/postgres/keyword_plan_integration_test.go "
        "internal/application/repository/retriever/postgres/keyword_plan_test.go "
        "internal/application/repository/retriever/postgres/keyword_score_test.go "
        "internal/application/repository/retriever/postgres/repository.go && "
        "go test ./internal/application/repository/retriever/postgres/ -count=1\n"
    )
    builder = builder.replace(
        "# Link the anydoc parser engine", tests + "\n# Link the anydoc parser engine", 1
    )
    return (
        "# syntax=docker/dockerfile:1\nARG KAP_RUNTIME_IMAGE\nARG KAP_BUILDER_IMAGE\n"
        + builder
        + "\nFROM ${KAP_RUNTIME_IMAGE}\n"
        "COPY --from=builder /app/WeKnora /app/WeKnora\n"
    )


def execute(args, cwd, log, timeout=600):
    # All command arguments are structured. Build/source logs never receive
    # production .env files, keys, DB data or mounted Docker sockets.
    started = time.monotonic()
    next_notice = started + 60
    proc = subprocess.Popen(args, cwd=cwd, stdout=log, stderr=log, start_new_session=True)
    try:
        while proc.poll() is None:
            now = time.monotonic()
            if now - started > timeout:
                raise TimeoutError("bounded build/source step timed out")
            if now >= next_notice:
                print(f"当前步骤仍在运行，已用时 {int(now - started)} 秒。", flush=True)
                next_notice = now + 60
            time.sleep(2)
        pg.require(proc.returncode == 0, "build/source command failed; inspect build.log")
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sql-stage", required=True, type=Path)
    args = parser.parse_args()
    import fcntl

    os.umask(0o077)
    sql_stage = args.sql_stage.resolve(strict=True)
    app_stage, run = sql_stage.parent, sql_stage.parent.parent
    pg.require(
        run.parent == Path("/data/weknora/upgrade-rehearsals")
        and run.name.startswith("run-")
        and run.name[4:].isalnum()
        and app_stage.name.startswith("app090-")
        and sql_stage.name.startswith("search-plan-"),
        "unexpected SQL stage",
    )
    report = json.loads((sql_stage / "report.json").read_text())
    pg.require(
        (sql_stage / "exit-code").read_text().strip() == "0"
        and report.get("plan_guard_verification", {}).get("passed") is True,
        "guarded SQL verification has not passed",
    )
    repo = Path(__file__).resolve().parents[1]
    patch = repo / "patches/weknora-v0.9.0-keyword.patch"
    pg.require(hashlib.sha256(patch.read_bytes()).hexdigest() == PATCH_SHA, "patch digest mismatch")
    pg.require(shutil.disk_usage(run).free > 30 * 1024**3, "less than 30 GiB free disk")
    lock = (Path.home() / ".weknora-rehearsal.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    stage = run / ("keyword-build-" + uuid.uuid4().hex[:10])
    stage.mkdir()
    pg.RUN, pg.STAGE = run, stage
    pg.PRIVATE = (stage / "private.log").open("ab")
    code = 1
    phase = "baseline"
    try:
        print("构建记录：" + str(stage), flush=True)
        before = production_fingerprint()
        resources = json.loads((app_stage / "resources.json").read_text())
        for key in ("container", "app", "redis"):
            item = pg.inspect(resources[key])
            pg.require(
                item["Config"]["Labels"].get(pg.LABEL) == str(run) and not item["State"]["Running"],
                "diagnostic containers must remain stopped",
            )
        images = json.loads((app_stage / "images.json").read_text())
        original_image = images["app"]
        image = json.loads(pg.docker("image", "inspect", original_image))[0]
        pg.require(
            image["Id"] == original_image and image["Architecture"] == "amd64",
            "unexpected runtime image",
        )
        tag_id = stage.name.removeprefix("keyword-build-")
        base_tag = "kap-weknora-keyword-base:" + tag_id
        output_tag = "kap-weknora-keyword-rehearsal:" + tag_id
        pg.docker("tag", original_image, base_tag)
        source = stage / "source"
        source.mkdir()
        with (stage / "build.log").open("ab", buffering=0) as log:
            phase = "source"
            print("=== 1/3 获取固定上游源码并应用检索补丁 ===", flush=True)
            execute(["git", "init", "-q"], source, log)
            execute(
                ["git", "remote", "add", "origin", "https://github.com/Tencent/WeKnora.git"],
                source,
                log,
            )
            execute(
                ["git", "-c", "credential.helper=", "fetch", "--depth=1", "origin", UPSTREAM],
                source,
                log,
            )
            execute(["git", "checkout", "--detach", "FETCH_HEAD"], source, log)
            revision = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=source, text=True
            ).strip()
            pg.require(revision == UPSTREAM, "source revision mismatch")
            execute(["git", "apply", "--check", str(patch)], source, log)
            execute(["git", "apply", str(patch)], source, log)
            (source / "Dockerfile.kap-keyword").write_text(
                dockerfile((source / "docker/Dockerfile.app").read_text()), encoding="utf-8"
            )
            phase = "build"
            print("=== 2/3 运行 Go 回归并构建应用（保留 anydoc；复用原运行镜像）===", flush=True)
            execute(["docker", "pull", "golang:1.26-bookworm"], source, log, 600)
            builder = json.loads(pg.docker("image", "inspect", "golang:1.26-bookworm"))[0]
            builder_digest = builder["RepoDigests"][0]
            command = [
                "docker",
                "build",
                "--progress=plain",
                "-f",
                "Dockerfile.kap-keyword",
                "-t",
                output_tag,
                "--build-arg",
                "KAP_RUNTIME_IMAGE=" + base_tag,
                "--build-arg",
                "KAP_BUILDER_IMAGE=" + builder_digest,
                "--build-arg",
                "GOPROXY_ARG=https://goproxy.cn|https://proxy.golang.org|direct",
                "--build-arg",
                "GOSUMDB_ARG=sum.golang.org",
                "--build-arg",
                "APK_MIRROR_ARG=mirrors.tencent.com",
                "--build-arg",
                "WITH_ANYDOC=1",
                "--build-arg",
                "VERSION_ARG=v0.9.0-kap.keyword.1",
                "--build-arg",
                "COMMIT_ID_ARG=" + UPSTREAM + "+" + PATCH_SHA[:12],
                "--label",
                pg.LABEL + "=" + str(run),
                "--label",
                "kap.weknora.keyword.patch=" + PATCH_SHA,
                "--label",
                "kap.weknora.keyword.base=" + original_image,
                ".",
            ]
            execute(command, source, log, 5400)
        built = json.loads(pg.docker("image", "inspect", output_tag))[0]
        manifest = {
            "upstream": UPSTREAM,
            "patch_sha256": PATCH_SHA,
            "image_id": built["Id"],
            "image_tag": output_tag,
            "base_image": original_image,
            "builder_image": builder["Id"],
            "builder_digest": builder_digest,
            "sql_stage": str(sql_stage),
            "anydoc": True,
        }
        (stage / "build-manifest.json").write_text(json.dumps(manifest, indent=2))
        pg.compare(before, production_fingerprint())
        (stage / "PASS-BUILD").write_text(
            "Go package tests and anydoc application build passed; not API acceptance.\n"
        )
        phase = "app_rehearsal"
        print("=== 3/3 使用新数据库副本进行应用与 KAP 接口复验 ===", flush=True)
        lock.close()  # The app script takes the same lock itself.
        child = subprocess.run(
            [
                "python3",
                str(repo / "scripts/weknora_app_rehearsal.py"),
                "--rehearsal-dir",
                str(run),
                "--patched-build-stage",
                str(stage),
            ],
            check=False,
        )
        code = child.returncode
    except Exception:
        pg.PRIVATE.write(traceback.format_exc().encode())
        print("已停止，阶段：" + phase + "。生产未切换。", flush=True)
        print("源码/编译错误可检查 build.log；不要粘贴 private 文件。", flush=True)
    finally:
        lock.close()
        (stage / "exit-code").write_text(str(code) + "\n")
        pg.PRIVATE.close()
        print(f"任务退出码：{code}；构建记录：{stage}", flush=True)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
