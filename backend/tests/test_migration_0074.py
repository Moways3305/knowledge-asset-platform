"""Release-note migration is reversible and preserves users."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_release_notes_migration(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/0074_release_notes.py"
    spec = importlib.util.spec_from_file_location("migration_0074", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE users (id TEXT PRIMARY KEY)"))
        connection.execute(sa.text("INSERT INTO users VALUES ('existing')"))
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.upgrade()
        assert {"release_notes", "release_note_reads"} <= set(
            sa.inspect(connection).get_table_names()
        )
        module.downgrade()
        assert sa.inspect(connection).get_table_names() == ["users"]
        assert connection.execute(sa.text("SELECT * FROM users")).scalar_one() == "existing"
        module.upgrade()
        assert (
            len(
                sa.inspect(connection).get_pk_constraint("release_note_reads")[
                    "constrained_columns"
                ]
            )
            == 2
        )
    engine.dispose()
