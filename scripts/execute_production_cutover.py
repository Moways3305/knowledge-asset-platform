"""Pinned KAP/WeKnora cutover with verified cold copies and pre-traffic recovery."""

import argparse
import copy
import json
import os
from pathlib import Path
import re
import signal
import time
import traceback
from urllib.parse import quote
import uuid

from prepare_production_release import Runner, require
from production_cutover_inventory import REVISION, ROOT, collect, environment, storage_inventory
from production_cutover_runtime import Engine, Runtime, payload
from resume_production_build import read
import weknora_pg_upgrade_rehearsal as pg
import weknora_schema_upgrade_rehearsal as schema

INFRA = ("kap-postgres-1", "kap-redis-1", "WeKnora-postgres", "WeKnora-redis")
APPS_STOP = (
    "kap-frontend-1",
    "WeKnora-frontend",
    "kap-backend-1",
    "kap-beat-1",
    "kap-worker-1",
    "kap-ocr_worker-1",
    "WeKnora-app",
    "WeKnora-docreader",
)
START = (
    *INFRA,
    "WeKnora-docreader",
    "WeKnora-app",
    "kap-backend-1",
    "kap-worker-1",
    "kap-ocr_worker-1",
    "kap-beat-1",
    "kap-frontend-1",
    "WeKnora-frontend",
)
WORKERS = {"kap-worker-1", "kap-ocr_worker-1", "kap-beat-1"}
HOST = "ws-47k0t1zmjgch8h33.cn-beijing.maas.aliyuncs.com"
ORIGIN = "https://kap.moways.com.cn"


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def sql(r, old, query, database=None):
    env = environment(old)
    return r.docker(
        "exec",
        "-i",
        "-e",
        "PGOPTIONS=-c statement_timeout=600000 -c lock_timeout=30000",
        old["Name"].lstrip("/"),
        "psql",
        "-XqAt",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        env.get("POSTGRES_USER", "postgres"),
        "-d",
        database or env.get("POSTGRES_DB", "postgres"),
        data=("SET standard_conforming_strings=on;\n" + query).encode(),
        timeout=660,
    )


def wait_database(r, old):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            if sql(r, old, "SELECT 1;") == "1":
                return
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError("database did not become ready")


def table_snapshot(r, old, columns=None):
    if columns is None:
        tables = json.loads(
            sql(
                r,
                old,
                "SELECT coalesce(json_agg(tablename ORDER BY tablename),'[]'::json) FROM pg_tables WHERE schemaname='public' AND tablename<>'alembic_version';",
            )
        )
        # Freeze the pre-migration projection. SELECT * would include columns
        # added by 0083 and falsely report changed business data after upgrade.
        columns = {}
        for name in tables:
            names = json.loads(
                sql(
                    r,
                    old,
                    "SELECT coalesce(json_agg(column_name ORDER BY ordinal_position),'[]'::json) "
                    "FROM information_schema.columns WHERE table_schema='public' AND table_name="
                    + literal(name)
                    + ";",
                )
            )
            require(bool(names), "KAP original table has no readable columns")
            columns[name] = ",".join(pg.ident(column) for column in names)
    result = {}
    for name, projection in columns.items():
        result[name] = sql(
            r,
            old,
            "SELECT count(*),md5(coalesce(string_agg(h,'' ORDER BY h),'')) FROM (SELECT md5(to_jsonb(t)::text) h FROM (SELECT "
            + projection
            + " FROM public."
            + pg.ident(name)
            + ") t) s;",
        )
    return columns, result


def corrected_models(rows, picked):
    models = {
        slot: copy.deepcopy(rows[str(picked["selected"][slot])])
        for slot in ("embedding", "chat", "rerank")
    }
    for slot, name, kind, path in (
        ("embedding", "text-embedding-v3", "Embedding", "/compatible-mode/v1"),
        ("rerank", "qwen3-rerank", "Rerank", "/api/v1/services/rerank/text-rerank/text-rerank"),
    ):
        model = models[slot]
        params = model["parameters"]
        if isinstance(params, str):
            params = json.loads(params)
        require(
            model["name"] == name and model["type"] == kind and model["source"] == "remote",
            "selected Aliyun model changed",
        )
        accepted = {"https://dashscope.aliyuncs.com/compatible-mode/v1", "https://" + HOST + path}
        if slot == "rerank":
            accepted.add("https://dashscope.aliyuncs.com" + path)
        require(
            params.get("base_url", "").rstrip("/") in accepted
            and params.get("provider") in {None, "", "aliyun"}
            and not params.get("spec")
            and not params.get("extra_config"),
            "selected Aliyun protocol changed",
        )
        require(
            not any(k.lower() == "authorization" for k in (params.get("custom_headers") or {})),
            "custom authentication needs separate correction",
        )
        params.update(base_url="https://" + HOST + path, provider="aliyun")
        model["parameters"] = params
    key = models["embedding"]["parameters"].get("api_key")
    require(isinstance(key, str) and bool(key.strip()), "embedding credential unavailable")
    models["rerank"]["parameters"]["api_key"] = key
    return models


PROBE = r"""
import asyncio, json, logging, urllib.request, time
from pathlib import Path
from urllib.parse import urlsplit
from app.services.weknora_client import WeKnoraClient
logging.disable(logging.CRITICAL)
data=json.loads(Path('/payload').read_text())
async def main():
    for attempt in range(60):
        try:
            urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=2).read()
            break
        except Exception:
            if attempt==59: raise
            await asyncio.sleep(2)
    client=WeKnoraClient(base_url='http://127.0.0.1:8080',api_key=data['api_key'],timeout=90)
    checks={}
    for slot in ('embedding','chat','rerank'):
        row=data['models'][slot]; params=row['parameters']
        if isinstance(params,str): params=json.loads(params)
        url=urlsplit(params['base_url'])
        assert url.scheme=='https' and not url.username and not url.password and url.port in (None,443)
        assert url.hostname in {'ws-47k0t1zmjgch8h33.cn-beijing.maas.aliyuncs.com','api.deepseek.com'}
        method={'embedding':client.test_embedding_model,'chat':client.check_remote_model,'rerank':client.check_rerank_model}[slot]
        result=await method(model_id=str(row['id']),model_name=row['name'],base_url=params['base_url'],source=row['source'],provider=params.get('provider'),interface_type=params.get('interface_type'))
        assert result.get('available') is True
        if slot=='embedding': assert result.get('dimension')==1024
        checks[slot]=True
    Path('/evidence/live-model-checks.json').write_text(json.dumps(checks))
asyncio.run(main())
"""


def health(r, name="kap-backend-1", revision=REVISION):
    code = (
        "import json,urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health/release',timeout=8)); assert data.get('commit')=="
        + repr(revision)
        + "; urllib.request.urlopen('http://127.0.0.1:8000/health/ready',timeout=8).read()"
    )
    until = time.monotonic() + 180
    while time.monotonic() < until:
        try:
            r.docker("exec", name, "python", "-c", code, timeout=25)
            return
        except Exception:
            time.sleep(3)
    raise RuntimeError("KAP health/release verification failed")


def wait_services(runtime, names, timeout=300):
    deadline = time.monotonic() + timeout
    while True:
        ready = True
        for name in names:
            item = runtime.owned(runtime.state["new"][name])
            require(item["State"]["Running"], "service stopped during readiness check")
            if item["State"].get("Health", {}).get("Status") not in {None, "healthy"}:
                ready = False
        if ready:
            return
        require(time.monotonic() < deadline, "service health timeout")
        time.sleep(5)


def escape_compose(value):
    # Resolved secrets/commands are literals, not a second round of interpolation.
    if isinstance(value, str):
        return value.replace("$", "$$")
    if isinstance(value, list):
        return [escape_compose(item) for item in value]
    if isinstance(value, dict):
        return {key: escape_compose(item) for key, item in value.items()}
    return value


def persist_compose(r, stage, out, originals, configs):
    """Save a complete, immutable-image operational entrypoint for each project."""
    records = read(stage / "compose-sources-private.json")
    result = {}
    for project in ("kap", "weknora"):
        output = {"name": project, "services": {}, "volumes": {}, "networks": {}}
        for name, old in originals.items():
            if name == "kap-migrate-1":
                continue
            labels = old["Config"]["Labels"]
            if labels["com.docker.compose.project"] != project:
                continue
            record = next(
                record
                for record in records
                if record["project"] == project
                and record["directory"] == labels["com.docker.compose.project.working_dir"]
                and record["files"] == labels["com.docker.compose.project.config_files"]
            )
            service = copy.deepcopy(
                read(Path(record["resolved"]))["services"][labels["com.docker.compose.service"]]
            )
            for field in (
                "build",
                "depends_on",
                "profiles",
                "env_file",
                "ports",
                "volumes",
                "networks",
                "extends",
                "pull_policy",
            ):
                service.pop(field, None)
            config = configs[name]
            service["pull_policy"] = "never"
            service.update(
                image=config["Image"],
                container_name=name,
                environment=dict(line.split("=", 1) for line in config["Env"]),
                command=config.get("Cmd"),
                entrypoint=config.get("Entrypoint"),
                user=config.get("User", ""),
                working_dir=config.get("WorkingDir", ""),
            )
            service["networks"] = {}
            for network, endpoint in config["NetworkingConfig"]["EndpointsConfig"].items():
                require(
                    not endpoint.get("IPAMConfig"),
                    "static IP needs explicit operational configuration",
                )
                output["networks"][network] = {"external": True, "name": network}
                service["networks"][network] = {"aliases": endpoint.get("Aliases") or []}
            service["volumes"] = []
            for mount in config["HostConfig"]["Mounts"]:
                entry = {
                    "type": mount["Type"],
                    "source": mount["Source"],
                    "target": mount["Target"],
                    "read_only": mount["ReadOnly"],
                }
                if mount["Type"] == "volume":
                    output["volumes"][mount["Source"]] = {"external": True, "name": mount["Source"]}
                    entry["volume"] = {"nocopy": True}
                elif mount.get("BindOptions", {}).get("Propagation"):
                    entry["bind"] = {"propagation": mount["BindOptions"]["Propagation"]}
                service["volumes"].append(entry)
            service["ports"] = []
            for port, bindings in (old["HostConfig"].get("PortBindings") or {}).items():
                target, protocol = port.split("/")
                for binding in bindings or []:
                    entry = {
                        "target": int(target),
                        "published": binding["HostPort"],
                        "protocol": protocol,
                    }
                    if binding.get("HostIp"):
                        entry["host_ip"] = binding["HostIp"]
                    service["ports"].append(entry)
            output["services"][labels["com.docker.compose.service"]] = service
        path = out / (project + "-compose-private.json")
        path.write_text(json.dumps(escape_compose(output)))
        # Validation only: do not create resources through Compose.
        rendered = json.loads(
            r.docker("compose", "-p", project, "-f", str(path), "config", "--format", "json")
        )
        for service, config in output["services"].items():
            actual = rendered["services"][service]["environment"]
            # Compose config serializes literal dollar signs as $$ so its output
            # can itself be used as a Compose file; containers receive one $.
            unescaped = {
                key: value.replace("$$", "$") if isinstance(value, str) else value
                for key, value in actual.items()
            }
            require(
                actual == config["environment"] or unescaped == config["environment"],
                "operational Compose changed environment literals",
            )
        result[project] = str(path)
    return result


def execute(r, stage, out, report, holder):
    inventory = {}
    collect(r, stage, out, inventory)
    require(not inventory["blockers"], "cutover inventory has blockers")
    require(inventory["databases"]["kap-postgres-1"]["migration"] == "0082", "KAP baseline changed")
    require(
        inventory["databases"]["WeKnora-postgres"]["extensions"].get("vector") == "0.8.1",
        "vector baseline changed",
    )
    size = sum(row["used_mib"] for row in inventory["storage"]) / 1024
    require(
        min(
            [inventory["preparation_disk_free_gib"]]
            + [row["filesystem_free_gib"] for row in inventory["storage"]]
        )
        > max(30, size * 3),
        "cold-copy storage headroom insufficient",
    )
    old = read(stage / "runtime-private.json")
    images = read(stage / "candidate-image-ids.json")
    wk = read(stage / "weknora-candidate.json")
    api = Engine(r.log)
    require(
        api.request("GET", "/info")["ID"] == r.docker("info", "--format", "{{.ID}}"),
        "Docker API and CLI target different engines",
    )
    runtime = Runtime(r, api, out, old, images["backend"])
    holder.append(runtime)
    configs = {}
    for name in START:
        item = old[name]
        image = (
            images[name[4:-2]]
            if name.startswith("kap-") and name[4:-2] in images
            else item["Image"]
        )
        if name == "WeKnora-app":
            image = wk["app"]
        if name == "WeKnora-postgres":
            image = wk["database"]
        old_config = json.loads(r.docker("image", "inspect", item["Image"]))[0]["Config"]
        new_config = json.loads(r.docker("image", "inspect", image))[0]["Config"]
        configs[name] = payload(item, image, new_config, old_config, runtime.token)
    managed = persist_compose(r, stage, out, old, configs)
    report["managed_compose_files"] = managed
    operational_paths = sorted(
        {
            Path(record["files"])
            for record in read(stage / "compose-sources-private.json")
            if record["project"] == "weknora"
        }
    )
    require(
        len(operational_paths) == 2
        and all(
            path.parent in {Path("/data/weknora/repo"), Path("/data/weknora/releases/v0.7.1")}
            and path.name == "docker-compose.yml"
            and path.resolve() == path
            and os.access(path.parent, os.W_OK)
            for path in operational_paths
        ),
        "WeKnora operational Compose files not writable or unexpected",
    )
    for name, config in configs.items():
        labels = config["Labels"]
        project = old[name]["Config"]["Labels"]["com.docker.compose.project"]
        labels["com.docker.compose.project.working_dir"] = str(out)
        labels["com.docker.compose.project.config_files"] = managed[project]
        labels.pop("com.docker.compose.config-hash", None)
        labels["com.docker.compose.image"] = config["Image"]
    # Verify the exact rehearsed SQL bundle before downtime.
    raw = r.docker(
        "run",
        "--rm",
        "--network",
        "none",
        "--entrypoint",
        "sh",
        wk["app_original"],
        "-c",
        "sha256sum /app/migrations/versioned/*.sql",
    )
    require(schema.manifest_digest(raw) == schema.MIGRATION_DIGEST, "migration bundle changed")
    picked = json.loads(
        r.docker(
            "exec",
            "-i",
            "kap-backend-1",
            "python",
            "-",
            data=(stage / "source/scripts/weknora_live_selection.py").read_bytes(),
        )
    )
    (out / "selection-private.json").write_text(json.dumps(picked))
    for name in ("kap-postgres-1", "WeKnora-postgres"):
        require(
            sql(r, old[name], "SELECT rolsuper FROM pg_roles WHERE rolname=current_user;") == "t",
            "database maintenance role unavailable",
        )
        require(
            sql(
                r,
                old[name],
                "SELECT count(*) FROM pg_tablespace WHERE pg_tablespace_location(oid)<>'';",
            )
            == "0",
            "external tablespaces require a separate backup",
        )
    report["checkpoint"] = "stopping_writers"
    print("=== 1/5 关闭入口并等待写入服务退出 ===", flush=True)
    runtime.freeze(APPS_STOP)
    for name in ("kap-postgres-1", "WeKnora-postgres"):
        require(
            sql(
                r,
                old[name],
                "SELECT count(*) FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid();",
            )
            == "0",
            "unexpected database clients remain",
        )
    kap_columns, kap_before = table_snapshot(r, old["kap-postgres-1"])
    defaults = json.loads(
        sql(r, old["kap-postgres-1"], "SELECT row_to_json(d) FROM weknora_default_models d;")
    )
    require(
        all(
            str(defaults["default_" + s + "_model_id"]) == str(picked["selected"][s])
            for s in ("embedding", "chat", "rerank")
        ),
        "model selection changed during stop",
    )
    pg.PRIVATE = r.log
    pg.OWNER = environment(old["WeKnora-postgres"])["POSTGRES_USER"]
    wk_columns = {
        table: pg.sql(
            "WeKnora-postgres",
            "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name="
            + literal(table)
            + " ORDER BY ordinal_position;",
        ).splitlines()
        for table in schema.CORE_TABLES
    }
    wk_before = schema.core_snapshot("WeKnora-postgres", wk_columns)
    deleted_before = int(
        sql(r, old["WeKnora-postgres"], "SELECT count(*) FROM chunks WHERE deleted_at IS NOT NULL;")
    )
    expected_cleanup = int(
        sql(
            r,
            old["WeKnora-postgres"],
            """SELECT count(*) FROM (
        SELECT *, CASE WHEN pg_input_is_valid(image_info,'jsonb') THEN image_info::jsonb ELSE 'null'::jsonb END j
        FROM chunks WHERE deleted_at IS NULL AND chunk_type IN ('image_caption','image_ocr','image_vector')
        ) s WHERE CASE WHEN jsonb_typeof(j)='array' THEN jsonb_array_length(j)=1
        AND j->0->>'sha256'='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855' ELSE false END;""",
        )
    )
    rows = json.loads(
        sql(
            r,
            old["WeKnora-postgres"],
            "SELECT json_agg(m) FROM models m WHERE deleted_at IS NULL AND id IN ("
            + ",".join(
                literal(picked["selected"][slot]) for slot in ("embedding", "chat", "rerank")
            )
            + ");",
        )
    )
    models = corrected_models({str(row["id"]): row for row in rows}, picked)
    (out / "before-private.json").write_text(
        json.dumps({"kap": kap_before, "weknora": wk_before, "models": rows})
    )
    # Every writer, including both Redis servers, is now stopped before copying.
    runtime.freeze(INFRA)
    active = [r.inspect(identity) for identity in r.docker("ps", "-q").splitlines()]
    stores = storage_inventory(old, active)
    require(
        not any(entry["unknown_writers"] for entry in stores),
        "additional writer appeared during stop",
    )
    print("=== 2/5 制作并校验当前数据库、队列和文件的停写副本 ===", flush=True)
    report["checkpoint"] = "cold_backup"
    runtime.backup(stores)
    report["consistent_backup_completed"] = True
    runtime.detach_originals()
    for name, config in configs.items():
        runtime.create(name, config)
    runtime.state["data_mutated"] = True
    runtime.save()
    report["checkpoint"] = "database_upgrade"
    print("=== 3/5 升级数据库，核对原有业务数据 ===", flush=True)
    for name in INFRA:
        runtime.start(name)
    for name in ("kap-postgres-1", "WeKnora-postgres"):
        wait_database(r, old[name])
    dbs = json.loads(
        sql(
            r,
            old["WeKnora-postgres"],
            "SELECT json_agg(json_build_object('name',datname,'allow',datallowconn)) FROM pg_database;",
            "postgres",
        )
    )
    for db in dbs:
        if not db["allow"]:
            sql(
                r,
                old["WeKnora-postgres"],
                "ALTER DATABASE " + pg.ident(db["name"]) + " ALLOW_CONNECTIONS true;",
                "postgres",
            )
        try:
            existing = sql(
                r,
                old["WeKnora-postgres"],
                "SELECT extname FROM pg_extension WHERE extname IN ('pg_search','vector');",
                db["name"],
            ).splitlines()
            for ext in existing:
                version = {"pg_search": "0.25.11", "vector": "0.8.4"}[ext]
                sql(
                    r,
                    old["WeKnora-postgres"],
                    "ALTER EXTENSION " + pg.ident(ext) + " UPDATE TO " + literal(version) + ";",
                    db["name"],
                )
        finally:
            if not db["allow"]:
                sql(
                    r,
                    old["WeKnora-postgres"],
                    "ALTER DATABASE " + pg.ident(db["name"]) + " ALLOW_CONNECTIONS false;",
                    "postgres",
                )
    env = environment(old["WeKnora-postgres"])
    url = (
        "postgres://"
        + quote(env["POSTGRES_USER"], safe="")
        + ":"
        + quote(env["POSTGRES_PASSWORD"], safe="")
        + "@127.0.0.1:5432/"
        + quote(env["POSTGRES_DB"], safe="")
        + "?sslmode=disable"
    )
    runtime.helper(
        [
            "sh",
            "-ec",
            'exec migrate -path /app/migrations/versioned -database "$CUTOVER_DB_URL" up',
        ],
        image=wk["app_original"],
        network="container:WeKnora-postgres",
        env=["CUTOVER_DB_URL=" + url],
    )
    require(
        sql(r, old["WeKnora-postgres"], "SELECT version,dirty FROM schema_migrations;") == "134|f",
        "WeKnora migration target not reached",
    )
    require(
        schema.core_snapshot("WeKnora-postgres", wk_columns) == wk_before,
        "WeKnora core data comparison failed",
    )
    require(
        int(
            sql(
                r,
                old["WeKnora-postgres"],
                "SELECT count(*) FROM chunks WHERE deleted_at IS NOT NULL;",
            )
        )
        == deleted_before + expected_cleanup,
        "unexpected chunk deletion during migration",
    )
    require(
        sql(
            r,
            old["WeKnora-postgres"],
            "SELECT extversion FROM pg_extension WHERE extname='pg_search';",
        )
        == "0.25.11",
        "pg_search version differs",
    )
    require(
        sql(
            r,
            old["WeKnora-postgres"],
            "SELECT extversion FROM pg_extension WHERE extname='vector';",
        )
        == "0.8.4",
        "vector version differs",
    )
    runtime.helper(
        ["python", "-m", "alembic", "upgrade", "head"],
        image=images["migrate"],
        network=old["kap-migrate-1"]["HostConfig"]["NetworkMode"],
        env=old["kap-backend-1"]["Config"]["Env"],
    )
    require(
        sql(r, old["kap-postgres-1"], "SELECT version_num FROM alembic_version;")
        == "0083_model_registry",
        "KAP migration target not reached",
    )
    require(
        table_snapshot(r, old["kap-postgres-1"], kap_columns)[1] == kap_before,
        "KAP original data comparison failed",
    )
    report["checkpoint"] = "models_and_staged_health"
    print("=== 4/5 修正模型配置并验证真实模型及新版应用 ===", flush=True)
    for slot in ("embedding", "rerank"):
        row = models[slot]
        result = sql(
            r,
            old["WeKnora-postgres"],
            "UPDATE models SET parameters="
            + literal(json.dumps(row["parameters"]))
            + "::jsonb, updated_at=now() WHERE id="
            + literal(row["id"])
            + " AND deleted_at IS NULL RETURNING id;",
        )
        require(result == str(row["id"]), "selected model update failed")
    for name in (
        "WeKnora-docreader",
        "WeKnora-app",
        "kap-backend-1",
        "kap-frontend-1",
        "WeKnora-frontend",
    ):
        runtime.start(name)
    health(r)
    runtime.helper(
        [
            "python",
            "-c",
            "import json,urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/',timeout=15).read(); data=json.load(urllib.request.urlopen('http://127.0.0.1:8080/release-identity.json',timeout=15)); assert data.get('commit')=="
            + repr(REVISION)
            + "; urllib.request.urlopen('http://127.0.0.1:8080/health/ready',timeout=15).read()",
        ],
        network="container:kap-frontend-1",
    )
    proof = out / "models-private.json"
    proof.write_text(
        json.dumps(
            {"models": models, "api_key": environment(old["kap-backend-1"])["WEKNORA_API_KEY"]}
        )
    )
    runtime.helper(
        ["python", "-c", PROBE],
        network="container:WeKnora-app",
        mounts=[
            f"type=bind,src={proof},dst=/payload,readonly",
            f"type=bind,src={out},dst=/evidence",
        ],
    )
    require(
        read(out / "live-model-checks.json") == {"embedding": True, "chat": True, "rerank": True},
        "model validation incomplete",
    )
    report["models"] = {
        "embedding": True,
        "rerank": True,
        "chat": True,
        "embedding_dimension": 1024,
        "aliyun_shared_key": True,
        "workspace_endpoint_corrected": True,
    }
    wait_services(runtime, [name for name in START if name not in WORKERS])
    r.docker(
        "exec",
        "kap-backend-1",
        "python",
        "-c",
        "import os,json,urllib.request; assert os.access('/data/uploads',os.R_OK|os.W_OK|os.X_OK); d=json.load(urllib.request.urlopen('http://127.0.0.1:8000/health/config',timeout=10)); assert d.get('production_ready') is True and d.get('production_blockers')==[]",
    )
    r.docker(
        "exec", "WeKnora-app", "sh", "-ec", "test -w /data/files; test -w /app/skills/preloaded"
    )
    r.docker(
        "exec",
        "kap-backend-1",
        "python",
        "-m",
        "app.commands.sync_release_notes",
        "--check-only",
        timeout=60,
    )
    runtime.configure_entrypoints(operational_paths, Path(managed["weknora"]), images)
    report["operational_image_references_updated"] = True
    # Durable boundary BEFORE any original host port is restored. After this marker,
    # failures retain the new databases; never erase possibly accepted user writes.
    report["checkpoint"] = "opening_traffic"
    print("=== 5/5 恢复正式入口、后台任务并核对发布版本 ===", flush=True)
    runtime.state["traffic_opening"] = True
    runtime.save()
    report["production_switched"] = True
    # Restart dependants after the databases obtain their final host bindings.
    for name in reversed(START):
        if name in WORKERS:
            continue
        identity = runtime.state["new"][name]
        if runtime.owned(identity)["State"]["Running"]:
            r.docker("stop", "-t", "120", identity, timeout=150)
    for name in START:
        config = copy.deepcopy(configs[name])
        config["HostConfig"]["PortBindings"] = copy.deepcopy(
            old[name]["HostConfig"].get("PortBindings") or {}
        )
        config["HostConfig"]["RestartPolicy"] = copy.deepcopy(
            old[name]["HostConfig"]["RestartPolicy"]
        )
        runtime.remove_new(name)
        runtime.create(name, config)
        runtime.start(name)
        if name in ("kap-postgres-1", "WeKnora-postgres"):
            wait_database(r, old[name])
        if name == "kap-backend-1":
            health(r)
    health(r)
    wait_services(runtime, START)
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
    r.capture("git", "-C", "/data/kap/repo", "merge", "--ff-only", REVISION, timeout=60)
    for name in START:
        item = runtime.owned(runtime.state["new"][name])
        require(
            item["State"]["Running"] and item["Image"] == configs[name]["Image"],
            "published service identity check failed",
        )
    # Retained old containers carry immutable Compose labels. Remove only these
    # stopped, renamed originals AFTER successful cutover to avoid future Compose
    # mistaking them for current replicas. Images, snapshots, and cold copies stay.
    for name in START:
        previous = r.inspect(old[name]["Id"])
        require(
            not previous["State"]["Running"]
            and previous["Image"] == old[name]["Image"]
            and previous["Name"] == "/" + name + "-previous-" + runtime.token[-10:],
            "old container cleanup identity changed",
        )
        r.docker("rm", previous["Id"])
    runtime.state["passed"] = True
    runtime.save()
    report.update(
        passed=True,
        checkpoint="complete",
        cutover_completed=True,
        version="v1.0.0",
        revision=REVISION,
        migration_target="0083_model_registry",
        weknora_schema=134,
        original_images_configs_and_cold_copies_retained=True,
        historical_migrate_container_retained=True,
    )


def main():
    import fcntl

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, type=Path)
    parser.add_argument("--recover", help="Recover a recorded cutover before traffic opening")
    parser.add_argument(
        "--execute", action="store_true", help="Perform the already authorized production cutover"
    )
    args = parser.parse_args()
    require(bool(args.execute) != bool(args.recover), "choose --execute or --recover")
    require(
        os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")
        == "unix:///var/run/docker.sock",
        "unexpected Docker endpoint",
    )
    os.umask(0o077)
    stage = args.stage.resolve(strict=True)
    require(
        stage.parent == ROOT / "production-preparations"
        and re.fullmatch(r"\d{8}-\d{6}-[a-f0-9]{6}", stage.name),
        "unexpected preparation",
    )
    report = {
        "phase": "production_cutover",
        "passed": False,
        "production_switched": False,
        "raw_logs_included": False,
    }
    holder = []
    with (stage.parent / "prepare.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Never start a second cutover on top of an unfinished or published one.
        if args.recover:
            require(
                re.fullmatch(r"cutover-execute-[a-f0-9]{10}", args.recover),
                "invalid recovery record",
            )
            out = (stage / args.recover).resolve(strict=True)
            require(out.parent == stage, "recovery path changed")
        else:
            for previous in stage.glob("cutover-execute-*"):
                state_path = previous / "state-private.json"
                if state_path.exists():
                    state = read(state_path)
                    require(
                        not state["traffic_opening"]
                        and (state.get("recovered") or not state["touched"]),
                        "unfinished or published cutover exists",
                    )
            out = stage / ("cutover-execute-" + uuid.uuid4().hex[:10])
            out.mkdir(mode=0o700)
        print("切换记录目录：" + str(out), flush=True)
        with (out / "private.log").open("ab") as log:
            r = Runner(log)

            def interrupted(signum, frame):
                raise RuntimeError("cutover interrupted")

            signal.signal(signal.SIGTERM, interrupted)
            try:
                if args.recover:
                    state = read(out / "state-private.json")
                    require(
                        state["originals"] == read(stage / "runtime-private.json"),
                        "recovery originals changed",
                    )
                    report["production_switched"] = bool(state["traffic_opening"])
                    require(
                        not state["traffic_opening"],
                        "traffic already opened; data rollback forbidden",
                    )
                    runtime = object.__new__(Runtime)
                    runtime.r, runtime.api, runtime.directory = r, Engine(log), out
                    runtime.token, runtime.state = out.name, state
                    runtime.helper_image = read(stage / "candidate-image-ids.json")["backend"]
                    for index, backup in enumerate(state["backups"]):
                        require(
                            backup["volume"] == "kap-cold-" + out.name[-10:] + "-" + str(index),
                            "backup volume record changed",
                        )
                        require(
                            any(
                                backup["mount"] in item.get("Mounts", [])
                                for item in state["originals"].values()
                            ),
                            "backup target changed",
                        )
                    holder.append(runtime)
                    runtime.recover(START)
                    health(r, revision=read(stage / "release-manifest.json")["previous_commit"])
                    report.update(
                        passed=True,
                        phase="production_cutover_recovery",
                        previous_release_recovered=True,
                    )
                else:
                    execute(r, stage, out, report, holder)
            except BaseException:
                log.write(traceback.format_exc().encode())
                log.flush()
                report["error"] = "cutover_failed_private_details_retained"
                if holder and holder[0].state["touched"] and not holder[0].state["traffic_opening"]:
                    print("开放入口前发生失败，正在恢复停写副本和旧服务。", flush=True)
                    try:
                        holder[0].recover(START)
                        health(r, revision=read(stage / "release-manifest.json")["previous_commit"])
                        report["previous_release_recovered"] = True
                    except BaseException:
                        log.write(traceback.format_exc().encode())
                        log.flush()
                        report["previous_release_recovered"] = False
                elif holder and holder[0].state["traffic_opening"]:
                    report["production_switched"] = True
                    report["automatic_data_rollback_skipped"] = True
            finally:
                (out / ("recovery-report.json" if args.recover else "report.json")).write_text(
                    json.dumps(report, ensure_ascii=False, indent=2)
                )
                print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
