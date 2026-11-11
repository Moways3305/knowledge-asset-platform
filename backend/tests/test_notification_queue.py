"""Real broker publication, legacy messages and bounded deployment consumers."""

from pathlib import Path
from queue import Empty
from uuid import uuid4

import pytest
import yaml
from celery import current_app
from celery.beat import ScheduleEntry, Scheduler
from pydantic import ValidationError

from app.core.config import Settings
from app.worker import celery_app as worker
from app.worker.tasks.notifications import dispatch_pending


@pytest.mark.parametrize("name", ["default", "ocr", "parse", "", " ", "notifications,default"])
def test_notification_queue_must_be_distinct_and_single(name):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, celery_notification_queue=name)


@pytest.mark.parametrize("source", ["direct", "beat", "retry", "legacy"])
def test_publish_with_real_router_and_keep_legacy_deliveries_consumable(monkeypatch, source):
    suffix = uuid4().hex
    settings = Settings(
        _env_file=None,
        celery_broker_url="memory://",
        celery_result_backend="cache+memory://",
        celery_task_always_eager=False,
        celery_default_queue="ordinary-" + suffix,
        celery_notification_queue="notify-" + suffix,
    )
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    previous = current_app._get_current_object()
    app = worker._make_celery()
    previous.set_current()
    task = app.tasks[dispatch_pending.name]
    with app.connection_for_write() as connection:
        normal = connection.SimpleQueue(settings.celery_default_queue)
        notify = connection.SimpleQueue(settings.celery_notification_queue)
        try:
            if source == "beat":
                entry = ScheduleEntry(
                    name="notifications-dispatch",
                    app=app,
                    **app.conf.beat_schedule["notifications-dispatch"],
                )
                Scheduler(app=app, lazy=True).apply_async(entry, advance=False)
            elif source == "retry":
                task.push_request(
                    called_directly=False,
                    id=str(uuid4()),
                    retries=0,
                    args=(),
                    kwargs={},
                    delivery_info={"routing_key": settings.celery_notification_queue},
                )
                try:
                    task.retry(countdown=0, throw=False)
                finally:
                    task.pop_request()
            elif source == "legacy":
                task.apply_async(queue=settings.celery_default_queue)
            else:
                task.delay()
            target, empty = (normal, notify) if source == "legacy" else (notify, normal)
            message = target.get(block=False)
            assert message.headers["task"] == "notifications.dispatch_pending"
            message.ack()
            with pytest.raises(Empty):
                empty.get(block=False)
            for name in (
                "domain_events.dispatch_pending",
                "ops.worker_heartbeat",
                "ingest.recover_orphans",
                "indexing.recover_interrupted_jobs",
            ):
                app.send_task(name)
                message = normal.get(block=False)
                assert message.headers["task"] == name
                message.ack()
            with pytest.raises(Empty):
                notify.get(block=False)
        finally:
            normal.close()
            notify.close()
            app.close()


def test_notification_consumer_and_producers_match_without_adding_total_resources():
    root = Path(__file__).resolve().parents[2]
    services = yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))["services"]
    consumer = services["notification_worker"]
    assert "--queues=notifications" in consumer["command"]
    assert "--concurrency=1" in consumer["command"]
    assert "--prefetch-multiplier=1" in consumer["command"]
    assert "--destination=notifications@$$HOSTNAME" in consumer["healthcheck"]["test"][1]
    assert "--destination=default@$$HOSTNAME" in services["worker"]["healthcheck"]["test"][1]
    assert consumer["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert not consumer.get("ports") and not consumer.get("volumes")
    assert consumer["stop_grace_period"] == services["worker"]["stop_grace_period"] == "150s"
    limits = [
        services[n]["deploy"]["resources"]["limits"]
        for n in ("worker", "parse_worker", "notification_worker")
    ]
    assert sum(float(item["cpus"]) for item in limits) == 1
    assert limits[0]["memory"] == "${INGEST_WORKER_MEMORY_LIMIT:-3072M}"
    assert limits[1]["memory"] == limits[2]["memory"] == "512M"
    for name in ("backend", "worker", "parse_worker", "notification_worker", "ocr_worker", "beat"):
        assert services[name]["environment"]["CELERY_NOTIFICATION_QUEUE"] == "notifications"
    # External sends are not exactly-once; queue isolation must not enable new global retries.
    assert not worker.celery_app.conf.task_reject_on_worker_lost
