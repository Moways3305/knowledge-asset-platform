import json
from types import SimpleNamespace

import pytest

from app.services.knowledge_qa import generate_answer
from app.services.llm_client import LLMError


class FakeLLM:
    def __init__(self, response):
        self.response = response
        self.called = False

    async def chat_completion(self, *args, **kwargs):
        self.called = True
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def evidence():
    return SimpleNamespace(asset=SimpleNamespace(title="虚构验收样本"), snippet="复核周期七天。")


async def test_no_evidence_is_explicit_refusal_without_model_call():
    llm = FakeLLM("must not call")
    result = await generate_answer(llm, "不存在的制度金额", [])
    assert result.status == "insufficient_evidence"
    assert not llm.called
    assert result.answer and result.citation_orders == []


async def test_insufficient_evidence_never_relays_fabricated_amount_or_citations():
    llm = FakeLLM(
        json.dumps(
            {"status": "insufficient_evidence", "answer": "金额9999元", "citation_orders": [1]}
        )
    )
    result = await generate_answer(llm, "金额", [evidence()])
    assert result.status == "insufficient_evidence"
    assert "9999" not in result.answer
    assert result.citation_orders == []


@pytest.mark.parametrize(
    "response",
    [
        "",
        "arbitrary text",
        "[]",
        json.dumps({"status": "answered", "answer": "七天[2]", "citation_orders": [2]}),
        json.dumps({"status": "answered", "answer": "七天[1]", "citation_orders": [True]}),
        json.dumps({"status": "answered", "answer": "七天[99]", "citation_orders": [1]}),
        json.dumps({"status": "answered", "answer": "七天", "citation_orders": [1]}),
        json.dumps(
            {"status": "answered", "answer": "七天[" + "9" * 5000 + "]", "citation_orders": [1]}
        ),
    ],
)
async def test_invalid_or_uncited_answers_fail_safely(response):
    result = await generate_answer(FakeLLM(response), "周期", [evidence()])
    assert result.status == "unavailable"
    assert result.answer is None and result.citation_orders == []
    assert result.message


async def test_model_failure_has_safe_diagnostic_not_secret(caplog):
    result = await generate_answer(
        FakeLLM(LLMError("llm_not_configured", "SECRET-key-endpoint")), "周期", [evidence()]
    )
    assert result.status == "unavailable" and result.message
    assert "SECRET" not in result.message + caplog.text


async def test_grounded_answer_preserves_verified_citation_number():
    result = await generate_answer(
        FakeLLM(
            json.dumps({"status": "answered", "answer": "周期七天。[1]", "citation_orders": [1]})
        ),
        "周期",
        [evidence()],
    )
    assert result.status == "answered"
    assert result.answer == "周期七天。[1]" and result.citation_orders == [1]
