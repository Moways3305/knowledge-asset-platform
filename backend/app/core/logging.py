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
import re
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

    # httpx/httpcore debug and info records include full request URLs.  WeCom
    # uses query parameters for corpsecret/access_token, so never let those
    # library records reach application logs; callers emit only safe codes.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


# 异常消息清洗规则（按顺序应用；越"包罗"的越先，避免子模式先吃掉外层）。
# 上游（WeKnora / WeCom / LLM / httpx）异常原文可能含 URL / payload / key / token / header，
# 直接 logger.exception 会泄露——故先经本清洗再记摘要。
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"https?://\S+"), "<redacted-url>"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<redacted-email>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<redacted-ip>"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+"), "Bearer <redacted>"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}"), "<redacted-key>"),
    # key=value / key: value 形式的敏感项：保留键名，脱敏值。
    (
        re.compile(
            r"(?i)\b(api[_-]?key|access[_-]?token|app[_-]?secret|corp[_-]?secret|client[_-]?secret"
            r"|secret|password|passwd|token|authorization|cookie|x-api-key)\b"
            r"(['\"\s]*[:=]['\"\s]*)[^\s,;'\"]+"
        ),
        r"\1=<redacted>",
    ),
    # 剩余高熵长串（≥32 连续字母数字/下划线/连字符）—— 多为 hash / 内部 id / token。
    (re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"), "<redacted>"),
)
_MAX_SUMMARY_LEN = 300

# 只有形如 lower_snake 的短码才视为"安全 error code"可直接入日志。任意异常的 `.code`
# 不可信（上游可能把 model id / OAuth code / 内部 id 放进去），不匹配则不写 error_code。
_SAFE_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def sanitize_exception_message(exc: BaseException) -> str:
    """把异常消息清洗为可安全入日志的摘要：移除 URL / email / IP / Bearer / key·token /
    `secret=...` 形式的敏感值与高熵长串，并截断长度。**绝不**返回原始上游异常原文。"""
    text = str(exc)
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    if len(text) > _MAX_SUMMARY_LEN:
        text = text[:_MAX_SUMMARY_LEN] + "…"
    return text


def safe_log_exception(
    logger: logging.Logger,
    message: str,
    exc: BaseException,
    *,
    level: int = logging.ERROR,
    include_summary: bool = True,
    **extra: object,
) -> None:
    """记录**清洗后**的异常摘要 + 异常类型（+ 结构化错误的 safe code）；**绝不**经
    `logger.exception` / `exc_info` 落原始 traceback / 上游异常原文。不改变降级逻辑，仅加可观测性。

    `include_summary=False`：连清洗后的 message 也不记，**只记异常类型名**——用于解析用户
    上传内容的路径（如 extraction / 脱敏），其异常 message 可能内嵌业务原文，清洗规则无法兜住。
    """
    payload: dict[str, object] = {"exc_type": type(exc).__name__}
    if include_summary:
        payload["error_summary"] = sanitize_exception_message(exc)
    # 仅当 .code 形如安全 lower_snake 短码时才记（我方结构化异常如此）；否则丢弃，
    # 不信任任意异常的 code 字段（可能内嵌 model id / OAuth code / 内部 id）。
    code = getattr(exc, "code", None)
    if isinstance(code, str) and _SAFE_ERROR_CODE.fullmatch(code):
        payload["error_code"] = code
    payload.update(extra)
    logger.log(level, message, extra=payload)
