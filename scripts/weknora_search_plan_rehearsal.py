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


def disabled_question_ids(libraries):
    # v0.9.0: a nil config is off; FAQ similar questions must remain searchable.
    return [
        k["id"]
        for k in libraries
        if k.get("type") != "faq"
        and not (k.get("question_generation_config") or {}).get("enabled", False)
    ]


def retrieval_limit(config, library_count):
    pg.require(library_count > 0, "empty search scope")
    depth = int((config or {}).get("embedding_top_k") or 0)
    depth = depth if depth > 0 else 50
    # Probe requests match_count=5, rerank disabled. Mirror service over-retrieval.
    return min(max(max(depth, 5) * 5, 50) * library_count, 500)


def query_parts(ids, excluded=(), limit=20, prepared=False):
    pg.require(ids and 1 <= limit <= 500, "invalid bounded search")
    pg.require(set(excluded).issubset(ids), "exclusion outside permitted scope")
    values = []

    def bind(value):
        values.append(value)
        return "$" + str(len(values)) if prepared else sql_value(value)

    scope = '"knowledge_base_id" IN (' + ",".join(bind(v) for v in ids) + ") AND "
    sql = (
        "SELECT paradedb.score(id) AS score,id,content,source_id,source_type,chunk_id,"
        'knowledge_id,knowledge_base_id,tag_id FROM "embeddings" WHERE '
        + scope
        + "content ||| "
        + bind("项目")
        + " AND (is_enabled IS NULL OR is_enabled = "
        + bind(True)
        + ")"
    )
    if excluded:
        sql += (
            " AND NOT (knowledge_base_id IN ("
            + ",".join(bind(v) for v in excluded)
            + ") AND source_type = 0 AND chunk_id <> '' AND source_id <> chunk_id"
            " AND substr(source_id, 1, length(chunk_id) + 1) = chunk_id || '-')"
        )
    sql += ' ORDER BY "score" DESC LIMIT ' + bind(limit)
    return sql, values


def sql_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    return literal(value)


def query(ids):
    return query_parts(ids)[0]


def statements(ids, excluded, limit, prepared=False):
    sql, values = query_parts(ids, excluded, limit, prepared)
    if not prepared:
        return "", sql
    # SQL PREPARE compares server plan modes; it is not a pgx wire-protocol test.
    setup = "PREPARE kap_search_probe AS " + sql + "; "
    execute = "EXECUTE kap_search_probe(" + ",".join(sql_value(v) for v in values) + ")"
    return setup, execute


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
                "SELECT COALESCE(json_agg(k),'[]'::json) FROM (SELECT id,embedding_model_id,type,question_generation_config FROM knowledge_bases WHERE deleted_at IS NULL AND tenant_id="
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
        configs = json.loads(
            pg.sql(
                name,
                "SELECT COALESCE(json_agg(t),'[]'::json) FROM (SELECT retrieval_config FROM tenants WHERE id="
                + str(int(bound["tenant_id"]))
                + ") t;",
            )
        )
        pg.require(len(configs) == 1, "tenant retrieval settings missing")
        config = configs[0]["retrieval_config"]
        disabled = set(disabled_question_ids(libraries))
        groups = {}
        for library in libraries:
            groups.setdefault(library.get("embedding_model_id") or "", []).append(library["id"])
        # Model IDs approximate the app's model/endpoint/dimension grouping.
        scopes = [
            ("model_group_" + str(i), ids) for i, ids in enumerate(list(groups.values())[:4], 1)
        ]
        result["grouping"] = "embedding_model_id; at most four groups"
        result["prepared_scope"] = "server SQL PREPARE; not pgx wire protocol"
        prefix = (
            "BEGIN READ ONLY; SET LOCAL ROLE "
            + pg.ident(role)
            + "; SET LOCAL statement_timeout='15s'; "
        )
        for label, ids in scopes:
            excluded = [v for v in ids if v in disabled]
            topk = retrieval_limit(config, len(ids))
            variants = [
                ("plain_20", (), 20, False, ""),
                ("exclusion_20", excluded, 20, False, ""),
                ("plain_actual_limit", (), topk, False, ""),
                ("full_literal", excluded, topk, False, ""),
                (
                    "full_custom_plan",
                    excluded,
                    topk,
                    True,
                    "SET LOCAL plan_cache_mode=force_custom_plan;",
                ),
                (
                    "full_generic_plan",
                    excluded,
                    topk,
                    True,
                    "SET LOCAL plan_cache_mode=force_generic_plan;",
                ),
                (
                    "full_no_parallel",
                    excluded,
                    topk,
                    False,
                    "SET LOCAL max_parallel_workers_per_gather=0;",
                ),
                (
                    "full_no_regular_index_scans",
                    excluded,
                    topk,
                    False,
                    "SET LOCAL enable_indexscan=off; SET LOCAL enable_bitmapscan=off;",
                ),
            ]
            for variant, exclusions, limit, prepared, settings in variants:
                case = {
                    "scope": label,
                    "library_count": len(ids),
                    "variant": variant,
                    "excluded_question_libraries": len(exclusions),
                    "limit": limit,
                }
                setup, sql = statements(ids, exclusions, limit, prepared)
                pg.PRIVATE.flush()
                offset = (stage / "private.log").stat().st_size
                try:
                    plan = pg.sql(
                        name,
                        prefix + settings + setup + "EXPLAIN (FORMAT JSON) " + sql + "; ROLLBACK;",
                    )
                    case["plan"] = plan_summary(json.loads(plan))
                    output = pg.sql(name, prefix + settings + setup + sql + "; ROLLBACK;")
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
