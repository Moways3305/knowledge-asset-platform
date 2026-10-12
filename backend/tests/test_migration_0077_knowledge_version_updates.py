import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_version_update_migration_preserves_old_data_and_refuses_loss(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/0077_knowledge_version_updates.py"
    spec = importlib.util.spec_from_file_location("migration_0077", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        for table in ("knowledge_assets", "knowledge_asset_versions"):
            connection.execute(sa.text(f"CREATE TABLE {table} (id TEXT PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE ingest_tasks (id TEXT PRIMARY KEY, status TEXT)"))
        connection.execute(sa.text("INSERT INTO ingest_tasks VALUES ('old','completed')"))
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.upgrade()
        assert connection.execute(
            sa.text("SELECT status,update_of_asset_id FROM ingest_tasks")
        ).one() == ("completed", None)
        module.downgrade()
        assert "update_of_asset_id" not in {
            x["name"] for x in sa.inspect(connection).get_columns("ingest_tasks")
        }
        module.upgrade()
        connection.execute(sa.text("UPDATE ingest_tasks SET update_of_asset_id='source'"))
        with pytest.raises(RuntimeError):
            module.downgrade()
    engine.dispose()
