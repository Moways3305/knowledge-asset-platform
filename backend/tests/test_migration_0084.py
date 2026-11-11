"""Delivery leases are additive, preserve existing notification facts, and reversible."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_notification_leases_preserve_rows_on_upgrade_and_downgrade(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/0084_notification_delivery_lease.py"
    spec = importlib.util.spec_from_file_location("migration_0084", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        for table in ("business_notifications", "notification_records"):
            connection.execute(sa.text(f"CREATE TABLE {table} (id TEXT PRIMARY KEY)"))
            connection.execute(sa.text(f"INSERT INTO {table} VALUES ('existing')"))
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.upgrade()
        for table in ("business_notifications", "notification_records"):
            assert tuple(connection.execute(sa.text(f"SELECT * FROM {table}")).one()) == (
                "existing",
                None,
                None,
                None,
            )
        module.downgrade()
        for table in ("business_notifications", "notification_records"):
            assert tuple(connection.execute(sa.text(f"SELECT * FROM {table}")).one()) == (
                "existing",
            )
    engine.dispose()
