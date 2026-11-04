"""Read-only validation of a candidate SQL fix; never installs an application patch."""

import json
import math
import time
import traceback

import weknora_pg_upgrade_rehearsal as pg
from weknora_rehearsal_diagnostics import classify
from weknora_search_plan_rehearsal import (
    disabled_question_ids,
    plan_summary,
    retrieval_limit,
    sql_value,
)

REFERENCE_CAP = 100000


def build_sql(ids, excluded, keyword, limit, mode="rewrite", prepared=False, documents=(), tags=()):
    pg.require(ids and 1 <= limit <= 500, "invalid scope or limit")
    pg.require(set(excluded).issubset(ids), "exclusion outside permitted scope")
    pg.require(mode in {"rewrite", "scores", "eligible"}, "unknown query mode")
    values = []

    def bind(value):
        values.append(value)
        return "$" + str(len(values)) if prepared else sql_value(value)

    def in_values(column, items):
        return column + " IN (" + ",".join(bind(v) for v in items) + ")"

    filters = [in_values("knowledge_base_id", ids)]
    if documents:
        filters.append(in_values("knowledge_id", documents))
    if tags:
        filters.append(in_values("tag_id", tags))
    filters += [
        "content ||| " + bind(keyword),
        "(is_enabled IS NULL OR is_enabled = " + bind(True) + ")",
    ]
    base = ' FROM "embeddings" WHERE ' + " AND ".join(filters)
    exclusion = "true"
    if excluded:
        exclusion = (
            "NOT ("
            + in_values("knowledge_base_id", excluded)
            + " AND source_type = 0 AND chunk_id <> '' AND source_id <> chunk_id"
            " AND substr(source_id, 1, length(chunk_id) + 1) = chunk_id || '-')"
        )
    if mode == "eligible":
        # Independent admissibility oracle: original filter, without score().
        sql = "SELECT id" + base + " AND " + exclusion + " LIMIT " + str(REFERENCE_CAP + 1)
    elif mode == "scores":
        # No complex predicate at this level. A sentinel prevents silently
        # accepting a truncated ranking reference; exceeding it fails closed.
        # No exclusion parameters are used by this query.
        return build_score_sql(ids, keyword, prepared, documents, tags)
    else:
        sql = (
            "WITH scored AS MATERIALIZED ("
            "SELECT paradedb.score(id) AS score,id,content,source_id,source_type,chunk_id,"
            "knowledge_id,knowledge_base_id,tag_id" + base + " ORDER BY score DESC) "
            "SELECT score,id,content,source_id,source_type,chunk_id,knowledge_id,knowledge_base_id,tag_id"
            " FROM scored WHERE " + exclusion + " ORDER BY score DESC LIMIT " + bind(limit)
        )
    return sql, values


def build_score_sql(ids, keyword, prepared, documents, tags):
    # Generate the same simple filters without unused exclusion parameters.
    sql, values = build_sql(ids, [], keyword, 1, "eligible", prepared, documents, tags)
    sql = sql.replace("SELECT id FROM", "SELECT paradedb.score(id) AS score,id FROM", 1)
    sql = sql.replace(" AND true LIMIT ", " ORDER BY score DESC LIMIT ")
    return sql, values


def compare_results(scores, eligible, actual, limit):
    # Accept any ordering among equal scores, but reject missing higher scores,
    # wrong scores, duplicates, prohibited IDs and early-LIMIT under-recall.
    reference_complete = len(scores) <= REFERENCE_CAP and len(eligible) <= REFERENCE_CAP
    allowed = {str(row["id"]) for row in eligible}
    ranked = {str(row["id"]): float(row["score"]) for row in scores}
    actual_ids = [str(row["id"]) for row in actual]
    actual_scores = [float(row["score"]) for row in actual]
    reference_valid = (
        reference_complete
        and len(ranked) == len(scores)
        and len(allowed) == len(eligible)
        and allowed.issubset(ranked)
        and all(math.isfinite(v) for v in ranked.values())
    )
    expected_scores = sorted((ranked[k] for k in allowed if k in ranked), reverse=True)[:limit]
    checks = {
        "reference_complete": reference_complete,
        "reference_valid": reference_valid,
        "returned_count": len(actual),
        "expected_count": min(limit, len(allowed)),
        "eligible_count": len(allowed),
        "unique_results": len(actual_ids) == len(set(actual_ids)),
        "only_eligible_results": set(actual_ids).issubset(allowed),
        "correct_top_scores": actual_scores == expected_scores,
        "scores_preserved": all(
            key in ranked and score == ranked[key] for key, score in zip(actual_ids, actual_scores)
        ),
    }
    checks["passed"] = (
        all(
            checks[k]
            for k in (
                "reference_complete",
                "reference_valid",
                "unique_results",
                "only_eligible_results",
                "correct_top_scores",
                "scores_preserved",
            )
        )
        and checks["returned_count"] == checks["expected_count"]
    )
    return checks


def json_query(sql):
    return "SELECT COALESCE(json_agg(probe_row),'[]'::json) FROM (" + sql + ") probe_row"


def run(name, prefix, libraries, scopes, config, stage):
    disabled = set(disabled_question_ids(libraries))
    cases = []
    # Capture positive and empty results across keywords and model-ID groups.
    for label, ids in scopes:
        excluded = [v for v in ids if v in disabled]
        limit = retrieval_limit(config, len(ids))
        for keyword in ("项目", "知识", "验收"):
            references = None
            for variant, setting, prepared in (
                ("literal", "", False),
                ("custom_plan", "SET LOCAL plan_cache_mode=force_custom_plan;", True),
                ("generic_plan", "SET LOCAL plan_cache_mode=force_generic_plan;", True),
            ):
                case = {
                    "scope": label,
                    "keyword": keyword,
                    "variant": variant,
                    "library_count": len(ids),
                    "excluded_question_libraries": len(excluded),
                    "limit": limit,
                }
                pg.PRIVATE.flush()
                offset = (stage / "private.log").stat().st_size
                started = time.monotonic()
                try:
                    if references is None:
                        references = []
                        for mode in ("scores", "eligible"):
                            sql, _ = build_sql(ids, excluded, keyword, limit, mode)
                            references.append(
                                json.loads(pg.sql(name, prefix + json_query(sql) + "; ROLLBACK;"))
                            )
                    sql, values = build_sql(ids, excluded, keyword, limit, prepared=prepared)
                    # Wrap before PREPARE so EXECUTE itself returns JSON. The
                    # materialization boundary remains in the actual statement.
                    setup = ""
                    execute = json_query(sql)
                    if prepared:
                        setup = "PREPARE kap_rewrite_probe AS " + execute + "; "
                        execute = (
                            "EXECUTE kap_rewrite_probe("
                            + ",".join(sql_value(v) for v in values)
                            + ")"
                        )
                    plan = pg.sql(
                        name,
                        prefix
                        + setting
                        + setup
                        + "EXPLAIN (FORMAT JSON) "
                        + execute
                        + "; ROLLBACK;",
                    )
                    case["plan"] = plan_summary(json.loads(plan))
                    actual = json.loads(
                        pg.sql(name, prefix + setting + setup + execute + "; ROLLBACK;")
                    )
                    case.update(compare_results(*references, actual, limit))
                    case["executed"] = True
                except Exception:
                    references = None
                    pg.PRIVATE.write(traceback.format_exc().encode())
                    pg.PRIVATE.flush()
                    private = (stage / "private.log").read_bytes()[offset:]
                    case.update(
                        {
                            "executed": False,
                            "passed": False,
                            "error": classify(private.decode(errors="replace")),
                        }
                    )
                case["elapsed_seconds"] = round(time.monotonic() - started, 3)
                cases.append(case)
                print(json.dumps(case, ensure_ascii=False), flush=True)
    positive_exclusion = any(
        c.get("passed") and c.get("returned_count", 0) > 0 and c["excluded_question_libraries"] > 0
        for c in cases
    )
    return {
        "candidate": "materialized scoring; original exclusion before final limit",
        "passed": bool(cases) and all(c["passed"] for c in cases) and positive_exclusion,
        "positive_exclusion_case": positive_exclusion,
        "cases": cases,
        "scope": "isolated SQL only; no app patch installed, no API acceptance",
    }
