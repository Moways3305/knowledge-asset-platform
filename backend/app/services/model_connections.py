"""External OpenAI-compatible LLM connections and business default assignment.

This compatibility facade intentionally never imports or calls WeKnora services. KAP encrypted
chat connections are used by content generation and project QA. WeKnora foundation models remain
owned by the dedicated WeKnora administration APIs.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generation_model import ContentGenerationModel
from app.services import generation_models


class ModelConnectionError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(code)


@dataclass
class ConnectionRecord:
    model_ref: str
    model: ContentGenerationModel

    def safe_out(self) -> dict:
        return {
            "model_ref": self.model_ref,
            "display_name": self.model.display_name,
            "capability_type": "chat",
            "provider": self.model.provider,
            "model_name": self.model.model_name,
            "enabled": self.model.enabled,
            "health_status": "configured",
            "available_usages": ["content_generation", "project_qa"],
            "legacy_adapter": False,
        }


async def _records(session: AsyncSession) -> list[ConnectionRecord]:
    return [
        ConnectionRecord(generation_models.connection_model_ref(model), model)
        for model in await generation_models.all_connection_models(session)
        if model.capability_type == "chat"
    ]


async def list_connections(session: AsyncSession) -> tuple[list[dict], None]:
    records = await _records(session)
    return [record.safe_out() for record in records], None


async def _resolve(session: AsyncSession, model_ref: str) -> ConnectionRecord:
    for record in await _records(session):
        if hmac.compare_digest(record.model_ref, model_ref):
            return record
    raise ModelConnectionError("model_connection_not_found", "外部 LLM 连接不存在", 404)


def _require_chat(capability_type: str) -> None:
    if capability_type != "chat":
        raise ModelConnectionError(
            "external_llm_chat_required",
            "外部 LLM 连接仅支持对话模型；嵌入和重排模型请在 WeKnora 底座配置中维护",
        )


async def create_connection(
    session: AsyncSession,
    *,
    display_name: str,
    capability_type: str,
    provider: str,
    model_name: str,
    base_url: str,
    api_key: str,
    enabled: bool,
    actor_id,
) -> dict:
    _require_chat(capability_type)
    created = await generation_models.create_model(
        session,
        display_name=display_name,
        provider=provider,
        model_name=model_name,
        base_url=base_url,
        api_key=api_key,
        enabled=enabled,
        make_default=False,
        actor_id=actor_id,
        capability_type="chat",
    )
    record = await _resolve(session, created["model_ref"])
    return record.safe_out()


async def update_connection(
    session: AsyncSession,
    model_ref: str,
    *,
    display_name: str,
    capability_type: str,
    provider: str,
    model_name: str,
    base_url: str | None,
    api_key: str | None,
    enabled: bool,
    actor_id,
) -> dict:
    _require_chat(capability_type)
    record = await _resolve(session, model_ref)
    defaults = await get_usage_assignments(session)
    current = defaults.get("external_llm_default")
    if not enabled and current and current.get("model_ref") == record.model_ref:
        raise ModelConnectionError(
            "model_connection_in_use",
            "请先调整外部 LLM 默认连接，再停用当前连接",
            409,
        )
    await generation_models.update_model(
        session,
        model_ref,
        display_name=display_name,
        provider=provider,
        model_name=model_name,
        base_url=base_url,
        api_key=api_key,
        enabled=enabled,
        actor_id=actor_id,
    )
    return (await _resolve(session, model_ref)).safe_out()


async def test_connection(session: AsyncSession, model_ref: str) -> dict:
    await _resolve(session, model_ref)
    return await generation_models.test_model_connection(session, model_ref)


def _usage_slot(record: ConnectionRecord | None) -> dict | None:
    if record is None:
        return None
    return {
        "model_ref": record.model_ref,
        "display_name": record.model.display_name,
        "capability_type": "chat",
    }


async def get_usage_assignments(session: AsyncSession) -> dict:
    records = await _records(session)
    default = next(
        (item for item in await generation_models.list_admin_models(session) if item["is_default"]),
        None,
    )
    selected = next(
        (record for record in records if default and record.model_ref == default["model_ref"]),
        None,
    )
    return {"external_llm_default": _usage_slot(selected)}


async def set_usage_assignments(
    session: AsyncSession,
    *,
    external_llm_default_ref: str | None,
    actor_id,
) -> dict:
    if external_llm_default_ref:
        record = await _resolve(session, external_llm_default_ref)
        if not record.model.enabled:
            raise ModelConnectionError("model_usage_disabled", "停用的外部 LLM 不能设为默认")
    await generation_models.set_default_model(session, external_llm_default_ref, actor_id=actor_id)
    return await get_usage_assignments(session)
