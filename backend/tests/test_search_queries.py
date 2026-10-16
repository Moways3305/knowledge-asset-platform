import asyncio
import json
import logging

import pytest

from app.services import search_queries
from app.services.llm_client import LLMError, NullLLMClient

QUESTION = "员工与企业保持长期共同利益的项目具体应该怎样实施和复核？"


class FakeModel:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def chat_completion(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


async def test_normalizes_without_dropping_original_and_bounds_queries():
    model = FakeModel(json.dumps({"queries": ["长期利益机制", "实施复核"]}))
    assert await search_queries.plan_queries(model, QUESTION) == [
        QUESTION,
        "长期利益机制",
        "实施复核",
    ]
    assert len(model.calls) == 1
    assert model.calls[0][0][1]["content"] == QUESTION


@pytest.mark.parametrize(
    "response",
    [
        "not-json",
        "[]",
        '{"queries":"all"}',
        json.dumps({"queries": ["a", "b", "c"]}),
        json.dumps({"queries": [False]}),
        json.dumps({"queries": ["x" * 61]}),
        json.dumps({"queries": ["all\nfiles"]}),
        LLMError("timeout", "secret-key"),
    ],
)
async def test_invalid_output_falls_back_without_executing_instructions(response):
    assert await search_queries.plan_queries(FakeModel(response), QUESTION) == [QUESTION]


async def test_short_blank_and_unconfigured_queries_need_no_model():
    model = FakeModel("must not call")
    assert await search_queries.plan_queries(model, "术语") == ["术语"]
    assert await search_queries.plan_queries(model, "  ") == []
    assert await search_queries.plan_queries(NullLLMClient(), QUESTION) == [QUESTION]
    assert model.calls == []


async def test_rewrite_timeout_preserves_original(monkeypatch):
    class SlowModel(FakeModel):
        async def chat_completion(self, *args, **kwargs):
            await asyncio.sleep(1)
            return '{"queries":["不可等待"]}'

    monkeypatch.setattr(search_queries, "_TIMEOUT_SECONDS", 0.001)
    assert await search_queries.plan_queries(SlowModel(None), QUESTION) == [QUESTION]


async def test_planning_logs_only_safe_status_counts_and_timing(caplog):
    caplog.set_level(logging.INFO, logger="app.services.search_queries")
    query = QUESTION + "PRIVATE_QUERY"
    term = "PRIVATE_MODEL_TERM"
    assert await search_queries.plan_queries(
        FakeModel(json.dumps({"queries": [term]})), query, trace_id="safe-trace"
    ) == [query, term]
    records = [r for r in caplog.records if r.message == "retrieval_query_planning"]
    assert len(records) == 1
    assert records[0].planning_status == "expanded"
    assert records[0].query_count == 2
    assert records[0].duration_ms >= 0
    assert "PRIVATE" not in caplog.text + repr(records[0].__dict__)


async def test_model_errors_do_not_log_upstream_exception_payload(caplog):
    caplog.set_level(logging.INFO, logger="app.services.search_queries")
    await search_queries.plan_queries(
        FakeModel(LLMError("custom", "PRIVATE_PROVIDER_KEY")), QUESTION
    )
    record = next(r for r in caplog.records if r.message == "retrieval_query_planning")
    assert record.planning_status == "model_error" and record.query_count == 1
    assert "PRIVATE" not in caplog.text + repr(record.__dict__)
