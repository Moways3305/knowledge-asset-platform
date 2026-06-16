"""企业微信微盘扫描 Celery 任务（薄包装，loop-local engine）。

- `drive_scan(config_id, record_id=None, trace_id=None)`：worker 模式执行扫描。
  record_id 给定 → 跑既有 running 记录（手动触发的非 eager 分支）；否则按 config 新建记录
  （定时扫描）。自建 loop-local 会话与客户端，不复用全局 engine。
"""

from __future__ import annotations

import uuid

from app.worker.celery_app import celery_app
from app.worker.runtime import run_task


async def _run(maker, config_id: str, record_id: str | None, trace_id: str | None) -> None:
    from app.models.wecom import WecomScanConfig, WecomScanRecord
    from app.services import wecom_scan
    from app.services.desensitization import get_desensitizer
    from app.services.llm_client import get_llm_client
    from app.services.storage import get_storage
    from app.services.wecom_client import get_wecom_drive_client

    async with maker() as session:
        drive = get_wecom_drive_client()
        storage = get_storage()
        llm = get_llm_client()
        desensitizer = get_desensitizer()
        if record_id:
            config = await session.get(WecomScanConfig, uuid.UUID(config_id))
            record = await session.get(WecomScanRecord, uuid.UUID(record_id))
            if config is not None and record is not None:
                await wecom_scan.run_scan(
                    session,
                    config,
                    record,
                    drive=drive,
                    storage=storage,
                    llm=llm,
                    desensitizer=desensitizer,
                    trace_id=trace_id,
                    actor_caller=None,
                )
        else:
            await wecom_scan.scan_config_by_id(
                session,
                uuid.UUID(config_id),
                drive=drive,
                storage=storage,
                llm=llm,
                desensitizer=desensitizer,
                trace_id=trace_id,
            )


@celery_app.task(name="wecom.drive_scan", bind=True)
def drive_scan(
    self, config_id: str, record_id: str | None = None, trace_id: str | None = None
) -> None:
    run_task(lambda maker: _run(maker, config_id, record_id, trace_id))
