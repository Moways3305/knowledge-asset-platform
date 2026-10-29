import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_withdrawal_backfill_requires_unambiguous_audit_and_preserves_rejections(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/0082_withdrawn_review_status.py"
    spec = importlib.util.spec_from_file_location("migration_0082", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE review_tasks (id TEXT PRIMARY KEY, review_type TEXT, status TEXT, review_comment TEXT)"
            )
        )
        connection.execute(
            sa.text(
                "CREATE TABLE audit_events (target_id TEXT, target_type TEXT, log_type TEXT, action TEXT)"
            )
        )
        rows = [
            ("material", "material_to_asset", "rejected"),
            ("company", "project_to_company", "rejected"),
            ("true-rejection", "material_to_asset", "rejected"),
            ("no-audit", "material_to_asset", "rejected"),
            ("ambiguous", "material_to_asset", "rejected"),
            ("pending", "material_to_asset", "pending_reviewer"),
            ("cancelled", "material_to_asset", "cancelled"),
            ("wrong-type", "project_ingest_approval", "rejected"),
        ]
        for identity, review_type, status in rows:
            connection.execute(
                sa.text("INSERT INTO review_tasks VALUES (:id, :type, :status, '原意见')"),
                {"id": identity, "type": review_type, "status": status},
            )
        events = [
            ("material", "review.withdrawn"),
            ("company", "review.company_confirmation_withdrawn"),
            ("true-rejection", "review.rejected"),
            ("ambiguous", "review.withdrawn"),
            ("ambiguous", "review.rejected"),
            ("pending", "review.withdrawn"),
            ("wrong-type", "review.withdrawn"),
        ]
        for identity, action in events:
            connection.execute(
                sa.text(
                    "INSERT INTO audit_events VALUES (:id, 'review_task', 'operation', :action)"
                ),
                {"id": identity, "action": action},
            )
        original_events = connection.execute(
            sa.text("SELECT * FROM audit_events ORDER BY target_id, action")
        ).all()
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        module.upgrade()
        module.upgrade()
        actual = dict(connection.execute(sa.text("SELECT id, status FROM review_tasks")).all())
        expected = {identity: status for identity, _, status in rows}
        expected.update(material="cancelled", company="cancelled")
        assert actual == expected
        assert connection.execute(
            sa.text("SELECT DISTINCT review_comment FROM review_tasks")
        ).all() == [("原意见",)]
        assert (
            connection.execute(
                sa.text("SELECT * FROM audit_events ORDER BY target_id, action")
            ).all()
            == original_events
        )
        module.downgrade()
        assert dict(connection.execute(sa.text("SELECT id, status FROM review_tasks")).all()) == {
            identity: status for identity, _, status in rows
        }
    engine.dispose()
