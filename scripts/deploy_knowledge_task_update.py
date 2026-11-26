"""Release the merged inspection-continuity and delegated knowledge tasks."""

from functools import partial
from pathlib import Path

import deploy_maintenance_update as delivery
import deploy_stage_release as stage
import execute_production_cutover as cutover
from prepare_production_release import require

REVISION = "07d013228b8decb4651ec3dee44ae01900e8d43f"
VERSION = "v1.5.0"
BASELINES = {
    "8f4b15449b85aa1cb9815d5069af8f2bd802cf0c": "v1.4.1",
    "85ecf0a133f3915d06520b722c591acb05a724cc": "v1.4.2",
}
BASELINE_SCHEMA = "0093_optional_knowledge_review"
SCHEMA = "0095_knowledge_tasks"
NOTES = Path(__file__).resolve().parents[1] / "release-notes"


def select_profile(record):
    revision = record.get("revision")
    require(revision != REVISION, "release_already_deployed")
    require(
        revision in BASELINES and record.get("version") == BASELINES[revision],
        "unsupported_baseline",
    )
    stage.BASELINE, stage.BASELINE_VERSION, stage.BASELINE_SCHEMA = (
        revision,
        BASELINES[revision],
        BASELINE_SCHEMA,
    )
    entries = []
    if stage.BASELINE_VERSION == "v1.4.1":
        entries.append(
            {
                "kind": "fixed",
                "text": "在管理端查看历史告警时，标题和正文中的敏感个人信息会自动隐藏。",
            }
        )
    for name in ("maintenance-inspection-continuity.json", "consultant-knowledge-tasks.json"):
        entries.extend(delivery.read_record(NOTES / name))
    stage.RELEASE_ENTRIES = entries


# Migration 0094 stores the same set of issue IDs in a join table in place
# of a JSON array. Hash the logical set along with all other original columns.
LEGACY_IDS = "coalesce(nullif(issue_ids::jsonb, 'null'::jsonb), '[]'::jsonb)"


def digest_projection(table, projection, before_upgrade):
    if table != "maintenance_agent_digests":
        return projection
    columns = projection.split(",")
    require(columns.count('"issue_ids"') == 1, "unexpected_digest_columns")
    if before_upgrade:
        rows = f"SELECT DISTINCT value::uuid AS issue_id FROM jsonb_array_elements_text({LEGACY_IDS}) AS ids(value)"
    else:
        rows = "SELECT issue_id FROM public.maintenance_digest_issues WHERE digest_id = maintenance_agent_digests.id"
    columns[columns.index('"issue_ids"')] = (
        f"(SELECT coalesce(jsonb_agg(m.issue_id ORDER BY m.issue_id), '[]'::jsonb) FROM ({rows}) m) AS \"issue_ids\""
    )
    return ",".join(columns)


def validate_inventory(r, directory):
    old = delivery.capture_inventory(r, directory)
    # The join table has real UUID foreign keys. Check old JSON against those
    # constraints before the maintenance window, while services are still up.
    incompatible = stage.sql(
        r,
        old[stage.INFRA[0]],
        f"""SELECT count(*) FROM (
            SELECT d.id FROM maintenance_agent_digests d
            CROSS JOIN LATERAL jsonb_array_elements_text({LEGACY_IDS}) AS ids(value)
            LEFT JOIN maintenance_agent_issues i ON i.id = ids.value::uuid
            GROUP BY d.id
            HAVING count(i.id) <> count(*) OR count(DISTINCT ids.value) <> count(DISTINCT i.id)
        ) invalid_digests;""",
    )
    require(incompatible == "0", "unmigratable_digest_members")
    return old


def configure():
    delivery.REVISION, delivery.VERSION = REVISION, VERSION
    delivery.select_profile = select_profile
    delivery.configure()
    stage.SCHEMA = SCHEMA
    stage.RELEASE_TITLE = "巡检提醒、换版复检与顾问知识任务"
    stage.validate_inventory = validate_inventory
    stage.table_snapshot = partial(cutover.table_snapshot, project_columns=digest_projection)


if __name__ == "__main__":
    raise SystemExit(delivery.main(configure))
