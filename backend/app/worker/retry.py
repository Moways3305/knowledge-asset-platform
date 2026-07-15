"""Celery 任务重试分类与指数退避。

供 `app/worker/tasks/*` 决定一个逃逸到任务层的异常是否值得 `self.retry()`。

可重试（瞬时 / 基础设施）：网络超时 / 连接错误 / WeKnora·LLM·WeCom 网络错误 / WeKnora 5xx /
HTTP 429 / 临时 DB 连接失败（SQLAlchemy OperationalError·InterfaceError）。
不可重试（终态）：4xx（非 429）/ 权限拒绝 / 文件格式不支持 / 值错误等业务终态——直接失败，
由各自 service 层的 app-level 失败记录处理。
"""

from __future__ import annotations

import httpx
from sqlalchemy.exc import InterfaceError, OperationalError

# 基础设施 / 瞬时异常类型：连接 / 超时 / 网络 / DB 连接级。
# 不含裸 OSError（文件读写错误等终态也是 OSError，不应无脑重试）。
_RETRYABLE_TYPES: tuple[type[BaseException], ...] = (
    TimeoutError,
    ConnectionError,
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.NetworkError,
    httpx.PoolTimeout,
    OperationalError,  # SQLAlchemy：DB 连接断开 / 不可用（瞬时）
    InterfaceError,
)

# 我方结构化异常（WeKnoraError / LLMError / WeComError）的"瞬时" code。
_RETRYABLE_CODES = {
    "http_429",
    "llm_connection_error",
    "llm_timeout",
    "llm_rate_limited",
    "llm_server_error",
}
_RETRYABLE_CODE_PREFIXES = ("http_5",)  # 5xx
_RETRYABLE_CODE_SUFFIX = (
    "_network_error"  # weknora_network_error / llm_network_error / wecom_network_error
)


def is_retryable(exc: BaseException) -> bool:
    """异常是否属于"瞬时可重试"。未知一律视为不可重试（fail-safe，不无脑重试终态错误）。"""
    if isinstance(exc, _RETRYABLE_TYPES):
        return True
    code = getattr(exc, "code", None)
    if isinstance(code, str):
        if code in _RETRYABLE_CODES or code.endswith(_RETRYABLE_CODE_SUFFIX):
            return True
        if any(code.startswith(p) for p in _RETRYABLE_CODE_PREFIXES):
            return True
    return False


def backoff_countdown(retries: int) -> int:
    """指数退避：第 0 / 1 / 2 次重试 → 60 / 120 / 240 秒。"""
    return int(2**retries * 60)  # int() 收敛 pow 的 Any 标注；retries>=0 时为无操作
