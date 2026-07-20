"""Celery 任务重试分类与退避测试。

验证：瞬时/基础设施异常判为可重试；4xx/业务终态判为不可重试；指数退避值正确。
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy.exc import InterfaceError, OperationalError

from app.worker.retry import backoff_countdown, is_retryable


class _Coded(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@pytest.mark.parametrize(
    "exc",
    [
        TimeoutError("timed out"),
        ConnectionError("conn reset"),
        httpx.ConnectError("refused"),
        httpx.TimeoutException("read timeout"),
        httpx.PoolTimeout("pool"),
        OperationalError("SELECT 1", None, Exception("server closed connection")),
        InterfaceError("x", None, Exception("connection invalidated")),
        _Coded("http_500"),  # WeKnora 5xx
        _Coded("http_503"),
        _Coded("http_429"),  # rate limited → 退避后重试
        _Coded("weknora_network_error"),
        _Coded("llm_network_error"),
        _Coded("llm_connection_error"),
        _Coded("llm_timeout"),
        _Coded("llm_rate_limited"),
        _Coded("llm_server_error"),
        _Coded("wecom_network_error"),
    ],
)
def test_retryable(exc):
    assert is_retryable(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("bad value"),
        _Coded("http_400"),  # 4xx 终态
        _Coded("http_404"),
        _Coded("wecom_bad_response"),
        _Coded("llm_bad_response"),
        _Coded("llm_authentication_error"),
        _Coded("llm_model_not_found"),
        _Coded("llm_request_error"),
        _Coded("knowledge_delete_forbidden"),  # 权限拒绝
        _Coded("extraction_failed"),  # 文件格式不支持
        OSError("no such file"),  # 文件读写错误：不无脑重试
        KeyError("missing"),
    ],
)
def test_non_retryable(exc):
    assert is_retryable(exc) is False


def test_backoff_is_exponential():
    assert backoff_countdown(0) == 60
    assert backoff_countdown(1) == 120
    assert backoff_countdown(2) == 240
