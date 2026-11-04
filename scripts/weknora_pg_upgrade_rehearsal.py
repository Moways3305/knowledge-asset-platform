"""Upgrade only a copy of the explicitly verified, isolated rehearsal volume."""

import json
import os
from pathlib import Path
import subprocess
import time
import traceback
import uuid

RUN = Path()
OLD = OLD_VOLUME = NEW = VOLUME = OWNER = ""
STAGE = Path()
TARGET = "paradedb/paradedb:v0.25.11-pg17"
LABEL = "kap.weknora.rehearsal"
PRIVATE = None


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def docker(*args, data=None):
    result = subprocess.run(
        ["docker", *args], input=data, stdout=subprocess.PIPE, stderr=PRIVATE, timeout=1800
    )
    if result.returncode:
        PRIVATE.write(result.stdout)
        PRIVATE.flush()
        raise RuntimeError("Docker command failed; inspect the private log safely")
    return result.stdout.decode().strip()


def inspect(name):
    return json.loads(docker("inspect", name))[0]


def guard(name, volume):
    item = inspect(name)
    require(item["Config"]["Labels"].get(LABEL) == str(RUN), "label mismatch")
    require(item["HostConfig"]["NetworkMode"] == "none", "network is not isolated")
    require(not item["HostConfig"].get("PortBindings"), "unexpected published ports")
    mount = [m for m in item["Mounts"] if m["Destination"] == "/var/lib/postgresql/data"]
    require(len(mount) == 1 and mount[0].get("Name") == volume, "data volume mismatch")
    return item


def ident(value):
    return '"' + value.replace('"', '""') + '"'


def sql(name, query, db="WeKnora"):
    return docker(
        "exec",
        "-i",
        "-e",
        "PGOPTIONS=-c statement_timeout=900000 -c lock_timeout=30000",
        name,
        "psql",
        "-XqAt",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        OWNER,
        "-d",
        db,
        data=query.encode(),
    )


def wait(name, db="wk_restore_control"):
    for _ in range(180):
        result = subprocess.run(
            [
                "docker",
                "exec",
                name,
                "pg_isready",
                "-h",
                "127.0.0.1",
                "-U",
                OWNER,
                "-d",
                db,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        if result.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError("isolated database startup timeout")


def snapshot(name, label):
    tables = sql(
        name,
        """SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname='public' AND c.relkind IN ('r','p') AND NOT EXISTS
      (SELECT 1 FROM pg_depend d WHERE d.classid='pg_class'::regclass AND d.objid=c.oid AND d.deptype='e')
      ORDER BY 1""",
    ).splitlines()
    result = {"tables": {}, "retrieval": {}}
    for table in tables:
        result["tables"][table] = sql(
            name,
            "SELECT count(*),md5(COALESCE(string_agg(h,'' ORDER BY h),'')) "
            "FROM (SELECT md5(to_jsonb(t)::text) h FROM public." + ident(table) + " t) s;",
        )
    result["migration"] = sql(name, "SELECT version,dirty FROM schema_migrations;")
    result["sequences"] = sql(
        name,
        "SELECT sequencename,last_value FROM pg_sequences WHERE schemaname='public' ORDER BY 1;",
    )
    for term in ["项目", "知识", "验收"]:
        result["retrieval"]["keyword:" + term] = sql(
            name,
            "SELECT id,round(paradedb.score(id)::numeric,6) FROM embeddings WHERE content ||| '"
            + term
            + "' AND (is_enabled IS NULL OR is_enabled=true) ORDER BY paradedb.score(id) DESC,id LIMIT 20;",
        )
    dims = sql(
        name, "SELECT DISTINCT dimension FROM embeddings WHERE embedding IS NOT NULL ORDER BY 1;"
    ).splitlines()
    require(dims, "no vectors available for retrieval verification")
    for raw in dims:
        dim = int(raw)
        require(0 < dim <= 16000, "unexpected vector dimension")
        vector = sql(
            name,
            f"SELECT embedding::halfvec({dim})::text FROM embeddings WHERE dimension={dim} "
            "AND embedding IS NOT NULL AND (is_enabled IS NULL OR is_enabled=true) ORDER BY id LIMIT 1;",
        )
        if not vector:
            continue
        quoted = "'" + vector.replace("'", "''") + "'"
        query = (
            f"SELECT id,round((embedding::halfvec({dim}) <=> {quoted}::halfvec({dim}))::numeric,6) AS distance "
            f"FROM embeddings WHERE dimension={dim} AND embedding IS NOT NULL AND (is_enabled IS NULL OR is_enabled=true) "
            f"ORDER BY embedding::halfvec({dim}) <=> {quoted}::halfvec({dim}) LIMIT 20"
        )
        # Store IDs/distances, never vectors or document text, in the comparison file.
        result["retrieval"]["vector:" + raw] = sql(
            name,
            "BEGIN; SET LOCAL enable_seqscan=off; SET LOCAL hnsw.ef_search=100; "
            + "SELECT id,distance FROM ("
            + query.replace("LIMIT 20", "LIMIT 100")
            + ") candidates ORDER BY distance,id LIMIT 20; COMMIT;",
        )
    require(
        any(
            (result["retrieval"][key] for key in result["retrieval"] if key.startswith("keyword:"))
        ),
        "all keyword probes empty",
    )
    require(
        any((result["retrieval"][key] for key in result["retrieval"] if key.startswith("vector:"))),
        "all vector probes empty",
    )
    (STAGE / (label + ".json")).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        f"{label}: {len(tables)} 张业务表指纹、{len(result['retrieval'])} 组检索结果已记录",
        flush=True,
    )
    return result


def compare(before, after):
    differences = [key for key in before.keys() | after.keys() if before.get(key) != after.get(key)]
    if differences:
        print("发现差异类别：" + ", ".join(differences), flush=True)
        raise RuntimeError("comparison differs; do not upgrade production")


def main():
    import argparse
    import shutil

    global RUN, OLD, OLD_VOLUME, NEW, VOLUME, OWNER, STAGE, PRIVATE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rehearsal-dir", required=True, type=Path)
    args = parser.parse_args()
    import fcntl

    os.umask(0o077)
    RUN = args.rehearsal_dir.resolve(strict=True)
    require(RUN.parent == Path("/data/weknora/upgrade-rehearsals"), "unexpected rehearsal parent")
    require(
        RUN.name.startswith("run-") and RUN.name[4:].isalnum(), "invalid rehearsal directory name"
    )
    lock = (Path.home() / ".weknora-rehearsal.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    require(shutil.disk_usage(RUN).free > 20 * 1024**3, "less than 20 GiB free disk")
    OLD = "wk-rehearsal-" + RUN.name[4:]
    OLD_VOLUME = OLD + "-data"
    STAGE = RUN / ("pg02511-" + uuid.uuid4().hex[:10])
    STAGE.mkdir()
    NEW = "wk-pg02511-" + uuid.uuid4().hex[:12]
    VOLUME = NEW + "-data"
    PRIVATE = (STAGE / "private.log").open("ab")
    created = False
    old_started = False
    code = 1
    try:
        print("演练记录：" + str(STAGE), flush=True)
        require((RUN / "exit-code").read_text().strip() == "0", "old restore did not pass")
        old = guard(OLD, OLD_VOLUME)
        old_image = (RUN / "old-database-image.txt").read_text().strip()
        require(
            old["Image"] == old_image and (not old["State"]["Running"]),
            "old rehearsal baseline changed",
        )
        OWNER = next(
            line.split("=", 1)[1]
            for line in (RUN / "restore-private.env").read_text().splitlines()
            if line.startswith("POSTGRES_USER=")
        )
        require(
            OWNER.startswith("wkrestore_") and OWNER.replace("_", "").isalnum(),
            "rehearsal verification failed",
        )
        print("=== 1/5 拉取固定版本镜像 ===", flush=True)
        subprocess.run(
            ["docker", "pull", TARGET], check=True, stderr=subprocess.STDOUT, timeout=1800
        )
        target_info = json.loads(docker("image", "inspect", TARGET))[0]
        target_image = target_info["Id"]
        (STAGE / "images.json").write_text(
            json.dumps(
                {
                    "old": old_image,
                    "new": target_image,
                    "digests": target_info.get("RepoDigests", []),
                },
                indent=2,
            )
        )
        print("=== 2/5 记录旧副本基线并复制独立数据卷 ===", flush=True)
        old_started = True
        docker("start", OLD)
        wait(OLD)
        require(
            sql(OLD, "SELECT version,dirty FROM schema_migrations;") == "74|f",
            "rehearsal verification failed",
        )
        before = snapshot(OLD, "before")
        docker("stop", "-t", "60", OLD)
        require(not guard(OLD, OLD_VOLUME)["State"]["Running"], "rehearsal verification failed")
        docker("volume", "create", "--label", LABEL + "=" + str(RUN), VOLUME)
        docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "0:0",
            "--entrypoint",
            "sh",
            "--mount",
            f"type=volume,src={OLD_VOLUME},dst=/from,readonly",
            "--mount",
            f"type=volume,src={VOLUME},dst=/to",
            old_image,
            "-c",
            "cp -a /from/. /to/",
        )
        (STAGE / "resources.json").write_text(
            json.dumps(
                {
                    "container": NEW,
                    "volume": VOLUME,
                    "old_container": OLD,
                    "old_volume": OLD_VOLUME,
                    "run": str(RUN),
                },
                indent=2,
            )
        )
        print("=== 3/5 在新副本升级数据库扩展 ===", flush=True)
        docker(
            "run",
            "-d",
            "--name",
            NEW,
            "--label",
            LABEL + "=" + str(RUN),
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
            str(RUN / "restore-private.env"),
            "--mount",
            f"type=volume,src={VOLUME},dst=/var/lib/postgresql/data",
            target_image,
        )
        created = True
        guard(NEW, VOLUME)
        wait(NEW)
        databases = json.loads(
            sql(
                NEW,
                "SELECT json_agg(json_build_object('name',datname,'allow',datallowconn) ORDER BY datname) FROM pg_database;",
                "wk_restore_control",
            )
        )
        versions = {}
        for db in databases:
            name = db["name"]
            if not db["allow"]:
                sql(
                    NEW,
                    "ALTER DATABASE " + ident(name) + " ALLOW_CONNECTIONS true;",
                    "wk_restore_control",
                )
            try:
                existing = sql(
                    NEW,
                    "SELECT extname FROM pg_extension WHERE extname IN ('pg_search','vector') ORDER BY 1;",
                    name,
                ).splitlines()
                for ext in existing:
                    version = {"pg_search": "0.25.11", "vector": "0.8.4"}[ext]
                    sql(NEW, f"ALTER EXTENSION {ident(ext)} UPDATE TO '{version}';", name)
                    require(
                        sql(
                            NEW, f"SELECT extversion FROM pg_extension WHERE extname='{ext}';", name
                        )
                        == version,
                        "rehearsal verification failed",
                    )
                versions[name] = sql(
                    NEW, "SELECT extname,extversion FROM pg_extension ORDER BY 1;", name
                )
            finally:
                if not db["allow"]:
                    sql(
                        NEW,
                        "ALTER DATABASE " + ident(name) + " ALLOW_CONNECTIONS false;",
                        "wk_restore_control",
                    )
        require(
            sql(NEW, "SELECT version FROM paradedb.version_info();") == "0.25.11",
            "rehearsal verification failed",
        )
        (STAGE / "extensions.json").write_text(json.dumps(versions, indent=2))
        print("=== 4/5 比较数据与检索，重启后再次验证 ===", flush=True)
        compare(before, snapshot(NEW, "after"))
        docker("restart", "-t", "60", NEW)
        wait(NEW)
        compare(before, snapshot(NEW, "after-restart"))
        docker("stop", "-t", "60", NEW)
        print("=== 5/5 确认保留的旧副本仍可启动 ===", flush=True)
        docker("start", OLD)
        wait(OLD)
        require(
            sql(OLD, "SELECT extversion FROM pg_extension WHERE extname='pg_search';") == "0.22.2",
            "rehearsal verification failed",
        )
        require(
            sql(OLD, "SELECT version,dirty FROM schema_migrations;") == "74|f",
            "rehearsal verification failed",
        )
        print(
            "旧副本知识库/文档数："
            + sql(
                OLD,
                "SELECT (SELECT count(*) FROM knowledge_bases),(SELECT count(*) FROM knowledges);",
            ),
            flush=True,
        )
        code = 0
    except Exception:
        PRIVATE.write(traceback.format_exc().encode())
        PRIVATE.flush()
        print(
            "演练停止，保留所有副本与备份；请仅反馈 progress.log，不要粘贴 private.log。",
            flush=True,
        )
    finally:
        for name, volume in ([(OLD, OLD_VOLUME)] if old_started else []) + (
            [(NEW, VOLUME)] if created else []
        ):
            try:
                item = guard(name, volume)
                if code != 0:
                    subprocess.run(
                        ["docker", "logs", "--tail", "100", name],
                        stdout=PRIVATE,
                        stderr=PRIVATE,
                        timeout=15,
                    )
                if item["State"]["Running"]:
                    docker("stop", "-t", "60", name)
            except Exception:
                code = 1
                print("隔离容器收尾需检查：" + name, flush=True)
        if code == 0:
            print("数据库扩展升级演练通过；WeKnora 应用迁移和生产升级尚未执行。", flush=True)
            (STAGE / "PASS").write_text(
                "Database extension rehearsal passed; application migration and live API acceptance NOT performed.\n"
            )
        (STAGE / "exit-code").write_text(str(code) + "\n")
        print(f"退出码：{code}；记录目录：{STAGE}", flush=True)
        PRIVATE.close()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
