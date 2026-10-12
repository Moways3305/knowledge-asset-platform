import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_oauth_migration_preserves_grants_on_downgrade(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/0078_mcp_oauth.py"
    spec = importlib.util.spec_from_file_location("migration_0078", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE agent_whitelist_rules (id TEXT PRIMARY KEY)"))
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.upgrade()
        module.downgrade()
        module.upgrade()
        connection.execute(
            sa.text(
                """INSERT INTO mcp_oauth_records VALUES
            ('grant-id','grant','{}','2099-01-01')"""
            )
        )
        with pytest.raises(RuntimeError):
            module.downgrade()
        assert connection.scalar(sa.text("SELECT count(*) FROM mcp_oauth_records")) == 1
    engine.dispose()
