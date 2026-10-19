import asyncio
import json
import logging

import pytest

from app.services import desensitization
from app.services.desensitization import LlmOutputDesensitizer
from app.services.llm_client import LLMError


class Model:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def chat_completion(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _plan(items, *, complete=True):
    return json.dumps({"complete": complete, "redactions": items}, ensure_ascii=False)


def _long_text():
    return (
        "PRIVATE客户甲\n"
        + "保留原始步骤和段落。\n" * 1500
        + "结尾仍为PRIVATE客户甲；电话13800138000。"
    )


async def test_long_document_is_locally_reconstructed_in_full_without_model_rewriting():
    source = _long_text()
    model = Model(_plan([{"text": "PRIVATE客户甲", "replacement": "【客户】"}]))
    result = await LlmOutputDesensitizer(model).scrub(source, trace_id="safe-trace")
    assert result == source.replace("PRIVATE客户甲", "【客户】").replace(
        "13800138000", "【手机号】"
    )
    messages, options = model.calls[0]
    assert json.loads(messages[1]["content"]) == {"text": source}
    assert options["json_object"] is True and options["max_tokens"] == 2048
    assert options["trace_id"] == "safe-trace"


@pytest.mark.parametrize(
    "response",
    [
        None,
        "non-json PRIVATE_ERROR",
        "[" * 1500 + "]" * 1500,
        "x" * 32769,
        "{}",
        _plan([], complete=False),
        _plan([]),
        _plan([{"text": "not in document", "replacement": "【客户】"}]),
        _plan([{"text": "PRIVATE客户甲", "replacement": "invented text"}]),
        _plan([{"text": "", "replacement": "【客户】"}]),
        _plan([{"text": "PRIVATE客户甲", "replacement": "【客户】", "extra": "PRIVATE"}]),
        json.dumps({"complete": 1, "redactions": []}),
        LLMError("unavailable", "PRIVATE_ERROR"),
    ],
    ids=[
        "none",
        "non-json",
        "deep-json",
        "oversized",
        "missing-fields",
        "incomplete",
        "empty",
        "invented-source",
        "unapproved-replacement",
        "blank-source",
        "extra-field",
        "boolean-required",
        "model-error",
    ],
)
async def test_invalid_or_failed_plan_never_releases_any_part_of_long_document(response, caplog):
    caplog.set_level(logging.INFO, logger="app.services.desensitization")
    assert await LlmOutputDesensitizer(Model(response)).scrub(_long_text()) is None
    assert "PRIVATE" not in repr([r.__dict__ for r in caplog.records])


async def test_all_occurrences_and_overlapping_ranges_are_redacted_without_gaps():
    source = "ABCD / ABCD\n" + "保留正文。" * 1000
    model = Model(
        _plan(
            [
                {"text": "ABC", "replacement": "【客户】"},
                {"text": "BCD", "replacement": "【联系人】"},
            ]
        )
    )
    result = await LlmOutputDesensitizer(model).scrub(source)
    assert result == "【敏感信息】 / 【敏感信息】\n" + "保留正文。" * 1000


async def test_short_document_keeps_existing_rewrite_contract():
    model = Model("已擦洗【客户】")
    assert await LlmOutputDesensitizer(model).scrub("原文客户甲") == "已擦洗【客户】"
    assert model.calls[0][0][1]["content"] == "原文客户甲"
    assert model.calls[0][1]["json_object"] is False


def test_plan_budgets_and_noop_fail_closed():
    apply = desensitization._apply_redaction_plan
    item = {"text": "甲乙", "replacement": "【客户】"}
    assert apply("甲乙", _plan([item] * 257)) is None
    assert apply("甲乙" * 10001, _plan([item])) is None
    assert apply("【客户】", _plan([{"text": "【客户】", "replacement": "【客户】"}])) is None
    assert apply("x" * 257, _plan([{"text": "x" * 257, "replacement": "【客户】"}])) is None


async def test_success_diagnostic_has_no_entities_or_document_content(caplog):
    caplog.set_level(logging.INFO, logger="app.services.desensitization")
    model = Model(_plan([{"text": "PRIVATE客户甲", "replacement": "【客户】"}]))
    await LlmOutputDesensitizer(model).scrub(_long_text(), trace_id="safe-trace")
    record = next(r for r in caplog.records if r.message == "retrieval_long_redaction")
    assert record.redaction_status == "complete"
    assert record.content_chars == len(_long_text())
    assert record.trace_id == "safe-trace"
    assert "PRIVATE" not in repr(record.__dict__)


async def test_long_plan_timeout_drains_model_and_does_not_release_raw_text(monkeypatch):
    finished = asyncio.Event()

    class WaitingModel:
        async def chat_completion(self, *args, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()

    monkeypatch.setattr(desensitization, "_LONG_SCRUB_TIMEOUT_SECONDS", 0.001)
    assert await LlmOutputDesensitizer(WaitingModel()).scrub(_long_text()) is None
    assert finished.is_set()


async def test_caller_cancellation_is_propagated_and_drains_long_plan():
    entered, finished = asyncio.Event(), asyncio.Event()

    class WaitingModel:
        async def chat_completion(self, *args, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()

    task = asyncio.create_task(LlmOutputDesensitizer(WaitingModel()).scrub(_long_text()))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert finished.is_set()
