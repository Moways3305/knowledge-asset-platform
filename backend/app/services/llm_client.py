"""外部 LLM 客户端（R2）——一个 OpenAI 兼容客户端 + provider 注册表。

不写多套 SDK：所有 provider 都走 OpenAI 兼容 `POST {base_url}/chat/completions`，
`Authorization: Bearer {api_key}`。provider 注册表给出各家 base_url / 默认 model，
env 可覆盖。MiniMax 留薄 adapter 位（其 OpenAI 兼容通道历史有 GroupId 等差异）。

安全红线：`api_key` / `Authorization` 头**绝不**进异常 / 日志 / 审计 / 响应。
`LLMError` 只带 code/message。

dev/降级：未配置 provider+api_key → `llm_enabled()` False，依赖返回 `NullLLMClient`
（调用抛 `llm_not_configured`），内容处理据此降级（不让上传失败）。测试注入 fake。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings


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
        self, *, provider: str, api_key: str, base_url: str = "", model: str = "",
        timeout: float = 30.0, minimax_group_id: str = "",
    ) -> None:
        reg = PROVIDER_REGISTRY.get(provider) or PROVIDER_REGISTRY["custom"]
        self.provider = provider
        self._api_key = api_key
        self._base = (base_url or reg.base_url).rstrip("/")
        self.model = model or reg.default_model
        self._timeout = timeout
        self._minimax_group_id = minimax_group_id
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
        self, messages: list[dict[str, str]], *, temperature: float = 0.2,
        model: str | None = None, json_object: bool = True, trace_id: str | None = None,
    ) -> str:
        """调用 chat/completions，返回 assistant 文本内容（由调用方解析 JSON）。"""
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_object:
            payload["response_format"] = {"type": "json_object"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    self._endpoint(), json=payload, headers=self._headers(trace_id)
                )
        except httpx.HTTPError as exc:
            raise LLMError("llm_network_error", f"LLM 网络错误（{type(exc).__name__}）") from exc
        if resp.status_code >= 400:
            # 不回显 provider 错误明文（可能含敏感串）；只给状态码。
            raise LLMError(f"http_{resp.status_code}", "LLM 调用失败")
        try:
            data = resp.json()
            return str(data["choices"][0]["message"]["content"])
        except Exception as exc:  # noqa: BLE001
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
        provider=s.llm_provider, api_key=s.llm_api_key, base_url=s.llm_base_url,
        model=s.llm_model, timeout=s.llm_timeout, minimax_group_id=s.llm_minimax_group_id,
    )
