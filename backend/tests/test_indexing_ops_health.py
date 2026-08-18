from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import select

from app.db.utils import utc_now
from app.models.indexing_job import IndexingOperationJob, IndexingOpsSnapshot, OpsRuntimeHeartbeat
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.seed.dev_seed import USER_ADMIN_ONLY, USER_CONSULTANT
from app.services import error_catalog, indexing_health
from app.worker import beat_scheduler
from app.worker.beat_scheduler import record_beat_heartbeat_from_scheduler
from app.worker.tasks import ops_health
from app.worker.tasks.ops_health import worker_heartbeat


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


def test_diagnostic_categories_are_allowlisted_and_unknown_fails_closed():
    assert error_catalog.diagnostic("weknora_default_model_not_configured") == (
        "configuration",
        "配置问题",
    )
    assert error_catalog.diagnostic("weknora_down") == ("external_service", "外部服务")
    assert error_catalog.diagnostic("source_file_unreadable") == (
        "source_content",
        "文件或内容",
    )
    assert error_catalog.diagnostic("SECRET-LIKE upstream payload") == ("unknown", "待确认")
    assert error_catalog.targeted_retry_eligible("weknora_down") is True
    assert error_catalog.targeted_retry_eligible("SECRET-LIKE upstream payload") is False


async def test_snapshot_is_hourly_idempotent_and_contains_real_queue_metrics(db_session):
    now = utc_now().replace(minute=25, second=0, microsecond=0)
    db_session.add(
        IndexingOperationJob(
            operation_type="retry_index",
            status="queued",
            requested_by_user_id=USER_ADMIN_ONLY,
            requested_at=now - timedelta(minutes=12),
        )
    )
    await db_session.commit()

    first = await indexing_health.capture_snapshot(db_session, observed_at=now)
    second = await indexing_health.capture_snapshot(
        db_session, observed_at=now + timedelta(minutes=20)
    )
    assert first.id == second.id
    assert second.queued_jobs == 1
    assert second.oldest_queued_seconds == 1920
    rows = list((await db_session.execute(select(IndexingOpsSnapshot))).scalars())
    assert len(rows) == 1


async def test_parse_failed_visibility_excludes_deleted_and_inactive_versions(db_session):
    active_asset_id = uuid.uuid4()
    active_version_id = uuid.uuid4()
    deleted_asset_id = uuid.uuid4()
    deleted_version_id = uuid.uuid4()
    inactive_asset_id = uuid.uuid4()
    inactive_version_id = uuid.uuid4()
    for asset_id, version_id, asset_status, version_status in (
        (active_asset_id, active_version_id, "active", "active"),
        (deleted_asset_id, deleted_version_id, "deleted", "active"),
        (inactive_asset_id, inactive_version_id, "active", "superseded"),
    ):
        db_session.add(
            KnowledgeAsset(
                id=asset_id,
                title="安全聚合测试",
                scope="personal",
                zone="asset",
                asset_type="methodology",
                owner_user_id=USER_CONSULTANT,
                current_version_id=version_id,
                visibility="private",
                confidentiality_level="L2",
                ai_access_level="A2",
                asset_status=asset_status,
            )
        )
        db_session.add(
            KnowledgeAssetVersion(
                id=version_id,
                asset_id=asset_id,
                version_no="v1",
                version_status=version_status,
                created_by=USER_CONSULTANT,
                index_status="indexed",
                weknora_doc_id=f"server-only-{asset_id}",
                weknora_parse_status="failed",
            )
        )
    await db_session.commit()

    counts = await indexing_health.indexing_counts(db_session)
    assert counts["parse_failed"] == 1
    assert counts["index_failed"] == 0

    snapshot = await indexing_health.capture_snapshot(db_session, observed_at=utc_now())
    assert snapshot.parse_failed == 1
    health = await indexing_health.get_health(db_session, now=utc_now())
    assert health.trend_points[-1].parse_failed == 1


async def test_health_separates_submission_and_parse_interruptions(db_session):
    now = utc_now()
    for index, code in enumerate(("index_submission_interrupted", "index_interrupted")):
        asset_id = uuid.uuid4()
        version_id = uuid.uuid4()
        db_session.add(
            KnowledgeAsset(
                id=asset_id,
                title=f"safe interruption {index}",
                scope="personal",
                zone="asset",
                asset_type="methodology",
                owner_user_id=USER_CONSULTANT,
                current_version_id=version_id,
                confidentiality_level="L2",
                asset_status="active",
            )
        )
        db_session.add(
            KnowledgeAssetVersion(
                id=version_id,
                asset_id=asset_id,
                version_no="v1",
                version_status="active",
                created_by=USER_CONSULTANT,
                index_status="index_failed",
                index_error_code=code,
                weknora_doc_id="server-only" if code == "index_interrupted" else None,
                weknora_parse_status="processing" if code == "index_interrupted" else None,
            )
        )
    await db_session.commit()

    counts = await indexing_health.indexing_counts(db_session)
    assert counts["submission_interrupted"] == 1
    assert counts["parse_stalled"] == 1
    snapshot = await indexing_health.capture_snapshot(db_session, observed_at=now)
    assert snapshot.submission_interrupted == 1
    assert snapshot.parse_stalled == 1


async def test_health_reports_real_healthy_stale_and_insufficient_states(db_session, monkeypatch):
    now = utc_now()
    monkeypatch.setattr(
        indexing_health,
        "get_settings",
        lambda: SimpleNamespace(celery_task_always_eager=False),
    )
    await indexing_health.record_heartbeat(
        db_session, "worker", observed_at=now - timedelta(seconds=30)
    )
    await indexing_health.record_heartbeat(
        db_session, "beat", observed_at=now - timedelta(minutes=10)
    )
    await indexing_health.capture_snapshot(db_session, observed_at=now - timedelta(hours=1))

    health = await indexing_health.get_health(db_session, window_hours=24, now=now)
    assert health.insufficient_data is True
    assert health.message == "正在积累运维数据"
    assert health.worker.status == "healthy"
    assert health.beat.status == "stale"
    assert len(health.trend_points) == 1

    await indexing_health.capture_snapshot(db_session, observed_at=now)
    enough = await indexing_health.get_health(db_session, window_hours=24, now=now)
    assert enough.insufficient_data is False
    assert enough.message == "最近运行趋势已更新"


async def test_eager_mode_never_claims_worker_or_beat_online(db_session, monkeypatch):
    now = utc_now()
    await indexing_health.record_heartbeat(db_session, "worker", observed_at=now)
    await indexing_health.record_heartbeat(db_session, "beat", observed_at=now)
    monkeypatch.setattr(
        indexing_health,
        "get_settings",
        lambda: SimpleNamespace(celery_task_always_eager=True),
    )
    health = await indexing_health.get_health(db_session, now=now)
    assert health.worker.status == health.beat.status == "unknown"
    assert health.worker.last_heartbeat_at is None
    assert "不代表" in health.worker.message
    assert worker_heartbeat() == "eager_unknown"
    assert record_beat_heartbeat_from_scheduler() is False


def test_runtime_heartbeat_paths_write_only_outside_eager_mode(monkeypatch):
    calls: list[str] = []
    settings = SimpleNamespace(celery_task_always_eager=False)

    monkeypatch.setattr(ops_health, "get_settings", lambda: settings)
    monkeypatch.setattr(ops_health, "run_task", lambda _task, label: calls.append(label))
    monkeypatch.setattr(beat_scheduler, "get_settings", lambda: settings)
    monkeypatch.setattr(beat_scheduler, "run_task", lambda _task, label: calls.append(label))

    assert worker_heartbeat() == "recorded"
    assert record_beat_heartbeat_from_scheduler() is True
    assert calls == ["ops.worker_heartbeat", "ops.beat_heartbeat"]


async def test_health_api_window_permission_and_safe_shape(client, db_session):
    await indexing_health.capture_snapshot(db_session, observed_at=utc_now())
    response = await client.get(
        "/admin/ops/indexing/health?window_hours=24", headers=_hdr(USER_ADMIN_ONLY)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["window_hours"] == 24
    assert body["worker"]["status"] == "unknown"
    assert body["beat"]["status"] == "unknown"
    assert "storage_ref" not in response.text
    assert "weknora" not in response.text.lower()
    denied = await client.get("/admin/ops/indexing/health", headers=_hdr(USER_CONSULTANT))
    assert denied.status_code == 403


async def test_record_heartbeat_rejects_unapproved_component(db_session):
    try:
        await indexing_health.record_heartbeat(db_session, "SECRET-worker-name")
    except ValueError as exc:
        assert str(exc) == "unsupported heartbeat component"
    else:
        raise AssertionError("unapproved component was accepted")
    assert (await db_session.get(OpsRuntimeHeartbeat, "SECRET-worker-name")) is None
