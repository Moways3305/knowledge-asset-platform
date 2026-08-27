from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import create_engine, inspect


def _migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0068_upload_duplicate_decisions.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0068", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0068_declares_hash_indexes_and_reversible_columns():
    migration = _migration()
    assert migration.down_revision == "0067_domain_event_outbox"
    source = Path(migration.__file__).read_text(encoding="utf-8")
    assert "ix_ingest_tasks_source_hash_status_scope" in source
    assert "ix_asset_versions_file_hash_status" in source
    assert 'drop_column("ingest_tasks", "duplicate_decision")' in source


def test_model_metadata_contains_duplicate_indexes():
    from app.db.base import Base
    from app.models import ingest, knowledge  # noqa: F401

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    ingest_indexes = {index["name"] for index in inspector.get_indexes("ingest_tasks")}
    version_indexes = {index["name"] for index in inspector.get_indexes("knowledge_asset_versions")}
    assert "ix_ingest_tasks_source_hash_status_scope" in ingest_indexes
    assert "ix_asset_versions_file_hash_status" in version_indexes
