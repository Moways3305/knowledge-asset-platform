"""The trust-loop migration preserves existing assets and supports rollback."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_upgrade_preserves_assets_and_roundtrips(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/0076_knowledge_review_loop.py"
    spec = importlib.util.spec_from_file_location("migration_0076", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE users (id TEXT PRIMARY KEY)"))
        connection.execute(
            sa.text("CREATE TABLE knowledge_assets (id TEXT PRIMARY KEY, title TEXT NOT NULL)")
        )
        connection.execute(sa.text("INSERT INTO knowledge_assets VALUES ('old', '历史资料')"))
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.upgrade()
        row = connection.execute(
            sa.text("SELECT title,review_due_at,replacement_asset_id FROM knowledge_assets")
        ).one()
        assert (
            row.title == "历史资料"
            and row.review_due_at is None
            and row.replacement_asset_id is None
        )
        assert "knowledge_corrections" in sa.inspect(connection).get_table_names()
        module.downgrade()
        assert "knowledge_corrections" not in sa.inspect(connection).get_table_names()
        assert (
            connection.execute(sa.text("SELECT title FROM knowledge_assets")).scalar_one()
            == "历史资料"
        )
    engine.dispose()
