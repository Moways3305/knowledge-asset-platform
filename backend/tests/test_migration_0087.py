"""Cursor rollback retains requests, grants and unrelated scan intentions."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_access_scan_index_upgrade_downgrade_preserves_facts(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/0087_original_access_scan.py"
    spec = importlib.util.spec_from_file_location("migration_0087", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE original_access_requests (id TEXT PRIMARY KEY, status TEXT, created_at DATETIME, review_note TEXT)"
            )
        )
        conn.execute(sa.text("CREATE TABLE access_grants (id TEXT PRIMARY KEY, status TEXT)"))
        conn.execute(sa.text("CREATE TABLE governance_scan_runs (name TEXT PRIMARY KEY)"))
        conn.execute(
            sa.text(
                "INSERT INTO original_access_requests VALUES ('request', 'pending', '2026-01-01', 'keep')"
            )
        )
        conn.execute(sa.text("INSERT INTO access_grants VALUES ('grant', 'active')"))
        conn.execute(
            sa.text("INSERT INTO governance_scan_runs VALUES ('archive'), ('review'), ('reuse')")
        )
        tables = ["original_access_requests", "access_grants", "governance_scan_runs"]
        before = {t: conn.execute(sa.text(f"SELECT * FROM {t}")).all() for t in tables}
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        for _ in range(2):
            module.upgrade()
            conn.execute(sa.text("INSERT INTO governance_scan_runs VALUES ('original_access')"))
            module.downgrade()
            assert {t: conn.execute(sa.text(f"SELECT * FROM {t}")).all() for t in tables} == before
    engine.dispose()
