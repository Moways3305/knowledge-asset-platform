"""Celery 应用。

broker / result backend 缺省回退到 `settings.redis_url`；`task_always_eager` 来自
`settings.celery_task_always_eager`（默认 True，便于本地/测试无 worker 运行）。

任务模块在 `app/worker/tasks/*`，通过 `include` 注册。每个任务自建 async DB 会话，
**绝不**复用 FastAPI 请求会话。
"""

from __future__ import annotations

from celery import Celery
from celery.signals import setup_logging

from app.core.config import get_settings


@setup_logging.connect
def _configure_worker_logging(**_: object) -> None:
    """worker / beat 进程启动时装配 JSON 结构化日志（与 worker_hijack_root_logger=False 配合，
    避免 Celery 覆盖 root logger）。仅在 Celery 真正初始化日志时触发，不影响普通 import / 测试。"""
    from app.core.logging import configure_logging

    configure_logging()


def _make_celery() -> Celery:
    s = get_settings()
    broker = s.celery_broker_url or s.redis_url
    backend = s.celery_result_backend or s.redis_url
    app = Celery(
        "knowledge_asset_platform",
        broker=broker,
        backend=backend,
        include=[
            "app.worker.tasks.ingest",
            "app.worker.tasks.parse",
            "app.worker.tasks.lifecycle",
            "app.worker.tasks.upgrade",
            "app.worker.tasks.wecom",
            "app.worker.tasks.notifications",
            "app.worker.tasks.original_access",
            "app.worker.tasks.indexing",
            "app.worker.tasks.ops_alerts",
            "app.worker.tasks.ops_health",
        ],
    )
    app.conf.update(
        task_always_eager=s.celery_task_always_eager,
        task_eager_propagates=True,
        task_acks_late=True,
        worker_hijack_root_logger=False,
        timezone="UTC",
        enable_utc=True,
        beat_scheduler="app.worker.beat_scheduler:DatabaseHeartbeatScheduler",
        # 定时调度（celery beat）：扫描类作业按日触发；实际由 worker+beat 驱动，
        # 测试直接调用 service 层，不依赖 beat。
        beat_schedule={
            "weknora-parse-reconcile": {
                "task": "weknora.parse_reconcile",
                "schedule": 300.0,  # 每 5 分钟对账解析状态
            },
            "lifecycle-archive-scan": {
                "task": "lifecycle.archive_scan",
                "schedule": 86400.0,  # 每日扫描归档预警/候选
            },
            "reuse-upgrade-scan": {
                "task": "reuse.upgrade_scan",
                "schedule": 86400.0,  # 每日跨项目复用统计 + 升格推荐
            },
            "notifications-dispatch": {
                "task": "notifications.dispatch_pending",
                "schedule": 120.0,  # 每 2 分钟下发待发 wecom 通知
            },
            "original-access-auto-approve": {
                "task": "access.auto_approve_timed_out",
                "schedule": 1800.0,  # 每 30 分钟扫描超时 pending 原文申请
            },
            "ops-alerts-scan": {
                "task": "ops.alerts_scan",
                "schedule": 600.0,  # 每 10 分钟检查运维告警信号（超阈值经通知链路告警）
            },
            "ops-worker-heartbeat": {
                "task": "ops.worker_heartbeat",
                "schedule": 60.0,
            },
            "ops-indexing-health-snapshot": {
                "task": "ops.indexing_health_snapshot",
                "schedule": 3600.0,
            },
        },
    )
    return app


celery_app = _make_celery()
