"""Verify 0097/0098 additions without exempting existing workspace data."""

import json
import uuid

import execute_production_cutover as cutover
from prepare_production_release import require

FORMAT = "agent-runtime-migration-v1"
TABLE_KEYS = {
    "ai_workspace_sessions": "session_id",
    "ai_workspace_runs": "run_id",
    "ai_workspace_messages": "message_ids",
}


def identities(imports):
    """Only UUID metadata belongs in the private snapshot/SQL, never source text."""
    require(isinstance(imports, list), "invalid_agent_import_manifest")
    rows = []
    seen = set()
    for value in imports:
        identity = uuid.UUID(value)
        require(str(identity) == value and value not in seen, "invalid_agent_import_manifest")
        seen.add(value)
        rows.append(
            {
                "session_id": value,
                "run_id": str(uuid.uuid5(identity, "workspace-legacy-run")),
                "user_id": str(uuid.uuid5(identity, "workspace-legacy-user")),
                "assistant_id": str(uuid.uuid5(identity, "workspace-legacy-assistant")),
            }
        )
    return rows


def expected_cte(rows):
    names = "session_id,run_id,user_id,assistant_id"
    if not rows:
        return f"WITH expected({names}) AS (SELECT NULL::uuid,NULL::uuid,NULL::uuid,NULL::uuid WHERE false) "
    values = ",".join(
        "(" + ",".join(cutover.literal(row[key]) + "::uuid" for key in names.split(",")) + ")"
        for row in rows
    )
    return f"WITH expected({names}) AS (VALUES {values}) "


def validate_imports(runner, old, rows):
    # Missing rows, unexpected owner/context, replayable state, or changed UUID5
    # identities must fail before a worker or public endpoint is opened.
    query = (
        expected_cte(rows)
        + """
SELECT count(*) FROM expected e
LEFT JOIN public.knowledge_agent_tasks t ON t.id=e.session_id
LEFT JOIN public.ai_workspace_sessions s ON s.id=e.session_id
LEFT JOIN public.ai_workspace_runs r ON r.id=e.run_id
LEFT JOIN public.ai_workspace_messages u ON u.id=e.user_id
LEFT JOIN public.ai_workspace_messages a ON a.id=e.assistant_id
WHERE t.id IS NULL OR s.id IS NULL OR r.id IS NULL OR u.id IS NULL OR a.id IS NULL
OR s.user_id IS DISTINCT FROM t.user_id OR s.role IS DISTINCT FROM t.role
OR s.agent_key IS DISTINCT FROM 'knowledge-maintenance'
OR s.active_run_id IS NOT NULL OR s.event_seq IS DISTINCT FROM 0
OR s.created_at IS DISTINCT FROM t.created_at OR s.updated_at IS DISTINCT FROM t.created_at
OR r.session_id IS DISTINCT FROM t.id OR r.context_key IS DISTINCT FROM t.library_key
OR r.model_ref IS DISTINCT FROM 'system_default'
OR r.status IS DISTINCT FROM CASE WHEN t.status IN ('ready','empty') THEN 'completed' ELSE 'failed' END
OR r.error_code IS DISTINCT FROM CASE WHEN t.status IN ('ready','empty') THEN NULL ELSE 'interrupted' END
OR r.claim IS NOT NULL OR r.lease_until IS NOT NULL OR r.next_wake_at IS NOT NULL
OR r.retry_of IS NOT NULL OR r.created_at IS DISTINCT FROM t.created_at
OR r.finished_at IS DISTINCT FROM t.created_at OR r.step_count IS DISTINCT FROM 0
OR r.max_steps IS DISTINCT FROM 24
OR r.source_refs::jsonb IS DISTINCT FROM '[]'::jsonb
OR r.runtime_state::jsonb IS DISTINCT FROM '{"legacy_task":true}'::jsonb
OR u.session_id IS DISTINCT FROM t.id OR a.session_id IS DISTINCT FROM t.id
OR u.run_id IS DISTINCT FROM r.id OR a.run_id IS DISTINCT FROM r.id
OR u.role IS DISTINCT FROM 'user' OR a.role IS DISTINCT FROM 'assistant'
OR u.created_at IS DISTINCT FROM t.created_at
OR a.created_at IS DISTINCT FROM t.created_at + interval '1 microsecond'
OR u.source_refs::jsonb IS DISTINCT FROM '[]'::jsonb
OR a.source_refs::jsonb IS DISTINCT FROM '[]'::jsonb;
"""
    )
    require(cutover.sql(runner, old, query) == "0", "legacy_agent_import_mismatch")
    require(
        cutover.sql(
            runner,
            old,
            "SELECT count(*) FROM public.knowledge_agent_tasks t "
            "JOIN public.ai_workspace_sessions s ON s.id=t.id "
            "WHERE s.agent_key IS DISTINCT FROM 'knowledge-maintenance';",
        )
        == "0",
        "legacy_agent_session_identity_mismatch",
    )
    for name in ("ai_workspace_messages", "ai_workspace_artifacts"):
        require(
            cutover.sql(
                runner,
                old,
                f"SELECT count(*) FROM public.{name} c LEFT JOIN public.ai_workspace_runs r "
                "ON r.id=c.run_id WHERE r.id IS NULL OR c.source_refs::jsonb IS DISTINCT FROM r.source_refs::jsonb;",
            )
            == "0",
            "agent_provenance_backfill_mismatch",
        )
    require(
        cutover.sql(runner, old, "SELECT count(*) FROM public.ai_workspace_actions;") == "0",
        "unexpected_agent_action_before_opening",
    )


def table_snapshot(runner, old, columns=None):
    if columns is None:
        imports = json.loads(
            cutover.sql(
                runner,
                old,
                "SELECT coalesce(json_agg(t.id ORDER BY t.id),'[]'::json) "
                "FROM public.knowledge_agent_tasks t LEFT JOIN public.ai_workspace_sessions s "
                "ON s.id=t.id WHERE s.id IS NULL;",
            )
        )
        rows = identities(imports)
        # A future deterministic import ID is only safe to exclude if it did not
        # exist before migration; otherwise a replaced original could be hidden.
        require(
            cutover.sql(
                runner,
                old,
                expected_cte(rows) + "SELECT count(*) FROM expected e WHERE EXISTS "
                "(SELECT 1 FROM public.ai_workspace_runs r WHERE r.id=e.run_id) "
                "OR EXISTS (SELECT 1 FROM public.ai_workspace_messages m "
                "WHERE m.id IN (e.user_id,e.assistant_id));",
            )
            == "0",
            "legacy_agent_import_identity_conflict",
        )
        frozen, before = cutover.table_snapshot(runner, old)
        require(set(TABLE_KEYS).issubset(frozen), "workspace_baseline_tables_missing")
        return {"format": FORMAT, "tables": frozen, "imports": imports}, before
    require(
        isinstance(columns, dict)
        and columns.get("format") == FORMAT
        and isinstance(columns.get("tables"), dict)
        and set(TABLE_KEYS).issubset(columns["tables"]),
        "invalid_agent_import_manifest",
    )
    rows = identities(columns.get("imports"))
    validate_imports(runner, old, rows)

    def unchanged_rows(name):
        if name not in TABLE_KEYS or not rows:
            return "true"
        keys = (
            ("user_id", "assistant_id") if name == "ai_workspace_messages" else (TABLE_KEYS[name],)
        )
        expected = [cutover.literal(row[key]) + "::uuid" for row in rows for key in keys]
        return "id NOT IN (" + ",".join(expected) + ")"

    _, after = cutover.table_snapshot(runner, old, columns["tables"], row_filter=unchanged_rows)
    print(f"历史 Agent 任务迁移校验通过：{len(rows)} 条；原有业务数据继续逐表核对。", flush=True)
    return columns, after


def redaction_check_code(manifest_path="/migration-check/database-before-private.json"):
    """Run inside the candidate image after Alembic, before opening any traffic."""
    # SQL parameter expansion is bounded to 200 IDs. Neither successful output
    # nor exceptions include the legacy instruction or any persisted new text.
    # The manifest is mounted read-only: never put a large UUID list in argv.
    return (
        "MANIFEST_PATH = "
        + repr(manifest_path)
        + "\nFORMAT = "
        + repr(FORMAT)
        + "\n"
        + _REDACTION_CHECK
    )


_REDACTION_CHECK = r'''
import asyncio
import json
import uuid
from pathlib import Path
from sqlalchemy import bindparam, text
from app.core.personal_information import redact_personal_information
from app.db.session import get_engine

async def verify(connection, import_ids):
    query = text("""
                SELECT t.id, t.instruction, t.status, s.title, r.instruction AS imported_instruction,
                       u.content AS user_content, a.content AS assistant_content
                FROM knowledge_agent_tasks t JOIN ai_workspace_sessions s ON s.id=t.id
                JOIN ai_workspace_runs r ON r.session_id=s.id
                JOIN ai_workspace_messages u ON u.run_id=r.id AND u.role='user'
                JOIN ai_workspace_messages a ON a.run_id=r.id AND a.role='assistant'
                WHERE CAST(t.id AS text) IN :ids
    """).bindparams(bindparam("ids", expanding=True))
    for start in range(0, len(import_ids), 200):
        ids = import_ids[start:start + 200]
        rows = (await connection.execute(query, {"ids": ids})).mappings().all()
        if len(rows) != len(ids) or {str(row['id']) for row in rows} != set(ids):
            raise RuntimeError('agent_import_count_mismatch')
        for row in rows:
            expected = redact_personal_information(row['instruction']) or '历史资料查找任务'
            response = (
                '历史资料查找任务已迁入本会话。原结果未重新核验，请继续交代需要查找或维护的内容。'
                if row['status'] in {'ready', 'empty'} else
                '历史任务未完成，未自动重新执行。请继续说明当前目标后重新处理。'
            )
            if (row['title'] != expected[:48] or row['imported_instruction'] != expected
                    or row['user_content'] != expected or row['assistant_content'] != response):
                raise RuntimeError('agent_import_redaction_mismatch')

async def check():
    engine = get_engine()
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            await verify(connection, IMPORT_IDS)
    finally:
        await engine.dispose()

try:
    manifest = json.loads(Path(MANIFEST_PATH).read_text(encoding='utf-8'))['columns']
    if manifest.get('format') != FORMAT or not isinstance(manifest.get('imports'), list):
        raise RuntimeError('invalid_agent_import_manifest')
    IMPORT_IDS = manifest['imports']
    if (len(set(IMPORT_IDS)) != len(IMPORT_IDS)
            or any(str(uuid.UUID(value)) != value for value in IMPORT_IDS)):
        raise RuntimeError('invalid_agent_import_manifest')
    asyncio.run(check())
except BaseException:
    raise SystemExit('agent_runtime_redaction_verification_failed') from None
print('历史 Agent 任务的标题、指令与消息脱敏校验通过。', flush=True)
'''
