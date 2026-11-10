"""Identify disposable worker connections without changing their pool or locks."""

from capacity_common import guard

guard()

from app.worker import runtime  # noqa: E402
from app.worker.celery_app import celery_app  # noqa: E402, F401

_create_engine = runtime.create_async_engine


def _tagged_engine(*args, **kwargs):
    connect = kwargs.setdefault("connect_args", {})
    connect.setdefault("server_settings", {})["application_name"] = "kap-capacity-worker"
    return _create_engine(*args, **kwargs)


runtime.create_async_engine = _tagged_engine
