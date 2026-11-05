"""Run pinned upstream SQL migrations on a new copy, without starting the app."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import traceback
from urllib.parse import quote
import uuid

import weknora_pg_upgrade_rehearsal as pg

APP_IMAGE = "wechatopenai/weknora-app:v0.9.0"
# All 270 SQL files at Tencent/WeKnora f17ee8a8da901bd658a4cb25f40b5fd41adbfdd7.
MIGRATION_DIGEST = "f065bba59e7c98cf84f1229f2e9647f0f4c7d87610c5d6ef7c3cad6b586b1838"
CORE_TABLES = (
    "knowledge_bases",
    "knowledges",
    "models",
    "tenants",
    "users",
    "tenant_api_keys",
    "chunks",
    "embeddings",
)


def manifest_digest(output):
    files = {}
    for line in output.splitlines():
        digest, path = line.split(maxsplit=1)
        name = Path(path.strip()).name
        pg.require(name.endswith(".sql") and name not in files, "invalid migration manifest")
        pg.require(
            len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), "invalid SQL hash"
        )
        files[name] = digest
    pg.require(files, "empty migration manifest")
    return hashlib.sha256(
        "".join(name + "\0" + files[name] + "\n" for name in sorted(files)).encode()
    ).hexdigest()


def projection(table, columns):
    # Migration 79 splits folder paths from the basename; compare its documented result.
    return ",".join(
        "regexp_replace(file_name, '^.*/', '') AS file_name"
        if table == "knowledges" and column == "file_name"
        else pg.ident(column)
        for column in columns
        # Migration 125 soft-deletes only empty-image derived chunks. Count separately below.
        if not (table == "chunks" and column in {"updated_at", "deleted_at"})
    )


def core_snapshot(container, columns):
    return {
        table: pg.sql(
            container,
            "SELECT count(*),md5(COALESCE(string_agg(h,'' ORDER BY h),'')) FROM "
            "(SELECT md5(to_jsonb(t)::text) h FROM (SELECT "
            + projection(table, fields)
            + " FROM public."
            + pg.ident(table)
            + ") t) s;",
        )
        for table, fields in columns.items()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pg-stage", required=True, type=Path)
    args = parser.parse_args()
    import fcntl

    os.umask(0o077)
    source = args.pg_stage.resolve(strict=True)
    run = source.parent
    pg.require(
        run.parent == Path("/data/weknora/upgrade-rehearsals")
        and run.name.startswith("run-")
        and run.name[4:].isalnum()
        and source.name.startswith("pg02511-"),
        "unexpected source directory",
    )
    lock = (Path.home() / ".weknora-rehearsal.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    pg.require(
        (source / "PASS").is_file() and (source / "exit-code").read_text().strip() == "0",
        "database extension rehearsal has not passed",
    )
    pg.require(shutil.disk_usage(run).free > 20 * 1024**3, "less than 20 GiB free disk")
    resources = json.loads((source / "resources.json").read_text())
    images = json.loads((source / "images.json").read_text())
    source_name, source_volume = resources["container"], resources["volume"]
    pg.require(
        source_name.startswith("wk-pg02511-") and source_volume == source_name + "-data",
        "invalid source resource names",
    )
    stage = run / ("schema090-" + uuid.uuid4().hex[:10])
    stage.mkdir()
    pg.RUN, pg.STAGE = run, stage
    pg.PRIVATE = (stage / "private.log").open("ab")
    name = "wk-schema090-" + uuid.uuid4().hex[:12]
    volume = name + "-data"
    worker = name + "-migrate"
    created = False
    code = 1
    try:
        print("演练记录：" + str(stage), flush=True)
        old = pg.guard(source_name, source_volume)
        pg.require(
            not old["State"]["Running"] and old["Image"] == images["new"], "source baseline changed"
        )
        env = dict(
            line.split("=", 1)
            for line in (run / "restore-private.env").read_text().splitlines()
            if "=" in line
        )
        pg.OWNER = env["POSTGRES_USER"]
        pg.require(
            pg.OWNER.startswith("wkrestore_") and pg.OWNER.replace("_", "").isalnum(),
            "invalid bootstrap user",
        )
        print("=== 1/4 拉取应用镜像并核对官方迁移文件 ===", flush=True)
        subprocess.run(
            ["docker", "pull", APP_IMAGE], check=True, stderr=subprocess.STDOUT, timeout=1800
        )
        app = json.loads(pg.docker("image", "inspect", APP_IMAGE))[0]
        manifest = pg.docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "sh",
            app["Id"],
            "-c",
            "sha256sum /app/migrations/versioned/*.sql",
        )
        pg.require(
            manifest_digest(manifest) == MIGRATION_DIGEST,
            "image migrations differ from pinned upstream source",
        )
        (stage / "images.json").write_text(
            json.dumps(
                {
                    "database": images["new"],
                    "app": app["Id"],
                    "digests": app.get("RepoDigests", []),
                },
                indent=2,
            )
        )
        print("=== 2/4 复制已通过的数据库副本并核对基线 ===", flush=True)
        pg.docker("volume", "create", "--label", pg.LABEL + "=" + str(run), volume)
        pg.docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "0:0",
            "--entrypoint",
            "sh",
            "--mount",
            f"type=volume,src={source_volume},dst=/from,readonly",
            "--mount",
            f"type=volume,src={volume},dst=/to",
            images["new"],
            "-c",
            "cp -a /from/. /to/",
        )
        (stage / "resources.json").write_text(
            json.dumps(
                {"container": name, "volume": volume, "source_stage": str(source), "run": str(run)},
                indent=2,
            )
        )
        pg.docker(
            "run",
            "-d",
            "--name",
            name,
            "--label",
            pg.LABEL + "=" + str(run),
            "--network",
            "none",
            "--restart",
            "no",
            "--memory",
            "4g",
            "--cpus",
            "2",
            "--shm-size",
            "512m",
            "--env-file",
            str(run / "restore-private.env"),
            "--mount",
            f"type=volume,src={volume},dst=/var/lib/postgresql/data",
            images["new"],
        )
        created = True
        pg.guard(name, volume)
        pg.wait(name)
        pg.require(
            pg.sql(name, "SELECT version,dirty FROM schema_migrations;") == "74|f",
            "schema baseline changed",
        )
        before = pg.snapshot(name, "before")
        pg.compare(json.loads((source / "after-restart.json").read_text()), before)
        columns = {
            table: pg.sql(
                name,
                "SELECT column_name FROM information_schema.columns "
                f"WHERE table_schema='public' AND table_name='{table}' ORDER BY ordinal_position;",
            ).splitlines()
            for table in CORE_TABLES
        }
        pg.require(all(columns.values()), "missing core table")
        baseline = core_snapshot(name, columns)
        deleted_before = int(
            pg.sql(name, "SELECT count(*) FROM chunks WHERE deleted_at IS NOT NULL;")
        )
        eligible = int(
            pg.sql(
                name,
                """SELECT count(*) FROM (
            SELECT *, CASE WHEN pg_input_is_valid(image_info,'jsonb') THEN image_info::jsonb ELSE 'null'::jsonb END j
            FROM chunks WHERE deleted_at IS NULL AND chunk_type IN ('image_caption','image_ocr','image_vector')
            ) s WHERE CASE WHEN jsonb_typeof(j)='array' THEN jsonb_array_length(j)=1
            AND j->0->>'sha256'='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855' ELSE false END;""",
            )
        )
        url = (
            "postgres://"
            + quote(pg.OWNER, safe="")
            + ":"
            + quote(env["POSTGRES_PASSWORD"], safe="")
        )
        url += "@127.0.0.1:5432/WeKnora?sslmode=disable"
        (stage / "migration-private.env").write_text("REHEARSAL_DB_URL=" + url + "\n")
        print("=== 3/4 仅运行官方 SQL 迁移（不启动应用服务） ===", flush=True)
        pg.guard(name, volume)
        pg.docker(
            "run",
            "--rm",
            "--name",
            worker,
            "--label",
            pg.LABEL + "=" + str(run),
            "--network",
            "container:" + name,
            "--memory",
            "1g",
            "--cpus",
            "1",
            "--env-file",
            str(stage / "migration-private.env"),
            "--entrypoint",
            "sh",
            app["Id"],
            "-c",
            'exec migrate -path /app/migrations/versioned -database "$REHEARSAL_DB_URL" up',
        )
        print("=== 4/4 核对核心数据、检索及重启结果 ===", flush=True)
        for phase in ["after", "after-restart"]:
            if phase == "after-restart":
                pg.docker("restart", "-t", "60", name)
                pg.wait(name)
            pg.require(
                pg.sql(name, "SELECT version,dirty FROM schema_migrations;") == "134|f",
                "migration did not reach clean version 134",
            )
            pg.compare(baseline, core_snapshot(name, columns))
            deleted_after = int(
                pg.sql(name, "SELECT count(*) FROM chunks WHERE deleted_at IS NOT NULL;")
            )
            pg.require(
                deleted_after == deleted_before + eligible, "unexpected chunk soft deletion count"
            )
            after = pg.snapshot(name, phase)
            pg.compare(before["retrieval"], after["retrieval"])
            print(
                f"{phase}: 8 张核心表保护字段核对通过；预期空图片分块清理 {eligible} 条；迁移 134 / dirty=false",
                flush=True,
            )
        (stage / "core-check.json").write_text(
            json.dumps(
                {
                    "tables": baseline,
                    "columns": columns,
                    "expected_empty_image_cleanup": eligible,
                    "migration": 134,
                },
                indent=2,
            )
        )
        code = 0
    except Exception:
        pg.PRIVATE.write(traceback.format_exc().encode())
        pg.PRIVATE.flush()
        print("演练停止，保留副本。请只反馈进度日志，不要粘贴 private.log。", flush=True)
    finally:
        # A timed-out docker CLI may leave its migration container alive. Stop only our labelled worker.
        try:
            listed = pg.docker("ps", "-aq", "--filter", "name=^/" + worker + "$")
            if listed:
                item = pg.inspect(worker)
                pg.require(
                    item["Config"]["Labels"].get(pg.LABEL) == str(run)
                    and item["HostConfig"]["NetworkMode"]
                    in {"container:" + name, "container:" + pg.inspect(name)["Id"]},
                    "worker identity mismatch",
                )
                pg.docker("stop", "-t", "30", worker)
                code = 1
            if created:
                pg.guard(name, volume)
                if code != 0:
                    subprocess.run(
                        ["docker", "logs", "--tail", "100", name],
                        stdout=pg.PRIVATE,
                        stderr=pg.PRIVATE,
                        timeout=15,
                    )
                pg.docker("stop", "-t", "60", name)
        except Exception:
            code = 1
            print("隔离资源收尾需检查：" + name, flush=True)
        if code == 0:
            (stage / "PASS").write_text(
                "SQL schema rehearsal passed. App startup, credential decryption and API acceptance NOT performed.\n"
            )
            print(
                "SQL 迁移演练通过；应用启动、密钥解密和 KAP 接口联调尚未验证。生产未切换。",
                flush=True,
            )
        (stage / "exit-code").write_text(str(code) + "\n")
        print(f"退出码：{code}；记录目录：{stage}", flush=True)
        pg.PRIVATE.close()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
