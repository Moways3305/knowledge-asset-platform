"""外部 LLM 客户端——一个 OpenAI 兼容客户端 + provider 注册表。

不写多套 SDK：所有 provider 都走 OpenAI 兼容 `POST {base_url}/chat/completions`，
`Authorization: Bearer {api_key}`。provider 注册表给出各家 base_url / 默认 model，
env 可覆盖。MiniMax 留薄 adapter 位（其 OpenAI 兼容通道历史有 GroupId 等差异）。

安全红线：`api_key` / `Authorization` 头**绝不**进异常 / 日志 / 审计 / 响应。
`LLMError` 只带 code/message。

dev/降级：未配置 provider+api_key → `llm_enabled()` False，依赖返回 `NullLLMClient`
（调用抛 `llm_not_configured`），内容处理据此降级（不让上传失败）。测试注入 fake。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import safe_log_exception

_logger = logging.getLogger(__name__)


class LLMError(Exception):
    """LLM 调用失败（结构化，不含 api_key）。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class _Provider:
    base_url: str
    default_model: str


@dataclass(frozen=True)
class LLMDiagnostic:
    category: str
    message: str
    remediation_hint: str
    retryable: bool


@dataclass(frozen=True)
class LLMUsage:
    """Safe provider-reported token counters; never contains request content."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


_DIAGNOSTICS: dict[str, LLMDiagnostic] = {
    "connection_error": LLMDiagnostic(
        "connection_error",
        "无法连接外部 LLM 服务。",
        "检查 API 地址、DNS、防火墙和后端网络连通性后重试。",
        True,
    ),
    "authentication_error": LLMDiagnostic(
        "authentication_error",
        "外部 LLM 认证失败。",
        "更新 API key，并确认该凭证有权访问所选模型。",
        False,
    ),
    "model_unavailable": LLMDiagnostic(
        "model_unavailable",
        "配置的外部 LLM 模型不可用。",
        "核对模型名称及账号权限，或选择供应商已开放的模型。",
        False,
    ),
    "timeout": LLMDiagnostic(
        "timeout",
        "外部 LLM 请求超时。",
        "稍后重试；若持续超时，请检查网络或供应商服务状态。",
        True,
    ),
    "rate_limited": LLMDiagnostic(
        "rate_limited",
        "外部 LLM 请求受到限流。",
        "稍后重试，并检查供应商配额、并发限制或计费状态。",
        True,
    ),
    "request_error": LLMDiagnostic(
        "request_error",
        "外部 LLM 拒绝了测试请求。",
        "确认 API 地址提供 OpenAI-compatible chat/completions，并核对模型能力。",
        False,
    ),
    "server_error": LLMDiagnostic(
        "server_error",
        "外部 LLM 服务端暂时异常。",
        "稍后重试，并在持续失败时检查供应商服务状态。",
        True,
    ),
    "response_error": LLMDiagnostic(
        "response_error",
        "外部 LLM 返回了无法识别的响应。",
        "确认接口兼容 OpenAI chat/completions 响应格式。",
        False,
    ),
    "configuration_error": LLMDiagnostic(
        "configuration_error",
        "外部 LLM 本地配置无法使用。",
        "检查模型名称、API 地址和平台加密配置后重新保存连接。",
        False,
    ),
}


def safe_llm_diagnostic(code: str | None) -> LLMDiagnostic:
    """Map internal/client codes to a fixed user-safe diagnostic category."""
    raw = (code or "").strip()
    if raw in _DIAGNOSTICS:
        return _DIAGNOSTICS[raw]
    if raw in {"llm_connection_error", "llm_network_error"}:
        return _DIAGNOSTICS["connection_error"]
    if raw in {"llm_authentication_error", "http_401", "http_403"}:
        return _DIAGNOSTICS["authentication_error"]
    if raw in {"llm_model_not_found", "http_404"}:
        return _DIAGNOSTICS["model_unavailable"]
    if raw == "llm_timeout":
        return _DIAGNOSTICS["timeout"]
    if raw in {"llm_rate_limited", "http_429"}:
        return _DIAGNOSTICS["rate_limited"]
    if raw in {"llm_request_error", "http_400", "http_422"}:
        return _DIAGNOSTICS["request_error"]
    if raw == "llm_bad_response":
        return _DIAGNOSTICS["response_error"]
    if raw in {
        "llm_not_configured",
        "llm_no_base_url",
        "llm_no_model",
        "generation_model_secret_unreadable",
        "generation_model_encryption_key_missing",
        "generation_model_encryption_key_invalid",
    }:
        return _DIAGNOSTICS["configuration_error"]
    if raw == "llm_server_error" or raw.startswith("http_5"):
        return _DIAGNOSTICS["server_error"]
    return _DIAGNOSTICS["server_error"]


# provider 注册表：base_url + 默认 model（env 可覆盖）。
PROVIDER_REGISTRY: dict[str, _Provider] = {
    "deepseek": _Provider("https://api.deepseek.com/v1", "deepseek-chat"),
    "kimi": _Provider("https://api.moonshot.cn/v1", "moonshot-v1-8k"),
    "qwen": _Provider("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    "glm": _Provider("https://open.bigmodel.cn/api/paas/v4", "glm-4"),
    "minimax": _Provider("https://api.minimax.chat/v1", "abab6.5s-chat"),
    "openai": _Provider("https://api.openai.com/v1", "gpt-4o-mini"),
    "custom": _Provider("", ""),  # base_url / model 必须由 env 覆盖
}


class LLMClient:
    """OpenAI 兼容 LLM 客户端（httpx 异步）。"""

    def __init__(
        self,
        *,
        provider: str,
        api_key: str,
        base_url: str = "",
        model: str = "",
        timeout: float = 30.0,
        minimax_group_id: str = "",
    ) -> None:
        reg = PROVIDER_REGISTRY.get(provider) or PROVIDER_REGISTRY["custom"]
        self.provider = provider
        self._api_key = api_key
        self._base = (base_url or reg.base_url).rstrip("/")
        self.model = model or reg.default_model
        self._timeout = timeout
        self._minimax_group_id = minimax_group_id
        self.last_usage: LLMUsage | None = None
        if not self._base:
            raise LLMError("llm_no_base_url", f"provider {provider} 缺少 base_url")
        if not self.model:
            raise LLMError("llm_no_model", f"provider {provider} 缺少 model")

    def _headers(self, trace_id: str | None) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        if trace_id:
            h["X-Request-ID"] = trace_id
        return h

    def _endpoint(self) -> str:
        # MiniMax adapter 位：OpenAI 兼容通道差异在此隔离（当前仅可选 GroupId query）。
        url = f"{self._base}/chat/completions"
        if self.provider == "minimax" and self._minimax_group_id:
            url += f"?GroupId={self._minimax_group_id}"
        return url

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        model: str | None = None,
        json_object: bool = True,
        max_input_chars: int | None = None,
        max_tokens: int | None = None,
        trace_id: str | None = None,
    ) -> str:
        """调用 chat/completions，返回 assistant 文本内容（由调用方解析 JSON）。"""
        self.last_usage = None
        bounded_messages = [dict(message) for message in messages]
        if max_input_chars is not None:
            if max_input_chars < 1:
                raise LLMError("llm_request_error", "LLM 输入上限必须为正数")
            input_chars = sum(len(message.get("content", "")) for message in bounded_messages)
            if input_chars > max_input_chars:
                raise LLMError("llm_request_error", "LLM 输入超过当前调用场景上限")
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": bounded_messages,
            "temperature": temperature,
        }
        if json_object:
            payload["response_format"] = {"type": "json_object"}
        if max_tokens is not None:
            if max_tokens < 1:
                raise LLMError("llm_request_error", "LLM 输出上限必须为正数")
            payload["max_tokens"] = max_tokens
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    self._endpoint(), json=payload, headers=self._headers(trace_id)
                )
        except httpx.TimeoutException as exc:
            raise LLMError("llm_timeout", "LLM 请求超时") from exc
        except httpx.RequestError as exc:
            raise LLMError("llm_connection_error", "LLM 连接失败") from exc
        if resp.status_code >= 400:
            # 不回显 provider 错误明文（可能含敏感串）；只给状态码。
            if resp.status_code in {401, 403}:
                code = "llm_authentication_error"
            elif resp.status_code == 404:
                code = "llm_model_not_found"
            elif resp.status_code == 429:
                code = "llm_rate_limited"
            elif resp.status_code in {400, 422}:
                code = "llm_request_error"
            elif resp.status_code >= 500:
                code = "llm_server_error"
            else:
                code = "llm_request_error"
            raise LLMError(code, "LLM 调用失败")
        try:
            data = resp.json()
            usage = data.get("usage") if isinstance(data, dict) else None
            if isinstance(usage, dict):

                def safe_count(name: str) -> int | None:
                    value = usage.get(name)
                    return value if isinstance(value, int) and value >= 0 else None

                self.last_usage = LLMUsage(
                    prompt_tokens=safe_count("prompt_tokens"),
                    completion_tokens=safe_count("completion_tokens"),
                    total_tokens=safe_count("total_tokens"),
                )
            return str(data["choices"][0]["message"]["content"])
        except Exception as exc:  # noqa: BLE001
            safe_log_exception(_logger, "llm_response_malformed", exc, status=resp.status_code)
            raise LLMError("llm_bad_response", "LLM 响应结构异常") from exc


class NullLLMClient:
    """未配置 LLM 时的占位：任何调用抛 not_configured（内容处理据此降级）。"""

    provider = ""
    model = ""

    async def chat_completion(self, *_: Any, **__: Any) -> str:
        raise LLMError("llm_not_configured", "LLM 未配置")


def llm_enabled() -> bool:
    s = get_settings()
    return bool(s.llm_provider and s.llm_api_key)


def get_llm_client() -> LLMClient | NullLLMClient:
    """FastAPI 依赖：配置齐全 → 真实客户端；否则 → NullLLMClient。

    测试经 `app.dependency_overrides[get_llm_client]` 注入 fake，不打真实网络。
    """
    if not llm_enabled():
        return NullLLMClient()
    s = get_settings()
    return LLMClient(
        provider=s.llm_provider,
        api_key=s.llm_api_key,
        base_url=s.llm_base_url,
        model=s.llm_model,
        timeout=s.llm_timeout,
        minimax_group_id=s.llm_minimax_group_id,
    )
