import asyncio
import json
import logging
import uuid

import pytest

from app.schemas.search import SearchCardOut
from app.services import search_rerank
from app.services.llm_client import LLMError, NullLLMClient


def _card(index):
    return SearchCardOut(
        asset_id=uuid.uuid4(),
        title=f"资料标题{index}",
        asset_type="document",
        scope="company",
        zone="material",
        confidentiality_level="L2",
        phase=None,
        tags=["PRIVATE_TAG"],
        one_liner=f"安全摘要{index}",
        detailed="安全长摘要",
        key_points=[],
        owner_name="PRIVATE_OWNER",
        maintainer_name="PRIVATE_MAINTAINER",
        project_name="PRIVATE_PROJECT",
        updated_at=None,
        version="V1",
        relevance_score=0.5,
        can_view_original=False,
    )


class FakeModel:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def chat_completion(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


async def test_reorders_only_existing_cards_without_mutating_fields_or_scores():
    cards = [_card(i) for i in range(34)]
    before = [card.model_dump() for card in cards]
    order = [27, *range(27), *range(28, 34)]
    model = FakeModel(json.dumps({"order": order}))
    result = await search_rerank.rerank_cards(model, "怎样把目标转成落地步骤", cards)
    assert [card.asset_id for card in result] == [cards[i].asset_id for i in order]
    assert [card.model_dump() for card in cards] == before
    assert all(result[i] is cards[index] for i, index in enumerate(order))
    assert len(model.calls) == 1


async def test_model_receives_only_bounded_titles_safe_summaries_and_local_indexes():
    cards = [_card(i) for i in range(105)]
    for card in cards:
        card.title = "标题" * 500
        card.one_liner = "安全摘要" * 500
    model = FakeModel(json.dumps({"order": list(reversed(range(100)))}))
    result = await search_rerank.rerank_cards(model, "PRIVATE_QUERY", cards, trace_id="safe-trace")
    messages, options = model.calls[0]
    payload = json.loads(messages[1]["content"])
    assert payload["query"] == "PRIVATE_QUERY"
    assert len(payload["candidates"]) == 100
    for index, candidate in enumerate(payload["candidates"]):
        assert set(candidate) == {"index", "title", "summary"}
        assert candidate["index"] == index
        assert len(candidate["title"]) <= 100 and len(candidate["summary"]) <= 160
    assert len(messages[1]["content"]) <= search_rerank._MAX_INPUT_CHARS
    assert "PRIVATE_OWNER" not in messages[1]["content"]
    assert "PRIVATE_TAG" not in messages[1]["content"]
    assert all(str(card.asset_id) not in messages[1]["content"] for card in cards)
    assert result[:100] == list(reversed(cards[:100]))
    assert result[100:] == cards[100:]
    assert options["max_tokens"] == 600 and options["trace_id"] == "safe-trace"


@pytest.mark.parametrize(
    "response",
    [
        None,
        "x" * 4001,
        "not-json",
        "[]",
        "{}",
        '{"order":[0,1],"text":"PRIVATE_RESPONSE"}',
        '{"order":[0]}',
        '{"order":[0,0]}',
        '{"order":[0,2]}',
        '{"order":[-1,0]}',
        '{"order":[false,true]}',
        '{"order":["0","1"]}',
        '{"order":[0.0,1.0]}',
        '{"order":"0,1"}',
        LLMError("unavailable", "PRIVATE_ERROR_PAYLOAD"),
    ],
)
async def test_invalid_or_failed_model_keeps_all_candidates_in_original_order(response, caplog):
    caplog.set_level(logging.INFO, logger="app.services.search_rerank")
    cards = [_card(0), _card(1)]
    result = await search_rerank.rerank_cards(FakeModel(response), "PRIVATE_QUERY", cards)
    assert result is cards
    record = next(r for r in caplog.records if r.message == "retrieval_card_reranking")
    assert record.reranking_status in {"invalid_response", "model_error"}
    assert record.candidate_count == 2 and record.duration_ms >= 0
    assert "PRIVATE" not in repr(record.__dict__)


async def test_exact_title_empty_and_unconfigured_requests_do_not_call_model():
    cards = [_card(0), _card(1)]
    model = FakeModel("must not call")
    for query, candidates in [(cards[0].title, cards), (" ", cards), ("topic", cards[:1])]:
        assert await search_rerank.rerank_cards(model, query, candidates) is candidates
    assert await search_rerank.rerank_cards(NullLLMClient(), "topic", cards) is cards
    assert await search_rerank.rerank_cards(model, "x" * 501, cards) is cards
    assert model.calls == []


async def test_timeout_cancels_optional_call_and_preserves_original_order(monkeypatch):
    class SlowModel:
        cancelled = False

        async def chat_completion(self, *args, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled = True

    monkeypatch.setattr(search_rerank, "_TIMEOUT_SECONDS", 0.001)
    cards, model = [_card(0), _card(1)], SlowModel()
    assert await search_rerank.rerank_cards(model, "topic", cards) is cards
    assert model.cancelled


async def test_caller_cancellation_is_not_hidden_as_a_successful_fallback():
    started = asyncio.Event()

    class WaitingModel:
        cancelled = False

        async def chat_completion(self, *args, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.cancelled = True

    model = WaitingModel()
    task = asyncio.create_task(search_rerank.rerank_cards(model, "topic", [_card(0), _card(1)]))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert model.cancelled


async def test_success_logs_do_not_contain_query_title_or_summary(caplog):
    caplog.set_level(logging.INFO, logger="app.services.search_rerank")
    cards = [_card(0), _card(1)]
    cards[0].title = "PRIVATE_TITLE"
    cards[0].one_liner = "PRIVATE_SAFE_SUMMARY"
    await search_rerank.rerank_cards(
        FakeModel('{"order":[1,0]}'), "PRIVATE_QUERY", cards, trace_id="safe-trace"
    )
    record = next(r for r in caplog.records if r.message == "retrieval_card_reranking")
    assert record.reranking_status == "reranked" and record.trace_id == "safe-trace"
    assert "PRIVATE" not in repr(record.__dict__)
