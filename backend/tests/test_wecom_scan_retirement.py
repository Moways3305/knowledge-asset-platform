"""Retirement closes every entry point while preserving independent integrations and data."""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.models.ingest import IngestTask
from app.models.wecom import WecomScanConfig, WecomScanRecord
from app.seed.dev_seed import USER_ADMIN_ONLY, USER_CONSULTANT
from app.worker.tasks.retired import _finish_scan, retire_drive_scan


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "configs"),
        ("POST", "configs"),
        ("PATCH", "configs/00000000-0000-0000-0000-000000000001"),
        ("POST", "configs/00000000-0000-0000-0000-000000000001/scan"),
        ("GET", "configs/00000000-0000-0000-0000-000000000001/records"),
        ("GET", "project-options"),
        ("GET", "owner-options"),
    ],
)
async def test_retired_scan_endpoints_are_absent_even_for_admin(client, method, path):
    response = await client.request(
        method,
        f"/api/v1/admin/wecom-scan/{path}",
        headers={"X-Dev-User-Id": str(USER_ADMIN_ONLY)},
    )
    assert response.status_code == 404


async def test_queued_scan_only_finalizes_its_running_record(db_session):
    config = WecomScanConfig(
        name="Historical scan",
        directory_path="legacy-space",
        scope_type="personal",
        created_by=USER_CONSULTANT,
    )
    db_session.add(config)
    await db_session.flush()
    record = WecomScanRecord(config_id=config.id, scan_status="running", new_count=2)
    completed = WecomScanRecord(config_id=config.id, scan_status="completed", new_count=3)
    db_session.add_all([record, completed])
    await db_session.commit()
    original_count = await db_session.scalar(select(func.count()).select_from(IngestTask))
    record_id, config_id, completed_id = record.id, config.id, completed.id
    await db_session.rollback()
    maker = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    # An unrelated message cannot finalize another configuration's record.
    await _finish_scan(maker, str(uuid.uuid4()), str(record_id))
    await _finish_scan(maker, str(config_id), str(record_id))
    await db_session.refresh(record)
    assert record.scan_status == "failed"
    assert record.error_type == "feature_retired"
    assert record.new_count == 2
    completed_at = record.scan_completed_at
    await db_session.rollback()
    await _finish_scan(maker, str(config_id), str(record_id))
    await _finish_scan(maker, str(config_id), str(completed_id))
    await db_session.refresh(record)
    await db_session.refresh(completed)
    assert record.scan_completed_at == completed_at
    assert completed.scan_status == "completed" and completed.new_count == 3
    assert await db_session.scalar(select(func.count()).select_from(IngestTask)) == original_count


def test_old_scheduled_message_creates_no_scan_or_external_work(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Retired scheduled messages must not start database or external work")

    monkeypatch.setattr("app.worker.tasks.retired.run_task", unexpected)
    retire_drive_scan.run(str(uuid.uuid4()))


@pytest.mark.parametrize("setting", ["WECOM_API_BASE_URL", "WECOM_DRIVE_BASE_URL"])
def test_existing_api_host_configuration_still_serves_oauth_and_notifications(monkeypatch, setting):
    from app.services import wecom_client, wecom_notification

    monkeypatch.delenv("WECOM_API_BASE_URL", raising=False)
    monkeypatch.delenv("WECOM_DRIVE_BASE_URL", raising=False)
    monkeypatch.setenv(setting, "https://example.invalid")
    settings = Settings(
        _env_file=None,
        wecom_corp_id="synthetic-corp",
        wecom_app_secret="synthetic-secret",
        wecom_agent_id="1",
        wecom_notify_enabled=True,
    )
    monkeypatch.setattr(wecom_client, "get_settings", lambda: settings)
    monkeypatch.setattr(wecom_notification, "get_settings", lambda: settings)
    assert wecom_client.get_wecom_oauth_client()._base == "https://example.invalid"
    assert wecom_notification.get_wecom_notification_sender()._base == "https://example.invalid"


def test_canonical_api_host_has_precedence_over_legacy_alias(monkeypatch):
    monkeypatch.setenv("WECOM_DRIVE_BASE_URL", "https://old.invalid")
    monkeypatch.setenv("WECOM_API_BASE_URL", "https://current.invalid")
    assert Settings(_env_file=None).wecom_api_base_url == "https://current.invalid"
