"""KAP 内容生成模型安全视图。

该模块只描述平台内容生成链路（标题 / 摘要 / 标签 / 内容建议）的安全配置状态，
不参与 WeKnora 知识库初始化，也不暴露 LLM base_url / api_key / 真实内部配置。
"""

from __future__ import annotations

import hashlib
import hmac

from app.core.config import get_settings
from app.services.llm_client import PROVIDER_REGISTRY, llm_enabled


def _configured_provider_model() -> tuple[str, str] | None:
    s = get_settings()
    if not llm_enabled():
        return None
    provider = (s.llm_provider or "").strip()
    model = (s.llm_model or "").strip()
    if not provider:
        return None
    if not model:
        reg = PROVIDER_REGISTRY.get(provider)
        model = reg.default_model if reg else ""
    if not model:
        return None
    return provider, model


def generation_model_ref(provider: str, model: str) -> str:
    raw = f"{provider}:{model}"
    key = (get_settings().generation_model_ref_secret or "kap-generation-model-ref-v1").encode(
        "utf-8"
    )
    return hmac.new(key, raw.encode("utf-8"), hashlib.sha256).hexdigest()


def current_generation_model_ref() -> str | None:
    pair = _configured_provider_model()
    if pair is None:
        return None
    return generation_model_ref(pair[0], pair[1])


def safe_generation_model_options() -> list[dict]:
    pair = _configured_provider_model()
    if pair is None:
        return []
    provider, model = pair
    return [
        {
            "model_ref": generation_model_ref(provider, model),
            "name": model,
            "provider": provider,
            "enabled": True,
            "is_default": True,
        }
    ]
