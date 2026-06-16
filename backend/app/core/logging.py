"""结构化 JSON 日志基线。

统一把日志输出为单行 JSON（便于 ELK / Loki 等采集系统直接解析），每条自动带上
`timestamp` / `level` / `logger` / `trace_id`（来自请求或任务上下文）+ 调用方经 `extra=`
传入的安全字段。

安全红线（**由各调用点负责，不在此处过滤**）：日志**绝不**记录业务原文 / extracted_text、
密码 / password_hash / token_hash / session token / cookie、WeKnora kb_id·doc_id、API key /
base url 真实值、OAuth state·code·access_token·app_secret、raw IP / email / identifier_hash 全文。
允许：safe model_ref、hash 前缀（≤8）、asset_id / user_id（UUID）、safe error code、method /
sanitized path / status / latency。
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

# 跨请求 / 任务的关联 id（由 TraceIdMiddleware 与 worker run_task 设置）。
trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)

# LogRecord 的标准属性集合：用于从 record 中挑出调用方经 `extra=` 注入的自定义字段。
_STD_ATTRS = set(logging.makeLogRecord({}).__dict__) | {"taskName", "message"}


def bind_trace_id(trace_id: str | None) -> None:
    """把 trace_id 绑定到当前上下文，后续同上下文的日志自动带上（无需逐条传参）。"""
    trace_id_var.set(trace_id)


class JsonFormatter(logging.Formatter):
    """单行 JSON 格式化器。只序列化调用方显式给出的字段，不触碰请求/响应体。"""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc)
        payload: dict[str, object] = {
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        trace_id = getattr(record, "trace_id", None) or trace_id_var.get()
        if trace_id:
            payload["trace_id"] = trace_id
        # 调用方经 extra= 注入的自定义字段（排除标准属性与已单独处理的键）。
        for key, value in record.__dict__.items():
            if key not in _STD_ATTRS and key != "trace_id":
                payload[key] = value
        if record.exc_info and record.exc_info[0] is not None:
            # 仅记异常**类型名**（安全）；不记 message / stack（避免泄露内部细节；后续如需排查细节，
            # 应通过受控诊断通道处理）。
            payload["exc_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, default=str)


_configured = False


def configure_logging(level: str | None = None) -> None:
    """配置全局 JSON 结构化日志到 stdout。幂等：仅首次装配 handler，之后调用只调级别
    （避免重复调用 create_app 时反复增删 root handler，误伤如 pytest caplog 的临时 handler）。"""
    global _configured
    from app.core.config import get_settings

    log_level = (level or get_settings().log_level or "INFO").upper()

    root = logging.getLogger()
    if _configured:
        root.setLevel(log_level)
        return
    _configured = True

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(log_level)

    # uvicorn 自带的 access/error 日志改走 root 的 JSON handler，保证 stdout 全为 JSON。
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
