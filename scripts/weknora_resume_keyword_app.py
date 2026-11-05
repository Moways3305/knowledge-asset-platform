"""Resume a completed keyword build stopped by the legacy mount-order guard."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import traceback
import uuid

import weknora_app_rehearsal as app
import weknora_keyword_app_rehearsal as build
import weknora_pg_upgrade_rehearsal as pg


def validate_completed_build(stage, run):
    pg.require((stage / "exit-code").read_text().strip() == "1", "not a failed build run")
    # Do not accept timeout/source/compiler failures or manufacture a pass for
    # an image without the completed-build manifest written after docker build.
    pg.require(
        "comparison differs; do not upgrade production"
        in (stage / "private.log").read_text(errors="replace"),
        "build was not stopped by the production comparison guard",
    )
    manifest = json.loads((stage / "build-manifest.json").read_text())
    sql = Path(manifest["sql_stage"]).resolve(strict=True)
    pg.require(
        sql.parent.parent == run
        and sql.parent.name.startswith("app090-")
        and sql.name.startswith("search-plan-"),
        "SQL report outside this rehearsal",
    )
    report = json.loads((sql / "report.json").read_text())
    pg.require(
        (sql / "exit-code").read_text().strip() == "0"
        and report.get("plan_guard_verification", {}).get("passed") is True,
        "SQL guard verification missing",
    )
    pg.require(
        manifest.get("anydoc") is True
        and manifest.get("rust_toolchain") == build.RUST_TOOLCHAIN
        and manifest.get("source", {}).get("source_manifest_sha256") == build.SOURCE_MANIFEST_SHA,
        "not the verified local-ZIP anydoc build",
    )
    original = json.loads((sql.parent / "images.json").read_text())["app"]
    image = app.verify_built_image(stage, run, original)
    return image


def recheck_production(run):
    before = app.production_fingerprint()
    saved = json.loads((run / "runtime-private.json").read_text())
    baseline = {
        item["Name"].lstrip("/"): app.container_fingerprint(item)
        for item in saved
        if item["Name"].lstrip("/") in before
    }
    pg.require("WeKnora-app" in baseline, "original app baseline missing")
    pg.compare(baseline, {name: before[name] for name in baseline})
    # No historical hashes were saved by the old build script. Compare against
    # the original backup instead; record this scope explicitly, not as a
    # reconstructed before/after build comparison.
    pg.compare(before, app.production_fingerprint())
    return {
        "comparison": "original_backup_and_current_stability",
        "backup_containers_checked": sorted(baseline),
        "current_fingerprints": before,
    }


def main():
    import fcntl

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-stage", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    stage = args.build_stage.resolve(strict=True)
    run = stage.parent
    pg.require(
        run.parent == Path("/data/weknora/upgrade-rehearsals")
        and run.name.startswith("run-")
        and run.name[4:].isalnum()
        and stage.name.startswith("keyword-build-")
        and stage.name.removeprefix("keyword-build-").isalnum(),
        "unexpected build directory",
    )
    lock = (Path.home() / ".weknora-rehearsal.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    recovery = stage / ("resume-" + uuid.uuid4().hex[:10])
    recovery.mkdir()
    pg.PRIVATE = (recovery / "private.log").open("ab")
    code = 1
    try:
        print("续验记录：" + str(recovery), flush=True)
        image = validate_completed_build(stage, run)
        report = recheck_production(run)
        report["image_id"] = image
        (recovery / "guard-report.json").write_text(json.dumps(report, indent=2))
        (stage / "PASS-BUILD").write_text(
            "Completed build verified after canonical mount comparison; not API acceptance.\n"
        )
        print("镜像身份与生产配置复核通过；复用已构建镜像，不重新编译。", flush=True)
        lock.close()
        code = subprocess.run(
            [
                "python3",
                str(Path(__file__).with_name("weknora_app_rehearsal.py")),
                "--rehearsal-dir",
                str(run),
                "--patched-build-stage",
                str(stage),
            ],
            check=False,
        ).returncode
    except Exception:
        pg.PRIVATE.write(traceback.format_exc().encode())
        print("续验已停止；请勿粘贴 private 文件。生产未切换。", flush=True)
    finally:
        lock.close()
        pg.PRIVATE.close()
        (recovery / "exit-code").write_text(str(code) + "\n")
        print(f"续验退出码：{code}；记录目录：{recovery}", flush=True)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
