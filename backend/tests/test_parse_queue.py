"""Publish through Celery's router and guard the matching deployment consumer."""

import ast
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
from app.worker.tasks.parse import reconcile_parse


@pytest.mark.parametrize("name", ["default", "ocr", "", " ", "parse,default"])
def test_parse_queue_cannot_alias_shared_queues_or_list_multiple_consumers(name):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, celery_parse_queue=name)


@pytest.mark.parametrize("source", ["direct", "beat", "retry"])
def test_parse_publication_routes_to_custom_dedicated_queue(monkeypatch, source):
    suffix = uuid4().hex
    settings = Settings(
        _env_file=None,
        celery_broker_url="memory://",
        celery_result_backend="cache+memory://",
        celery_task_always_eager=False,
        celery_default_queue="ordinary-" + suffix,
        celery_ocr_queue="heavy-" + suffix,
        celery_parse_queue="parse-" + suffix,
    )
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    previous = current_app._get_current_object()
    app = worker._make_celery()
    previous.set_current()
    # Publish the real task; eager mode is disabled, so no database work runs here.
    task = app.tasks["weknora.parse_reconcile"]
    with app.connection_for_write() as connection:
        ordinary = connection.SimpleQueue(settings.celery_default_queue)
        dedicated = connection.SimpleQueue(settings.celery_parse_queue)
        try:
            if source == "beat":
                entry = ScheduleEntry(
                    name="weknora-parse-reconcile",
                    app=app,
                    **app.conf.beat_schedule["weknora-parse-reconcile"],
                )
                Scheduler(app=app, lazy=True).apply_async(entry, advance=False)
            elif source == "retry":
                task.push_request(
                    called_directly=False,
                    id=str(uuid4()),
                    retries=0,
                    args=(),
                    kwargs={},
                    delivery_info={"routing_key": settings.celery_parse_queue},
                )
                try:
                    task.retry(countdown=0, throw=False)
                finally:
                    task.pop_request()
            else:
                task.delay()
            message = dedicated.get(block=False)
            assert message.headers["task"] == "weknora.parse_reconcile"
            message.ack()
            with pytest.raises(Empty):
                ordinary.get(block=False)
            for name in ("domain_events.dispatch_pending", "ops.worker_heartbeat"):
                app.send_task(name)
                message = ordinary.get(block=False)
                assert message.headers["task"] == name
                message.ack()
            with pytest.raises(Empty):
                dedicated.get(block=False)
        finally:
            ordinary.close()
            dedicated.close()
            app.close()


def test_parse_worker_loss_requeues_only_the_idempotent_reconciler():
    assert reconcile_parse.acks_late
    assert reconcile_parse.reject_on_worker_lost
    assert not worker.celery_app.conf.task_reject_on_worker_lost


def test_live_upload_rehearsal_consumes_the_new_parse_route():
    # The functional fixture publishes the real parse task after upload. Without
    # this consumer it waits forever despite the API and worker both being healthy.
    source = Path(__file__).resolve().parents[2] / "scripts/weknora_kap_role_probe.py"
    commands = [
        [entry.value for entry in node.elts if isinstance(entry, ast.Constant)]
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
        if isinstance(node, ast.List)
    ]
    command = next(items for items in commands if "worker" in items and "-Q" in items)
    queues = set(command[command.index("-Q") + 1].split(","))
    settings = Settings(_env_file=None)
    assert {
        settings.celery_default_queue,
        settings.celery_ocr_queue,
        settings.celery_parse_queue,
        settings.celery_notification_queue,
    } <= queues


def test_compose_dedicated_consumer_is_bounded_and_checked_by_its_own_name():
    root = Path(__file__).resolve().parents[2]
    services = yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))["services"]
    parse = services["parse_worker"]
    assert "--queues=parse" in parse["command"]
    assert "--concurrency=1" in parse["command"]
    assert "--prefetch-multiplier=1" in parse["command"]
    assert "--destination=parse@$$HOSTNAME" in parse["healthcheck"]["test"][1]
    assert parse["stop_grace_period"] == "45s"
    assert parse["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert "ports" not in parse
    assert not parse.get("volumes"), "Status polling needs no document filesystem access"
    assert parse["deploy"]["resources"]["limits"]["memory"] == "512M"
    limits = [
        services[name]["deploy"]["resources"]["limits"]
        for name in ("worker", "parse_worker", "notification_worker")
    ]
    assert sum(float(limit["cpus"]) for limit in limits) == 1
    for name in ("backend", "worker", "ocr_worker", "beat", "parse_worker"):
        assert services[name]["environment"]["CELERY_PARSE_QUEUE"] == "parse"
    assert "--queues=default" in services["worker"]["command"]
    assert "--queues=ocr" in services["ocr_worker"]["command"]
