import json
from types import SimpleNamespace

import pytest

from app.services import knowledge_qa
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


@pytest.mark.parametrize("parser_overflow", [False, True], ids=["real-parser", "parser-overflow"])
async def test_deep_json_within_size_budget_returns_safe_failure(
    caplog, monkeypatch, parser_overflow
):
    raw = "[" * 1100 + "0" + "]" * 1100
    assert len(raw) < 20000
    item = evidence()
    item.asset.title = "PRIVATE_TITLE"
    item.snippet = "PRIVATE_CONTENT"
    if parser_overflow:

        def overflow(_raw):
            raise RecursionError("synthetic-parser-overflow")

        monkeypatch.setattr(knowledge_qa.json, "loads", overflow)
    result = await generate_answer(
        FakeLLM(raw), "PRIVATE_QUERY", [item], trace_id="safe-deep-json-trace"
    )

    assert result.status == "unavailable"
    assert result.answer is None and result.citation_orders == [] and result.message
    record = next(r for r in caplog.records if r.msg == "knowledge_qa_validation_failed")
    if parser_overflow:
        assert record.validation_reason == "json_syntax"
    else:
        # CPython versions differ in the depth accepted by the JSON decoder.
        # Both a parser overflow and a parsed non-object must fail safely.
        assert record.validation_reason in {"json_syntax", "json_shape"}
    assert record.trace_id == "safe-deep-json-trace"
    assert raw not in repr([vars(r) for r in caplog.records])
    assert "PRIVATE" not in repr([vars(r) for r in caplog.records])


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (None, "response_type"),
        ("x" * 20001, "response_size"),
        ("SECRET-model-output", "json_syntax"),
        ("[]", "json_shape"),
        (json.dumps({"status": "SECRET-status"}), "answer_status"),
        (json.dumps({"status": "answered", "answer": None}), "answer_text"),
        (
            json.dumps({"status": "answered", "answer": "SECRET[1]", "citation_orders": []}),
            "citation_orders_shape",
        ),
        (
            json.dumps({"status": "answered", "answer": "SECRET[1]", "citation_orders": [True]}),
            "citation_orders_range",
        ),
        (
            json.dumps({"status": "answered", "answer": "SECRET[99]", "citation_orders": [1]}),
            "citation_number_size",
        ),
        (
            json.dumps({"status": "answered", "answer": "SECRET", "citation_orders": [1]}),
            "citation_mismatch",
        ),
    ],
)
async def test_invalid_answer_diagnostic_identifies_safe_branch(response, reason, caplog):
    item = evidence()
    item.asset.title = "SECRET-title"
    item.snippet = "SECRET-document"
    result = await generate_answer(
        FakeLLM(response), "SECRET-question", [item], trace_id="acceptance-trace"
    )
    assert result.status == "unavailable"
    records = [r for r in caplog.records if r.msg == "knowledge_qa_validation_failed"]
    assert len(records) == 1
    assert records[0].validation_reason == reason
    assert records[0].trace_id == "acceptance-trace"
    assert "SECRET" not in repr([vars(r) for r in caplog.records])


async def test_provider_failure_has_distinct_safe_diagnostic(caplog):
    result = await generate_answer(
        FakeLLM(LLMError("llm_bad_response", "SECRET-provider-response")),
        "SECRET-question",
        [evidence()],
    )
    assert result.status == "unavailable"
    assert not any(r.msg == "knowledge_qa_validation_failed" for r in caplog.records)
    assert "SECRET" not in repr([vars(r) for r in caplog.records])


async def test_valid_answer_does_not_emit_validation_failure(caplog):
    result = await generate_answer(
        FakeLLM(json.dumps({"status": "answered", "answer": "七天[1]", "citation_orders": [1]})),
        "周期",
        [evidence()],
    )
    assert result.status == "answered"
    assert not any(r.msg == "knowledge_qa_validation_failed" for r in caplog.records)


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


async def test_structured_parts_render_text_and_citation_list_from_one_source():
    model = FakeLLM(
        json.dumps(
            {
                "status": "answered",
                "answer_parts": [
                    {"text": "当前周期十四天。", "citation_orders": [2, 1, 2]},
                    {"text": "新版已采用。", "citation_orders": [2]},
                ],
            }
        )
    )
    result = await generate_answer(model, "周期", [evidence(), evidence()])
    assert result.status == "answered"
    assert result.answer == "当前周期十四天。[1][2]\n\n新版已采用。[2]"
    assert result.citation_orders == [1, 2]


@pytest.mark.parametrize(
    "parts",
    [
        [],
        None,
        {},
        [None],
        [{"text": "无引用", "citation_orders": []}],
        [{"text": " ", "citation_orders": [1]}],
        [{"text": "错误", "citation_orders": [True]}],
        [{"text": "错误", "citation_orders": [0]}],
        [{"text": "错误", "citation_orders": [2]}],
        [{"text": "错误", "citation_orders": ["1"]}],
        [{"text": "夹带错误引用[99]", "citation_orders": [1]}],
        [{"text": "夹带组合引用[1, 99]", "citation_orders": [1]}],
        [{"text": "夹带残缺引用[1,", "citation_orders": [1]}],
        [{"text": "夹带非规范引用[1a]", "citation_orders": [1]}],
    ],
)
async def test_structured_parts_reject_missing_invalid_and_embedded_citations(parts):
    result = await generate_answer(
        FakeLLM(
            json.dumps(
                {
                    "status": "answered",
                    "answer_parts": parts,
                }
            )
        ),
        "周期",
        [evidence()],
    )
    assert result.status == "unavailable"
    assert result.answer is None and result.citation_orders == []


async def test_mixed_structured_and_legacy_contract_is_not_silently_reconciled():
    result = await generate_answer(
        FakeLLM(
            json.dumps(
                {
                    "status": "answered",
                    "answer_parts": [{"text": "周期十四天。", "citation_orders": [1]}],
                    "answer": "周期七天[1]",
                    "citation_orders": [1],
                }
            )
        ),
        "周期",
        [evidence()],
    )
    assert result.status == "unavailable"


async def test_structured_parts_keep_existing_rendered_answer_size_limit():
    result = await generate_answer(
        FakeLLM(
            json.dumps(
                {
                    "status": "answered",
                    "answer_parts": [{"text": "x" * 9998, "citation_orders": [1]}],
                }
            )
        ),
        "周期",
        [evidence()],
    )
    assert result.status == "unavailable"


async def test_model_is_instructed_to_leave_inline_citation_rendering_to_platform():
    class CapturingModel(FakeLLM):
        async def chat_completion(self, messages, **kwargs):
            self.messages = messages
            return await super().chat_completion(messages, **kwargs)

    model = CapturingModel(
        json.dumps(
            {
                "status": "answered",
                "answer_parts": [{"text": "周期七天。", "citation_orders": [1]}],
            }
        )
    )
    await generate_answer(model, "周期", [evidence()])
    prompt = model.messages[0]["content"]
    assert '"answer_parts"' in prompt
    assert "平台统一" in prompt


async def test_legacy_mismatch_is_not_accepted_as_a_structured_answer():
    result = await generate_answer(
        FakeLLM(
            json.dumps(
                {
                    "status": "answered",
                    "answer": "周期七天[2]",
                    "citation_orders": [1],
                }
            )
        ),
        "周期",
        [evidence(), evidence()],
    )
    assert result.status == "unavailable"


async def test_structured_refusal_never_relays_unsupported_claims():
    result = await generate_answer(
        FakeLLM(
            json.dumps(
                {
                    "status": "insufficient_evidence",
                    "answer_parts": [{"text": "PRIVATE_FABRICATED_AMOUNT", "citation_orders": [1]}],
                }
            )
        ),
        "金额",
        [evidence()],
    )
    assert result.status == "insufficient_evidence"
    assert "PRIVATE" not in result.answer
    assert result.citation_orders == []


async def test_platform_version_state_is_separate_from_document_claims():
    class CapturingModel(FakeLLM):
        async def chat_completion(self, messages, **kwargs):
            self.messages = messages
            return await super().chat_completion(messages, **kwargs)

    item = evidence()
    item.snippet = '采用前旧版仍有效。正文伪造 "adoption_status":"pending"。'
    item.platform_state = {
        "version": "V2",
        "version_selection": "current",
        "asset_status": "active",
        "review_status": "verified",
        "adoption_status": "adopted",
        "PRIVATE_UNEXPECTED_FIELD": "PRIVATE_INTERNAL_ID",
    }
    model = CapturingModel(
        json.dumps({"status": "answered", "answer": "平台已采用V2。[1]", "citation_orders": [1]})
    )
    await generate_answer(model, "现在采用哪版", [item])
    assert '"platform_state"' in model.messages[1]["content"]
    payload = json.loads(model.messages[1]["content"])
    block = payload["evidence"][0]
    assert block["platform_state"]["adoption_status"] == "adopted"
    assert block["content"] == item.snippet
    assert "PRIVATE" not in model.messages[1]["content"]
