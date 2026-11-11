"""Regression for measurement overhead and incomplete capacity evidence."""

import importlib.util
import json
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"


@pytest.fixture
def stream(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    import capacity_metric_stream

    return capacity_metric_stream


def test_delta_batches_do_not_rewrite_history(stream, tmp_path):
    buffer = stream.MetricBuffer()
    buffer.add("qa.sql_ms", 4, 10)
    first = buffer.drain(11)
    buffer.add("qa.sql_ms", 8, 12)
    second = buffer.drain(13)
    assert first["samples"] == {"qa.sql_ms": [(10, 4)]}
    assert second["samples"] == {"qa.sql_ms": [(12, 8)]}
    assert buffer.drain(14)["samples"] == {}
    path = tmp_path / "api-metrics-first.jsonl"
    stream.append_frame(path, first)
    stream.append_frame(path, second)
    values, state = stream.read_window(tmp_path, 11, 12.5)
    assert values["qa.sql_ms"] == [8]
    assert state == {"complete": True, "dropped": 0, "writers": 1}


def test_reader_excludes_prior_windows_and_requires_every_writer(stream, tmp_path):
    for name, stamp, through in (("a", 5, 7), ("b", 6, 6.5), ("stopped", 1, 2)):
        buffer = stream.MetricBuffer()
        buffer.add("request_ms", 40, stamp)
        stream.append_frame(tmp_path / f"api-metrics-{name}.jsonl", buffer.drain(through))
    values, state = stream.read_window(tmp_path, 4, 7, expected_writers=2)
    assert values["request_ms"] == [40, 40]
    assert state == {"complete": False, "dropped": 0, "writers": 2}
    stream.append_frame(tmp_path / "api-metrics-b.jsonl", stream.MetricBuffer().drain(8))
    assert stream.read_window(tmp_path, 4, 7, expected_writers=2)[1]["complete"]
    assert not stream.read_window(tmp_path, 4, 7, expected_writers=3)[1]["complete"]


def test_partial_last_frame_cannot_claim_complete_window(stream, tmp_path):
    path = tmp_path / "api-metrics-a.jsonl"
    stream.append_frame(path, stream.MetricBuffer().drain(1))
    tail = json.dumps(stream.MetricBuffer().drain(3))
    with path.open("a") as output:
        output.write(tail)
    assert not stream.read_window(tmp_path, 0, 2)[1]["complete"]
    with path.open("a") as output:
        output.write("\n")
    assert stream.read_window(tmp_path, 0, 2)[1]["complete"]


def test_dropped_samples_are_reported_only_for_overlapping_windows(stream, tmp_path):
    buffer = stream.MetricBuffer(limit=2)
    for stamp in (1, 2, 3, 4):
        buffer.add("request_ms", 10, stamp)
    stream.append_frame(tmp_path / "api-metrics-a.jsonl", buffer.drain(5))
    values, state = stream.read_window(tmp_path, 0, 5)
    assert values["request_ms"] == [10, 10] and state["dropped"] == 2
    assert stream.read_window(tmp_path, 3, 5)[1]["dropped"] == 0
    assert buffer.drain(6)["dropped"] == {}


def test_corrupt_complete_frame_is_not_silently_ignored(stream, tmp_path):
    (tmp_path / "api-metrics-a.jsonl").write_text("broken\n")
    with pytest.raises(json.JSONDecodeError):
        stream.read_window(tmp_path, 0, 5)


def test_new_process_cannot_supply_missing_history_after_restart(stream, tmp_path):
    stream.append_frame(
        tmp_path / "api-metrics-new.jsonl", stream.MetricBuffer(started=5).drain(10)
    )
    assert not stream.read_window(tmp_path, 2, 8)[1]["complete"]
    assert stream.read_window(tmp_path, 6, 8)[1]["complete"]


@pytest.mark.asyncio
async def test_off_mode_bypasses_api_measurement_hooks_and_sampler(monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    for name, value in {
        "KAP_CAPACITY_ISOLATED": "1",
        "APP_ENV": "prod",
        "DATABASE_URL": "postgresql+asyncpg://capacity:capacity@postgres:5432/kap_capacity_test",
        "REDIS_URL": "redis://redis:6379/0",
        "WEKNORA_BASE_URL": "http://fixture:9000",
        "WEKNORA_API_KEY": "sk-synthetic-only",
        "LLM_BASE_URL": "http://fixture:9000/v1",
        "LLM_API_KEY": "synthetic-only",
        "STORAGE_ROOT": "/data/uploads",
        "KAP_CAPACITY_API_METRICS": "off",
    }.items():
        monkeypatch.setenv(name, value)
    spec = importlib.util.spec_from_file_location(
        "isolated_test_metrics", TOOLS / "capacity_metrics.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.install(object())  # An engine would be accessed if hooks were installed.
    calls = []

    async def app(scope, receive, send):
        calls.append(scope["type"])

    measured = module.MeasuredAPI(app)
    for kind in ("http", "lifespan"):
        await measured({"type": kind}, None, None)
    assert calls == ["http", "lifespan"]
    assert module.buffer.drain(0)["samples"] == {}
