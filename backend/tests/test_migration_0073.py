"""Lease migration preserves existing rows and is reversibly additive."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_lease_upgrade_and_downgrade(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/0073_parse_reconcile_lease.py"
    spec = importlib.util.spec_from_file_location("migration_0073", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE knowledge_asset_versions (id TEXT PRIMARY KEY)"))
        connection.execute(sa.text("INSERT INTO knowledge_asset_versions VALUES ('existing')"))
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.upgrade()
        row = connection.execute(sa.text("SELECT * FROM knowledge_asset_versions")).one()
        assert tuple(row) == ("existing", None, None)
        module.downgrade()
        assert connection.execute(sa.text("SELECT * FROM knowledge_asset_versions")).one() == (
            "existing",
        )
    engine.dispose()
