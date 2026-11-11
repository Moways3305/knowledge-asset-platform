"""Drain already-published messages for retired features without external I/O.

No API or scheduler publishes these tasks. Keep the legacy task name during
upgrades so queued scans cannot import files or leave their record running.
"""

import uuid

from sqlalchemy import update

from app.db.utils import utc_now
from app.models.wecom import WecomScanRecord
from app.worker.celery_app import celery_app
from app.worker.runtime import run_task


async def _finish_scan(maker, config_id: str, record_id: str) -> None:
    async with maker() as session:
        await session.execute(
            update(WecomScanRecord)
            .where(
                WecomScanRecord.id == uuid.UUID(record_id),
                WecomScanRecord.config_id == uuid.UUID(config_id),
                WecomScanRecord.scan_status == "running",
            )
            .values(
                scan_status="failed",
                scan_completed_at=utc_now(),
                error_type="feature_retired",
                error_message="微盘扫描功能已移除，未继续扫描或导入文件。",
            )
        )
        await session.commit()


@celery_app.task(name="wecom.drive_scan", bind=True)
def retire_drive_scan(
    self, config_id: str, record_id: str | None = None, trace_id: str | None = None
) -> None:
    if record_id is not None:
        run_task(
            lambda maker: _finish_scan(maker, config_id, record_id),
            label="wecom.drive_scan",
            trace_id=trace_id,
        )
