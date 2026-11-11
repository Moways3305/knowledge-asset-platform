"""Reuse progress/index migration retains business history and other scan cycles."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_reuse_upgrade_downgrade_preserves_business_rows(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/0086_reuse_scan_batches.py"
    spec = importlib.util.spec_from_file_location("migration_0086", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE knowledge_assets (id TEXT PRIMARY KEY, deleted_at DATETIME, updated_at DATETIME)"
            )
        )
        conn.execute(
            sa.text(
                "CREATE TABLE agent_call_citations (id TEXT PRIMARY KEY, cited_asset_id TEXT, created_at DATETIME, call_id TEXT)"
            )
        )
        conn.execute(
            sa.text("CREATE TABLE audit_events (id TEXT PRIMARY KEY, action TEXT, target_id TEXT)")
        )
        conn.execute(sa.text("CREATE TABLE governance_scan_runs (name TEXT PRIMARY KEY)"))
        conn.execute(sa.text("INSERT INTO knowledge_assets VALUES ('asset', NULL, '2025-01-01')"))
        conn.execute(
            sa.text(
                "INSERT INTO agent_call_citations VALUES ('citation', 'asset', '2025-02-01', 'call')"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO audit_events VALUES ('audit', 'knowledge.upgrade_recommended', 'asset')"
            )
        )
        conn.execute(sa.text("INSERT INTO governance_scan_runs VALUES ('archive'), ('review')"))
        tables = [
            "knowledge_assets",
            "agent_call_citations",
            "audit_events",
            "governance_scan_runs",
        ]
        before = {t: conn.execute(sa.text(f"SELECT * FROM {t}")).all() for t in tables}
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        for _ in range(2):
            module.upgrade()
            assert (
                conn.execute(sa.text("SELECT reuse_scan_checked_at FROM knowledge_assets")).scalar()
                is None
            )
            conn.execute(sa.text("INSERT INTO governance_scan_runs VALUES ('reuse')"))
            module.downgrade()
            assert {t: conn.execute(sa.text(f"SELECT * FROM {t}")).all() for t in tables} == before
    engine.dispose()
