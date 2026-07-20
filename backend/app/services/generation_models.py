"""KAP 内容生成模型持久化、安全引用与运行时解析。

产品配置存在后，内容生成调用只使用数据库中的平台默认模型。敏感字段使用 Fernet
加密落库，解密仅发生在后端构造 LLMClient 时；API/审计/日志只使用安全 model_ref。
"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from typing import cast

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.db.utils import utc_now
from app.models.generation_model import ContentGenerationModel, ContentGenerationSettings
from app.services.llm_client import (
    PROVIDER_REGISTRY,
    LLMClient,
    LLMError,
    NullLLMClient,
    get_llm_client,
    llm_enabled,
    safe_llm_diagnostic,
)


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


class GenerationModelError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(code)


def _cipher() -> Fernet:
    key = (get_settings().generation_model_encryption_key or "").strip()
    if not key:
        raise GenerationModelError(
            "generation_model_encryption_key_missing",
            "内容生成模型加密密钥未配置",
            503,
        )
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise GenerationModelError(
            "generation_model_encryption_key_invalid",
            "内容生成模型加密密钥格式无效",
            503,
        ) from exc


def _encrypt(value: str) -> str:
    encrypted = cast(bytes, _cipher().encrypt(value.encode("utf-8")))
    return encrypted.decode("ascii")


def _decrypt(value: str) -> str:
    try:
        decrypted = cast(bytes, _cipher().decrypt(value.encode("ascii")))
        return decrypted.decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError) as exc:
        raise GenerationModelError(
            "generation_model_secret_unreadable",
            "内容生成模型敏感配置无法读取",
            503,
        ) from exc


def _model_ref(model_id: uuid.UUID) -> str:
    key = (get_settings().generation_model_ref_secret or "kap-generation-model-ref-v1").encode(
        "utf-8"
    )
    return hmac.new(key, str(model_id).encode("ascii"), hashlib.sha256).hexdigest()


def generation_model_ref(provider: str, model: str) -> str:
    """兼容环境变量模型与既有 ai_result 的安全引用。"""
    raw = f"{provider}:{model}"
    key = (get_settings().generation_model_ref_secret or "kap-generation-model-ref-v1").encode(
        "utf-8"
    )
    return hmac.new(key, raw.encode("utf-8"), hashlib.sha256).hexdigest()


def _validate_http_url(value: str) -> str:
    cleaned = value.strip()
    if not cleaned.lower().startswith(("http://", "https://")):
        raise GenerationModelError(
            "generation_model_base_url_invalid",
            "API 地址必须以 http:// 或 https:// 开头",
        )
    return cleaned.rstrip("/")


def _required(value: str, code: str, message: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise GenerationModelError(code, message)
    return cleaned


async def _settings(
    session: AsyncSession, *, create: bool = False
) -> ContentGenerationSettings | None:
    row = await session.get(ContentGenerationSettings, 1)
    if row is None and create:
        row = ContentGenerationSettings(id=1)
        session.add(row)
        await session.flush()
    return row


async def all_connection_models(session: AsyncSession) -> list[ContentGenerationModel]:
    return list(
        (
            await session.execute(
                select(ContentGenerationModel).order_by(ContentGenerationModel.created_at)
            )
        )
        .scalars()
        .all()
    )


async def _resolve_ref(session: AsyncSession, model_ref: str) -> ContentGenerationModel | None:
    for model in await all_connection_models(session):
        if hmac.compare_digest(_model_ref(model.id), model_ref):
            return model
    return None


def _safe_model(model: ContentGenerationModel, default_id: uuid.UUID | None) -> dict:
    if model.last_error_category:
        health_status = "unhealthy"
    elif model.last_test_succeeded_at:
        health_status = "healthy"
    else:
        health_status = "untested"
    return {
        "model_ref": _model_ref(model.id),
        "display_name": model.display_name,
        "provider": model.provider,
        "model_name": model.model_name,
        "enabled": model.enabled,
        "is_default": model.id == default_id,
        "health_status": health_status,
        "last_test_succeeded_at": model.last_test_succeeded_at,
        "last_test_failed_at": model.last_test_failed_at,
        "last_error_category": model.last_error_category,
    }


async def list_admin_models(session: AsyncSession) -> list[dict]:
    settings = await _settings(session)
    default_id = settings.default_model_id if settings else None
    return [
        _safe_model(m, default_id)
        for m in await all_connection_models(session)
        if m.capability_type == "chat"
    ]


def _env_option() -> dict | None:
    settings = get_settings()
    client = get_llm_client()
    if isinstance(client, NullLLMClient):
        return None
    return {
        "model_ref": generation_model_ref(client.provider, client.model),
        "display_name": settings.llm_model or client.model,
        "provider": client.provider,
        "model_name": client.model,
        "enabled": True,
        "is_default": True,
    }


async def safe_generation_model_options(session: AsyncSession) -> list[dict]:
    settings = await _settings(session)
    if settings is None:
        fallback = _env_option()
        return [fallback] if fallback else []
    return [item for item in await list_admin_models(session) if item["enabled"]]


async def create_model(
    session: AsyncSession,
    *,
    display_name: str,
    provider: str,
    model_name: str,
    base_url: str,
    api_key: str,
    enabled: bool,
    make_default: bool,
    actor_id: uuid.UUID,
    capability_type: str = "chat",
) -> dict:
    if make_default and not enabled:
        raise GenerationModelError(
            "generation_model_default_disabled", "停用的内容生成模型不能设为默认"
        )
    model = ContentGenerationModel(
        display_name=_required(
            display_name, "generation_model_display_name_required", "请填写显示名称"
        ),
        provider=_required(provider, "generation_model_provider_required", "请选择 provider"),
        model_name=_required(model_name, "generation_model_name_required", "请填写模型名称"),
        capability_type=capability_type,
        base_url_ciphertext=_encrypt(_validate_http_url(base_url)),
        api_key_ciphertext=_encrypt(
            _required(api_key, "generation_model_api_key_required", "请填写 API key")
        ),
        enabled=enabled,
        created_by=actor_id,
        updated_by=actor_id,
    )
    session.add(model)
    await session.flush()
    settings = await _settings(session, create=True)
    if settings is None:
        raise RuntimeError("generation model settings missing after create=True")
    if make_default:
        settings.default_model_id = model.id
        settings.updated_by = actor_id
    await session.flush()
    return _safe_model(model, settings.default_model_id)


async def update_model(
    session: AsyncSession,
    model_ref: str,
    *,
    display_name: str,
    provider: str,
    model_name: str,
    base_url: str | None,
    api_key: str | None,
    enabled: bool,
    actor_id: uuid.UUID,
) -> dict:
    model = await _resolve_ref(session, model_ref)
    if model is None:
        raise GenerationModelError("generation_model_not_found", "内容生成模型不存在", 404)
    settings = await _settings(session, create=True)
    if settings is None:
        raise RuntimeError("generation model settings missing after create=True")
    if not enabled and settings.default_model_id == model.id:
        raise GenerationModelError(
            "generation_model_default_disable_denied",
            "请先选择其他默认模型或清空默认模型，再停用当前模型",
            409,
        )
    model.display_name = _required(
        display_name, "generation_model_display_name_required", "请填写显示名称"
    )
    model.provider = _required(provider, "generation_model_provider_required", "请选择 provider")
    model.model_name = _required(model_name, "generation_model_name_required", "请填写模型名称")
    model.enabled = enabled
    model.updated_by = actor_id
    if base_url is not None and base_url.strip():
        model.base_url_ciphertext = _encrypt(_validate_http_url(base_url))
    if api_key is not None and api_key.strip():
        model.api_key_ciphertext = _encrypt(api_key.strip())
    await session.flush()
    return _safe_model(model, settings.default_model_id)


async def delete_model(session: AsyncSession, model_ref: str) -> None:
    model = await _resolve_ref(session, model_ref)
    if model is None:
        raise GenerationModelError("generation_model_not_found", "内容生成模型不存在", 404)
    settings = await _settings(session, create=True)
    if settings is None:
        raise RuntimeError("generation model settings missing after create=True")
    if settings.default_model_id == model.id:
        raise GenerationModelError(
            "generation_model_default_delete_denied",
            "请先选择其他默认模型或清空默认模型，再删除当前模型",
            409,
        )
    await session.delete(model)
    await session.flush()


async def set_default_model(
    session: AsyncSession, model_ref: str | None, *, actor_id: uuid.UUID
) -> dict | None:
    settings = await _settings(session, create=True)
    if settings is None:
        raise RuntimeError("generation model settings missing after create=True")
    if not model_ref:
        settings.default_model_id = None
        settings.updated_by = actor_id
        await session.flush()
        return None
    model = await _resolve_ref(session, model_ref)
    if model is None:
        raise GenerationModelError("generation_model_not_found", "内容生成模型不存在", 404)
    if not model.enabled:
        raise GenerationModelError(
            "generation_model_default_disabled", "停用的内容生成模型不能设为默认"
        )
    if model.capability_type != "chat":
        raise GenerationModelError("generation_model_type_mismatch", "只有对话模型可用于内容生成")
    settings.default_model_id = model.id
    settings.updated_by = actor_id
    await session.flush()
    return _safe_model(model, model.id)


async def test_model_connection(session: AsyncSession, model_ref: str) -> dict:
    model = await _resolve_ref(session, model_ref)
    if model is None:
        raise GenerationModelError("generation_model_not_found", "内容生成模型不存在", 404)
    started = time.monotonic()
    try:
        client = LLMClient(
            provider=model.provider,
            api_key=_decrypt(model.api_key_ciphertext),
            base_url=_decrypt(model.base_url_ciphertext),
            model=model.model_name,
            timeout=min(get_settings().llm_timeout, 15.0),
        )
        await client.chat_completion(
            [{"role": "user", "content": "请仅回复 OK"}],
            json_object=False,
            trace_id=None,
        )
    except (LLMError, GenerationModelError) as exc:
        diagnostic = safe_llm_diagnostic(getattr(exc, "code", None))
        model.last_test_failed_at = utc_now()
        model.last_error_category = diagnostic.category
        await session.flush()
        return {
            "success": False,
            "error_category": diagnostic.category,
            "message": diagnostic.message,
            "remediation_hint": diagnostic.remediation_hint,
            "retryable": diagnostic.retryable,
            "duration_ms": round((time.monotonic() - started) * 1000),
        }
    model.last_test_succeeded_at = utc_now()
    model.last_error_category = None
    await session.flush()
    return {
        "success": True,
        "error_category": None,
        "message": "外部 LLM 连接正常。",
        "remediation_hint": "无需处理。",
        "retryable": False,
        "duration_ms": round((time.monotonic() - started) * 1000),
    }


def safe_connection_diagnostics(model: ContentGenerationModel) -> dict:
    safe = _safe_model(model, None)
    return {
        "health_status": safe["health_status"],
        "last_test_succeeded_at": safe["last_test_succeeded_at"],
        "last_test_failed_at": safe["last_test_failed_at"],
        "last_error_category": safe["last_error_category"],
    }


async def resolve_generation_llm_client(
    session: AsyncSession,
) -> LLMClient | NullLLMClient:
    settings = await _settings(session)
    if settings is None:
        return get_llm_client()
    if settings.default_model_id is None:
        return NullLLMClient()
    model = await session.get(ContentGenerationModel, settings.default_model_id)
    if model is None or not model.enabled or model.capability_type != "chat":
        return NullLLMClient()
    try:
        return LLMClient(
            provider=model.provider,
            api_key=_decrypt(model.api_key_ciphertext),
            base_url=_decrypt(model.base_url_ciphertext),
            model=model.model_name,
            timeout=get_settings().llm_timeout,
        )
    except (LLMError, GenerationModelError):
        return NullLLMClient()


async def get_generation_llm_client(
    session: AsyncSession = Depends(get_db),
) -> LLMClient | NullLLMClient:
    return await resolve_generation_llm_client(session)


async def generation_model_configured(session: AsyncSession) -> bool:
    return not isinstance(await resolve_generation_llm_client(session), NullLLMClient)


async def product_configuration_exists(session: AsyncSession) -> bool:
    return await _settings(session) is not None


def connection_model_ref(model: ContentGenerationModel) -> str:
    return _model_ref(model.id)


async def resolve_connection_ref(
    session: AsyncSession, model_ref: str
) -> ContentGenerationModel | None:
    return await _resolve_ref(session, model_ref)


def decrypt_connection_secrets(model: ContentGenerationModel) -> tuple[str, str]:
    """Return endpoint/key only to server-side adapter code."""
    return _decrypt(model.base_url_ciphertext), _decrypt(model.api_key_ciphertext)


def _client_for_model(model: ContentGenerationModel) -> LLMClient:
    return LLMClient(
        provider=model.provider,
        api_key=_decrypt(model.api_key_ciphertext),
        base_url=_decrypt(model.base_url_ciphertext),
        model=model.model_name,
        timeout=get_settings().llm_timeout,
    )


async def safe_project_qa_options(
    session: AsyncSession, fallback: LLMClient | NullLLMClient
) -> list[dict]:
    """Return only runnable project-QA choices and irreversible references."""
    settings = await _settings(session)
    default_id = settings.default_model_id if settings else None
    default_model = await session.get(ContentGenerationModel, default_id) if default_id else None
    default_available = bool(
        (default_model and default_model.enabled and default_model.capability_type == "chat")
        or (settings is None and not isinstance(fallback, NullLLMClient))
    )
    items: list[dict] = []
    if default_available:
        items.append(
            {
                "model_ref": "system_default",
                "display_name": "系统默认模型",
                "is_default": True,
            }
        )
    for model in await all_connection_models(session):
        if model.enabled and model.capability_type == "chat" and model.id != default_id:
            items.append(
                {
                    "model_ref": _model_ref(model.id),
                    "display_name": model.display_name,
                    "is_default": False,
                }
            )
    return items


async def resolve_project_qa_client(
    session: AsyncSession,
    model_ref: str,
    fallback: LLMClient | NullLLMClient,
) -> LLMClient | NullLLMClient:
    """Resolve a validated QA model without exposing connection credentials."""
    if model_ref == "system_default":
        settings = await _settings(session)
        if settings is None:
            if isinstance(fallback, NullLLMClient):
                raise GenerationModelError(
                    "project_qa_default_model_missing", "系统默认问答模型尚未配置", 409
                )
            return fallback
        model = (
            await session.get(ContentGenerationModel, settings.default_model_id)
            if settings.default_model_id
            else None
        )
        if model is None or not model.enabled or model.capability_type != "chat":
            raise GenerationModelError(
                "project_qa_default_model_missing", "系统默认问答模型尚未配置", 409
            )
        return _client_for_model(model)

    model = await _resolve_ref(session, model_ref)
    if model is None:
        raise GenerationModelError("project_qa_model_not_found", "所选问答模型不可用")
    if model.capability_type != "chat":
        raise GenerationModelError("project_qa_model_type_mismatch", "所选模型不支持问答")
    if not model.enabled:
        raise GenerationModelError("project_qa_model_disabled", "所选问答模型已停用", 409)
    return _client_for_model(model)
