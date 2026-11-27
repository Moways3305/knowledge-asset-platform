"""Retiring the duplicate executor must preserve private history without replay."""

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine


def test_legacy_tasks_import_with_redaction_and_replay_preserves_new_work():
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "alembic"))
    migration = scripts.get_revision("0098_legacy_agent_sessions").module
    engine = sa.create_engine("sqlite://")
    owner = uuid.uuid4().hex
    now = datetime(2026, 11, 20, tzinfo=timezone.utc)
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE users (id CHAR(32) PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO users (id) VALUES (?)", (owner,))
        with Operations.context(MigrationContext.configure(connection)):
            for revision in ("0095_knowledge_tasks", "0096_ai_workspace", "0097_agent_runtime"):
                scripts.get_revision(revision).module.upgrade()
            legacy = sa.Table("knowledge_agent_tasks", sa.MetaData(), autoload_with=connection)
            # Cross the migration's 200-row page boundary; include active old work.
            records = [
                {
                    "id": uuid.uuid4().hex,
                    "user_id": owner,
                    "role": "consultant",
                    "library_key": "company",
                    "instruction": "检查资料，电话13800138000",
                    "status": "ready" if index % 2 else "checking",
                    "result": {"selected": {"asset_id": "old-private-source"}},
                    "created_at": now,
                }
                for index in range(205)
            ]
            connection.execute(legacy.insert(), records)
            migration.upgrade()
            sessions = sa.Table("ai_workspace_sessions", sa.MetaData(), autoload_with=connection)
            runs = sa.Table("ai_workspace_runs", sa.MetaData(), autoload_with=connection)
            messages = sa.Table("ai_workspace_messages", sa.MetaData(), autoload_with=connection)
            assert connection.scalar(sa.select(sa.func.count()).select_from(sessions)) == 205
            assert connection.scalar(sa.select(sa.func.count()).select_from(runs)) == 205
            assert connection.scalar(sa.select(sa.func.count()).select_from(messages)) == 410
            for row in connection.execute(sa.select(sessions)).mappings():
                assert row["user_id"] == owner and row["role"] == "consultant"
                assert row["agent_key"] == "knowledge-maintenance"
                assert row["active_run_id"] is None
                assert "13800138000" not in row["title"]
            assert set(connection.scalars(sa.select(runs.c.status))) == {"completed", "failed"}
            assert all(not refs for refs in connection.scalars(sa.select(runs.c.source_refs)))
            contents = " ".join(connection.scalars(sa.select(messages.c.content)))
            assert "13800138000" not in contents and "old-private-source" not in contents
            target = records[0]["id"]
            connection.execute(
                sessions.update().where(sessions.c.id == target).values(title="已继续处理的任务")
            )
            connection.execute(
                messages.insert().values(
                    id=uuid.uuid4().hex,
                    session_id=target,
                    run_id=connection.scalar(
                        sa.select(runs.c.id).where(runs.c.session_id == target)
                    ),
                    role="user",
                    content="继续检查新版本",
                    created_at=now,
                )
            )
            migration.downgrade()
            migration.upgrade()
            assert connection.scalar(sa.select(sa.func.count()).select_from(messages)) == 411
            assert connection.scalar(
                sa.select(sessions.c.title).where(sessions.c.id == target)
            ) == ("已继续处理的任务")
            # Original rows remain available for a controlled application rollback.
            assert connection.scalar(sa.select(sa.func.count()).select_from(legacy)) == 205
    engine.dispose()


def _migrate_to(connection, scripts, target, *, downgrade=False):
    """Use Alembic's real revision traversal and bookkeeping in this schema only."""
    # This matches the production env's widened ledger; old revision names exceed
    # Alembic's default VARCHAR(32). Do not import env.py (it opens its own engine).
    connection.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(64) NOT NULL PRIMARY KEY)"
    )
    connection.commit()
    traverse = scripts._downgrade_revs if downgrade else scripts._upgrade_revs
    context = MigrationContext.configure(
        connection,
        opts={
            "fn": lambda current, _: traverse(target, current),
            "transaction_per_migration": True,
        },
    )
    with Operations.context(context):
        with context.begin_transaction():
            context.run_migrations()
    assert context.get_current_revision() == scripts.get_revision(target).revision


def _postgres_history_roundtrip(connection):
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "alembic"))
    head = scripts.get_current_head()
    assert head == "0098_legacy_agent_sessions"
    # Exercise every migration from an empty schema, including all business FK
    # dependencies, rather than substituting metadata.create_all for the baseline.
    _migrate_to(connection, scripts, "0095_knowledge_tasks")
    owner, now = uuid.uuid4(), datetime(2026, 11, 20, tzinfo=timezone.utc)
    users = sa.Table("users", sa.MetaData(), autoload_with=connection)
    connection.execute(
        users.insert().values(
            id=owner,
            name="Synthetic migration owner",
            email=f"{owner.hex}@example.invalid",
            status="active",
            created_at=now,
            updated_at=now,
        )
    )
    legacy = sa.Table("knowledge_agent_tasks", sa.MetaData(), autoload_with=connection)
    statuses = ("queued", "planning", "checking", "ready", "empty", "failed")
    records = [
        {
            "id": uuid.uuid4(),
            "user_id": owner,
            "role": "consultant",
            "library_key": "company",
            "instruction": "检查资料，电话13800138000",
            "status": statuses[index % len(statuses)],
            "claim": uuid.uuid4(),
            "lease_until": now,
            "result": {"selected": {"asset_id": "old-private-source"}},
            "created_at": now,
        }
        for index in range(205)
    ]
    connection.execute(legacy.insert(), records)
    _migrate_to(connection, scripts, "0096_ai_workspace")
    _migrate_to(connection, scripts, "0097_agent_runtime")
    _migrate_to(connection, scripts, "head")

    def reflect(name):
        return sa.Table(name, sa.MetaData(), autoload_with=connection)

    sessions, runs, messages = (
        reflect("ai_workspace_" + name) for name in ("sessions", "runs", "messages")
    )
    assert connection.scalar(sa.select(sa.func.count()).select_from(sessions)) == 205
    assert connection.scalar(sa.select(sa.func.count()).select_from(runs)) == 205
    assert connection.scalar(sa.select(sa.func.count()).select_from(messages)) == 410
    expected_status = {
        row["id"]: "completed" if row["status"] in {"ready", "empty"} else "failed"
        for row in records
    }
    for row in connection.execute(sa.select(runs)).mappings():
        assert row["status"] == expected_status[row["session_id"]]
        assert row["claim"] is None and row["lease_until"] is None
        assert row["next_wake_at"] is None and row["finished_at"] is not None
        assert row["runtime_state"] == {"legacy_task": True}
        assert row["source_refs"] == []
    for row in connection.execute(sa.select(sessions)).mappings():
        assert row["user_id"] == owner and row["role"] == "consultant"
        assert row["agent_key"] == "knowledge-maintenance"
        assert row["active_run_id"] is None
        assert "13800138000" not in row["title"]
    contents = " ".join(connection.scalars(sa.select(messages.c.content)))
    assert "13800138000" not in contents and "old-private-source" not in contents

    # Preserve a user's post-upgrade edits and a new private reply through the
    # complete downgrade to the previous workspace schema, not only 0098's no-op.
    target = records[0]["id"]
    target_run = connection.scalar(sa.select(runs.c.id).where(runs.c.session_id == target))
    reply_id = uuid.uuid4()
    connection.execute(
        sessions.update().where(sessions.c.id == target).values(title="已继续处理的任务")
    )
    connection.execute(
        messages.insert().values(
            id=reply_id,
            session_id=target,
            run_id=target_run,
            role="user",
            content="继续检查新版本",
            created_at=now,
        )
    )
    _migrate_to(connection, scripts, "0096_ai_workspace", downgrade=True)
    old_sessions, old_messages = reflect("ai_workspace_sessions"), reflect("ai_workspace_messages")
    assert "agent_key" not in old_sessions.c and "source_refs" not in old_messages.c
    assert connection.scalar(sa.select(sa.func.count()).select_from(old_messages)) == 411
    assert (
        connection.scalar(sa.select(old_messages.c.content).where(old_messages.c.id == reply_id))
        == "继续检查新版本"
    )
    _migrate_to(connection, scripts, "head")
    sessions, runs, messages = (
        reflect("ai_workspace_" + name) for name in ("sessions", "runs", "messages")
    )
    assert connection.scalar(sa.select(sa.func.count()).select_from(sessions)) == 205
    assert connection.scalar(sa.select(sa.func.count()).select_from(runs)) == 205
    assert connection.scalar(sa.select(sa.func.count()).select_from(messages)) == 411
    assert (
        connection.scalar(sa.select(sessions.c.title).where(sessions.c.id == target))
        == "已继续处理的任务"
    )
    assert set(connection.scalars(sa.select(sessions.c.agent_key))) == {"knowledge-maintenance"}
    assert not connection.scalar(
        sa.select(sa.func.count())
        .select_from(runs)
        .where(runs.c.status.in_(["queued", "running", "waiting", "awaiting_confirmation"]))
    )
    assert not connection.scalar(
        sa.select(sa.func.count())
        .select_from(sessions)
        .where(sessions.c.active_run_id.is_not(None))
    )
    assert connection.scalar(sa.select(sa.func.count()).select_from(legacy)) == 205
    assert (
        connection.scalar(sa.select(sa.func.count()).select_from(users).where(users.c.id == owner))
        == 1
    )


async def test_postgres_full_upgrade_and_0096_history_roundtrip():
    url = os.environ.get("KAP_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("KAP_TEST_POSTGRES_URL is required for PostgreSQL migration verification")
    assert url.startswith("postgresql+asyncpg://")
    schema = "kap_migration98_" + uuid.uuid4().hex
    admin = create_async_engine(url)
    engine = create_async_engine(
        url, connect_args={"server_settings": {"search_path": schema, "statement_timeout": "30000"}}
    )
    try:
        async with admin.begin() as connection:
            await connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        async with engine.connect() as connection:
            await connection.run_sync(_postgres_history_roundtrip)
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()
