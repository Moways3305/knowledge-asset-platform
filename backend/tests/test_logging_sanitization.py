"""异常消息清洗（safe exception logging）测试。

构造含 URL / key / token / payload / email / IP 的异常消息，验证清洗后不含敏感内容，
但保留异常类型与安全错误码，仍具排查价值。
"""

from __future__ import annotations

import logging

from app.core.logging import (
    JsonFormatter,
    safe_log_exception,
    sanitize_exception_message,
)


def test_redacts_url_host_and_path():
    msg = "GET https://weknora.internal:8080/api/v1/models/wk-doc-123?api_key=sk-abc failed"
    out = sanitize_exception_message(RuntimeError(msg))
    assert "weknora.internal" not in out
    assert "wk-doc-123" not in out
    assert "<redacted-url>" in out


def test_redacts_bearer_and_sk_key():
    out = sanitize_exception_message(
        ValueError("Authorization: Bearer aToKenValue12345 / sk-1234567890abcdef")
    )
    assert "aToKenValue12345" not in out
    assert "sk-1234567890abcdef" not in out
    assert "<redacted" in out


def test_redacts_kv_secret_keeps_key_name():
    out = sanitize_exception_message(
        RuntimeError("login failed app_secret=SuperSecretValue123 corpsecret: AnotherOne456")
    )
    assert "SuperSecretValue123" not in out
    assert "AnotherOne456" not in out
    # 键名保留以便排查"哪个配置项出错"。
    assert "app_secret" in out


def test_redacts_email_and_ip():
    out = sanitize_exception_message(
        RuntimeError("user alice@example.com from 192.168.10.20 rejected")
    )
    assert "alice@example.com" not in out
    assert "192.168.10.20" not in out
    assert "<redacted-email>" in out
    assert "<redacted-ip>" in out


def test_redacts_long_high_entropy_token():
    token = "Ab3" + "x9Z" * 12  # 39 chars, no separators
    out = sanitize_exception_message(RuntimeError(f"unexpected token {token} in response"))
    assert token not in out
    assert "<redacted>" in out


def test_keeps_safe_structured_message():
    # 我方结构化错误的中文安全文案应保留（无敏感内容）。
    out = sanitize_exception_message(RuntimeError("weknora_down: 底座暂时不可用"))
    assert "底座暂时不可用" in out
    assert "weknora_down" in out


def test_truncates_overlong_message():
    out = sanitize_exception_message(RuntimeError("x" * 1000))
    assert len(out) <= 301  # 300 + 省略号


class _CodedError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


def test_safe_log_exception_payload(caplog):
    logger = logging.getLogger("app.test.safe")
    exc = _CodedError(
        "weknora_call_failed", "GET https://host/secret?api_key=sk-xyz123456789 failed"
    )
    with caplog.at_level(logging.ERROR):
        safe_log_exception(logger, "weknora call failed", exc, asset_id="uuid-1")
    rec = caplog.records[-1]
    assert rec.exc_type == "_CodedError"
    assert rec.error_code == "weknora_call_failed"  # 结构化 safe code
    assert rec.asset_id == "uuid-1"
    # 不泄露 url / key；且**不带** exc_info（不落 traceback 原文）。
    assert "host" not in rec.error_summary
    assert "sk-xyz123456789" not in rec.error_summary
    assert rec.exc_info is None


def test_safe_log_exception_does_not_log_unsafe_code(caplog):
    """不信任任意异常的 .code：非安全 lower_snake（含大写/连字符/内部 id 形态）不写入日志。"""
    logger = logging.getLogger("app.test.unsafe_code")
    # 上游把 model id / 内部 id 塞进 .code —— 形态不安全，必须丢弃（不绕过 sanitize）。
    exc = _CodedError("wk-doc-9f3AbC-Internal", "boom")
    with caplog.at_level(logging.ERROR):
        safe_log_exception(logger, "x", exc, include_summary=False)
    rec = caplog.records[-1]
    assert not hasattr(rec, "error_code")  # 不安全 code 被丢弃
    assert rec.exc_type == "_CodedError"  # 仍保留类型供定位


def test_include_summary_false_omits_error_summary(caplog):
    """include_summary=False（宽 catch / 解析用户内容路径）：连清洗后的 message 也不记。"""
    logger = logging.getLogger("app.test.no_summary")
    exc = RuntimeError("POST https://host/x 机密业务原文片段 model_id=abc")
    with caplog.at_level(logging.WARNING):
        safe_log_exception(
            logger, "ingest_processing_failed", exc, include_summary=False, level=logging.WARNING
        )
    rec = caplog.records[-1]
    assert not hasattr(rec, "error_summary")  # 不落 message（含原文风险）
    assert rec.exc_type == "RuntimeError"  # 仍可定位错误类别


def test_safe_log_exception_renders_clean_json():
    """经 JsonFormatter 渲染后整条日志不含敏感串。"""
    logger = logging.getLogger("app.test.safe.json")
    exc = RuntimeError("POST https://wk.internal/models token=Bearer secrettoken123456")
    record = logger.makeRecord(logger.name, logging.ERROR, __file__, 0, "ingest failed", (), None)
    record.exc_type = type(exc).__name__
    record.error_summary = sanitize_exception_message(exc)
    line = JsonFormatter().format(record)
    assert "wk.internal" not in line
    assert "secrettoken123456" not in line
