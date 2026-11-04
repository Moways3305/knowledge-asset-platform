"""Compare fixed read-only keyword SQL plans in an already isolated failed app copy."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import traceback
import uuid

import weknora_pg_upgrade_rehearsal as pg
from weknora_rehearsal_diagnostics import classify


def literal(value):
    return "E'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"


def query(ids):
    scope = "knowledge_base_id IN (" + ",".join(literal(v) for v in ids) + ") AND " if ids else ""
    return (
        "SELECT paradedb.score(id) AS score,id,content,source_id,source_type,chunk_id,"
        "knowledge_id,knowledge_base_id,tag_id FROM embeddings WHERE "
        + scope
        + "content ||| '项目' AND (is_enabled IS NULL OR is_enabled=true) ORDER BY score DESC LIMIT 20"
    )


def plan_summary(value):
    nodes = set()
    custom = set()
    parallel = False

    def visit(item):
        nonlocal parallel
        if isinstance(item, dict):
            node = item.get("Node Type")
            if node in {
                "Limit",
                "Sort",
                "Gather",
                "Gather Merge",
                "Seq Scan",
                "Index Scan",
                "Index Only Scan",
                "Bitmap Heap Scan",
                "Bitmap Index Scan",
                "Custom Scan",
                "Result",
                "Aggregate",
                "Nested Loop",
                "Hash Join",
                "Merge Join",
                "Materialize",
            }:
                nodes.add(node)
            provider = item.get("Custom Plan Provider", "")
            if isinstance(provider, str) and ("ParadeDB" in provider or "pg_search" in provider):
                custom.add("ParadeDB")
            parallel = (
                parallel or bool(item.get("Parallel Aware")) or bool(item.get("Workers Planned"))
            )
            for v in item.values():
                visit(v)
        elif isinstance(item, list):
            for v in item:
                visit(v)

    visit(value)
    return {"nodes": sorted(nodes), "custom_providers": sorted(custom), "parallel": parallel}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    import fcntl

    os.umask(0o077)
    source = args.stage.resolve(strict=True)
    run = source.parent
    pg.require(
        run.parent == Path("/data/weknora/upgrade-rehearsals")
        and run.name.startswith("run-")
        and run.name[4:].isalnum()
        and source.name.startswith("app090-"),
        "unexpected rehearsal stage",
    )
    lock = (Path.home() / ".weknora-rehearsal.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    stage = source / ("search-plan-" + uuid.uuid4().hex[:10])
    stage.mkdir()
    pg.RUN, pg.STAGE = run, stage
    pg.PRIVATE = (stage / "private.log").open("ab")
    result = {
        "diagnostic_only": True,
        "production_changed": False,
        "raw_sql_or_results_included": False,
        "probes": [],
    }
    started = False
    code = 1
    try:
        result["original_failure"] = classify((source / "probe-private.log").read_text())
        resources = json.loads((source / "resources.json").read_text())
        name, volume = resources["container"], resources["volume"]
        pg.require(
            name.startswith("wk-app090-") and volume == name + "-data", "unexpected container names"
        )
        item = pg.guard(name, volume)
        images = json.loads((source / "images.json").read_text())
        pg.require(
            not item["State"]["Running"] and item["Image"] == images["database"],
            "database baseline changed",
        )
        # Do not diagnose while sibling services can still mutate this copy.
        for key in ["app", "redis"]:
            child = pg.inspect(resources[key])
            pg.require(
                child["Config"]["Labels"].get(pg.LABEL) == str(run)
                and not child["State"]["Running"],
                "sibling still running or identity changed",
            )
        bootstrap = dict(
            line.split("=", 1)
            for line in (run / "restore-private.env").read_text().splitlines()
            if "=" in line
        )
        pg.OWNER = bootstrap["POSTGRES_USER"]
        appenv = dict(
            line.split("=", 1)
            for line in (source / "app-private.env").read_text().splitlines()
            if "=" in line
        )
        role = appenv["DB_USER"]
        pg.require(
            pg.OWNER.startswith("wkrestore_") and pg.OWNER.replace("_", "").isalnum(),
            "invalid bootstrap user",
        )
        key = json.loads((source / "probe-private.json").read_text())["api_key"]
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        print("仅启动隔离数据库，应用及 Redis 保持停止。", flush=True)
        started = True
        pg.docker("start", name)
        pg.wait(name)
        pg.require(
            pg.sql(name, "SELECT version,dirty FROM schema_migrations;") == "134|f",
            "schema changed",
        )
        rows = json.loads(
            pg.sql(
                name,
                "SELECT COALESCE(json_agg(k),'[]'::json) FROM (SELECT tenant_id,full_access,knowledge_base_ids FROM tenant_api_keys WHERE key_hash="
                + literal(key_hash)
                + " AND revoked_at IS NULL) k;",
            )
        )
        pg.require(
            len(rows) == 1 and rows[0]["tenant_id"] is not None,
            "cannot bind original KAP key to one workspace",
        )
        bound = rows[0]
        libraries = json.loads(
            pg.sql(
                name,
                "SELECT COALESCE(json_agg(k),'[]'::json) FROM (SELECT id,embedding_model_id FROM knowledge_bases WHERE deleted_at IS NULL AND tenant_id="
                + str(int(bound["tenant_id"]))
                + " ORDER BY id) k;",
            )
        )
        if not bound["full_access"]:
            allowed = bound["knowledge_base_ids"] or []
            if isinstance(allowed, str):
                allowed = json.loads(allowed)
            libraries = [k for k in libraries if k["id"] in allowed]
        pg.require(libraries, "no permitted libraries")
        groups = {}
        for library in libraries:
            groups.setdefault(library.get("embedding_model_id") or "", []).append(library["id"])
        scopes = [
            ("all_allowed", [k["id"] for k in libraries]),
            ("single_allowed", [libraries[0]["id"]]),
        ]
        scopes += [
            ("model_group_" + str(i), ids) for i, ids in enumerate(list(groups.values())[:4], 1)
        ]
        variants = {
            "default": "",
            "no_parallel": "SET LOCAL max_parallel_workers_per_gather=0;",
            "no_regular_index_scans": "SET LOCAL enable_indexscan=off; SET LOCAL enable_bitmapscan=off;",
        }
        prefix = (
            "BEGIN READ ONLY; SET LOCAL ROLE "
            + pg.ident(role)
            + "; SET LOCAL statement_timeout='15s'; "
        )
        for label, ids in scopes:
            for variant, settings in variants.items():
                case = {"scope": label, "library_count": len(ids), "variant": variant}
                sql = query(ids)
                pg.PRIVATE.flush()
                offset = (stage / "private.log").stat().st_size
                try:
                    plan = pg.sql(
                        name, prefix + settings + "EXPLAIN (FORMAT JSON) " + sql + "; ROLLBACK;"
                    )
                    case["plan"] = plan_summary(json.loads(plan))
                    output = pg.sql(name, prefix + settings + sql + "; ROLLBACK;")
                    case.update(
                        {
                            "executed": True,
                            "nonempty": bool(output),
                            "result_digest": hashlib.sha256(output.encode()).hexdigest(),
                        }
                    )
                except Exception:
                    pg.PRIVATE.flush()
                    # Classify, never emit SQL, document content, identities or endpoint details.
                    private = (stage / "private.log").read_bytes()
                    case.update(
                        {
                            "executed": False,
                            "error": classify(private[offset:].decode(errors="replace")),
                        }
                    )
                result["probes"].append(case)
                print(json.dumps(case, ensure_ascii=False), flush=True)
        code = 0
    except Exception:
        pg.PRIVATE.write(traceback.format_exc().encode())
        print("诊断未完成，保留私密日志；请勿粘贴私密日志。", flush=True)
    finally:
        if started:
            try:
                pg.guard(name, volume)
                pg.docker("stop", "-t", "60", name)
            except Exception:
                code = 1
                print("隔离数据库收尾需检查。", flush=True)
        result["diagnostic_completed"] = code == 0
        (stage / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        (stage / "exit-code").write_text(str(code) + "\n")
        print(
            json.dumps(
                {
                    "original_failure": result.get("original_failure"),
                    "diagnostic_completed": code == 0,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        print(
            f"诊断退出码：{code}；目录：{stage}。退出码 0 仅表示诊断完成，不表示检索验收通过。",
            flush=True,
        )
        pg.PRIVATE.close()
    raise SystemExit(code)


if __name__ == "__main__":
    main()
