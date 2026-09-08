"""Regression fixtures are synthetic, not customer data."""

import pytest

from app.services.authorized_summary import build_authorized_summary_variants
from app.services.content_processing import _SYSTEM_PROMPT
from app.services.desensitization import RuleBasedDesensitizer


@pytest.mark.parametrize(
    "source,secret",
    [
        ("总经理张三表示需要改进流程。", "张三"),
        ("李四女士提出建议。", "李四"),
        ("受访者：王五，反馈交付问题。", "王五"),
        ("报价：350000，尚未签约。", "350000"),
        ("合同约定 USD 12,500。", "12,500"),
        ("预算为 30 万美元。", "30"),
        ("合同金额为壹拾万元整。", "壹拾万"),
    ],
)
def test_authorized_summary_redacts_context_names_and_amounts(source, secret):
    short, detailed = build_authorized_summary_variants(one_liner=source, detailed=source)
    assert short and detailed
    assert secret not in short
    assert secret not in detailed
    # Re-running backfill should not keep changing placeholders.
    assert RuleBasedDesensitizer().desensitize(detailed).text == detailed


def test_ordinary_numbers_and_roles_are_preserved():
    source = "2026年开展3次培训，总经理负责协调，方法论包含4个步骤。"
    assert RuleBasedDesensitizer().desensitize(source).text == source


def test_confidentiality_prompt_includes_business_risk_definitions():
    for definition in (
        "L1 公开级",
        "L2 内部参考级",
        "L3 受限级",
        "L4 商业秘密级",
        "L5 严格商业秘密级",
        "高管评价",
        "上市底稿",
        "不得默认 L2",
        "空白合同模板不等同于已签合同",
    ):
        assert definition in _SYSTEM_PROMPT
