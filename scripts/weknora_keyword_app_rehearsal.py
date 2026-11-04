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
import zipfile

import weknora_pg_upgrade_rehearsal as pg
from weknora_app_rehearsal import production_fingerprint

UPSTREAM = "f17ee8a8da901bd658a4cb25f40b5fd41adbfdd7"
PATCH_SHA = "6323a4d74fd42ad921668121e3e21a227875fd436529fc7036c777f6be55f100"
# SHA256 of sorted path/NUL/git-mode/NUL/git-blob-SHA/newline records from
# git ls-tree -rz UPSTREAM. Verify every file, not just the editable ZIP comment.
SOURCE_MANIFEST_SHA = "8a4b09b6bf0d6456420f83d63bae524c4d69deecae13f59baf11491e4d652ec1"
RUST_TOOLCHAIN = "1.99.1"


def rust_build_steps():
    # Configure only the disposable builder. Retain Cargo.lock checksum checks
    # and the upstream anydoc source/patch/build script.
    return (
        "ENV RUSTUP_DIST_SERVER=https://rsproxy.cn RUSTUP_UPDATE_ROOT=https://rsproxy.cn/rustup\n"
        "ENV CARGO_HTTP_TIMEOUT=60 CARGO_NET_RETRY=2\n"
        'RUN if [ "$WITH_ANYDOC" = "1" ]; then \\\n'
        "    curl --proto '=https' --tlsv1.2 -fsSL --connect-timeout 15 --max-time 120 "
        "--retry 2 https://rsproxy.cn/rustup-init.sh -o /tmp/kap-rustup-init.sh && \\\n"
        "    timeout --signal=TERM --kill-after=15s 1200s "
        "sh /tmp/kap-rustup-init.sh -y --profile minimal --default-toolchain "
        + RUST_TOOLCHAIN
        + " && \\\n"
        "    rustc --version && cargo --version && \\\n"
        "    printf '%s\\n' '[source.crates-io]' \"replace-with = 'rsproxy-sparse'\" "
        "'[source.rsproxy-sparse]' \"registry = 'sparse+https://rsproxy.cn/index/'\" "
        '> "$CARGO_HOME/config.toml"; fi\n'
        "RUN --mount=type=cache,target=/usr/local/cargo/registry \\\n"
        "    --mount=type=cache,target=/usr/local/cargo/git \\\n"
        '    if [ "$WITH_ANYDOC" = "1" ]; then \\\n'
        "        timeout --signal=TERM --kill-after=15s 1800s ./scripts/build-anydoc-lib.sh; \\\n"
        "    fi\n"
    )


def extract_source_zip(archive, destination):
    pg.require(not any(destination.iterdir()), "source destination must be empty")
    prefix = "WeKnora-" + UPSTREAM + "/"
    rows, files, seen = [], [], set()
    with zipfile.ZipFile(archive) as bundle:
        pg.require(bundle.comment.decode("ascii") == UPSTREAM, "ZIP commit mismatch")
        entries = bundle.infolist()
        pg.require(len(entries) < 20000, "too many source entries")
        pg.require(sum(i.file_size for i in entries) < 2 * 1024**3, "source ZIP too large")
        for item in entries:
            pg.require(item.filename.startswith(prefix), "ZIP root mismatch")
            name = item.filename[len(prefix) :]
            if not name:
                pg.require(item.is_dir(), "invalid ZIP root")
                continue
            parts = name.rstrip("/").split("/")
            pg.require(
                all(p not in ("", ".", "..", ".git") for p in parts)
                and "\\" not in name
                and ":" not in name,
                "unsafe ZIP path",
            )
            mode = item.external_attr >> 16
            pg.require(mode & 0o170000 in (0, 0o040000, 0o100000), "ZIP links not allowed")
            if item.is_dir():
                continue
            pg.require(name not in seen, "duplicate ZIP file")
            seen.add(name)
            digest = hashlib.sha1(b"blob " + str(item.file_size).encode() + b"\0")
            with bundle.open(item) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            git_mode = b"100755" if mode & 0o111 else b"100644"
            rows.append(
                name.encode() + b"\0" + git_mode + b"\0" + digest.hexdigest().encode() + b"\n"
            )
            files.append((item, name, git_mode))
        manifest = hashlib.sha256(b"".join(sorted(rows))).hexdigest()
        pg.require(manifest == SOURCE_MANIFEST_SHA, "ZIP contents differ from pinned source")
        # No filesystem writes until all paths, contents and modes are verified.
        for item, name, mode in files:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(item) as stream, target.open("xb") as output:
                shutil.copyfileobj(stream, output)
            target.chmod(0o755 if mode == b"100755" else 0o644)
    return {"method": "local_zip", "source_manifest_sha256": manifest, "files": len(files)}


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
    old_rust = (
        "RUN --mount=type=cache,target=/usr/local/cargo/registry \\\n"
        "    --mount=type=cache,target=/usr/local/cargo/git \\\n"
        '    if [ "$WITH_ANYDOC" = "1" ]; then \\\n'
        "        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \\\n"
        "            | sh -s -- -y --profile minimal --default-toolchain stable && \\\n"
        "        ./scripts/build-anydoc-lib.sh; \\\n"
        "    fi\n"
    )
    pg.require(builder.count(old_rust) == 1, "upstream Rust build step changed")
    builder = builder.replace(old_rust, rust_build_steps())
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
    parser.add_argument(
        "--source-zip", type=Path, help="Official ZIP of the pinned upstream commit"
    )
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
        (stage / "production-before.json").write_text(json.dumps(before, indent=2))
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
            if args.source_zip:
                print("校验本地 ZIP 的提交及全部源码文件，跳过 GitHub 源码拉取。", flush=True)
                source_record = extract_source_zip(args.source_zip.resolve(strict=True), source)
                execute(["git", "init", "-q"], source, log)
            else:
                source_record = {"method": "git", "commit": UPSTREAM}
                execute(["git", "init", "-q"], source, log)
                execute(
                    ["git", "remote", "add", "origin", "https://github.com/Tencent/WeKnora.git"],
                    source,
                    log,
                )
                print("正在拉取固定上游提交（最多 600 秒）。", flush=True)
                execute(
                    [
                        "git",
                        "-c",
                        "credential.helper=",
                        "fetch",
                        "--progress",
                        "--depth=1",
                        "origin",
                        UPSTREAM,
                    ],
                    source,
                    log,
                )
                execute(["git", "checkout", "--detach", "FETCH_HEAD"], source, log)
                revision = subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=source, text=True
                ).strip()
                pg.require(revision == UPSTREAM, "source revision mismatch")
            (stage / "source-manifest.json").write_text(json.dumps(source_record, indent=2))
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
            "source": source_record,
            "rust_toolchain": RUST_TOOLCHAIN,
            "rust_mirror": "https://rsproxy.cn",
        }
        (stage / "build-manifest.json").write_text(json.dumps(manifest, indent=2))
        phase = "production_guard"
        after = production_fingerprint()
        (stage / "production-after.json").write_text(json.dumps(after, indent=2))
        pg.compare(before, after)
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
        if phase == "production_guard":
            print("镜像已构建，但生产一致性检查未通过；不要重建或手工写通过标记。", flush=True)
        else:
            print("源码/编译错误可检查 build.log；不要粘贴 private 文件。", flush=True)
    finally:
        lock.close()
        (stage / "exit-code").write_text(str(code) + "\n")
        pg.PRIVATE.close()
        print(f"任务退出码：{code}；构建记录：{stage}", flush=True)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
