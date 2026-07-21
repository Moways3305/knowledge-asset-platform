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
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 422,
        *,
        dependency: str | None = None,
        remediation_hint: str | None = None,
        action: str | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.dependency = dependency
        self.remediation_hint = remediation_hint
        self.action = action
        super().__init__(code)


@dataclass
class ConnectionRecord:
    model_ref: str
    model: ContentGenerationModel

    def safe_out(self) -> dict:
        safe = generation_models.safe_connection_diagnostics(self.model)
        return {
            "model_ref": self.model_ref,
            "display_name": self.model.display_name,
            "capability_type": "chat",
            "provider": self.model.provider,
            "model_name": self.model.model_name,
            "enabled": self.model.enabled,
            "health_status": safe["health_status"],
            "last_test_succeeded_at": safe["last_test_succeeded_at"],
            "last_test_failed_at": safe["last_test_failed_at"],
            "last_error_category": safe["last_error_category"],
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
            "当前连接正在承担内容生成和默认项目问答，不能直接停用。",
            409,
            dependency="external_llm_default",
            remediation_hint="先选择其他已启用连接作为默认，或明确清空默认用途，再停用当前连接。",
            action="change_or_clear_external_llm_default",
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


async def delete_model_connection(session: AsyncSession, model_ref: str) -> None:
    """删除外部 LLM 连接。

    关联检查：若该连接当前承担 external_llm_default 用途，拒绝删除（提示先切换默认）。
    默认模型的硬保护由底层 `generation_models.delete_model` 负责（409
    generation_model_default_delete_denied），此处不重复实现。
    """
    record = await _resolve(session, model_ref)
    defaults = await get_usage_assignments(session)
    current = defaults.get("external_llm_default")
    if current and current.get("model_ref") == record.model_ref:
        raise ModelConnectionError(
            "model_connection_in_use",
            "当前连接正在承担内容生成和默认项目问答，不能直接删除。",
            409,
            dependency="external_llm_default",
            remediation_hint="先选择其他已启用连接作为默认，或明确清空默认用途，再删除当前连接。",
            action="change_or_clear_external_llm_default",
        )
    await generation_models.delete_model(session, model_ref)


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
    slot = _usage_slot(selected)
    if slot is None:
        return {
            "external_llm_default": None,
            "dependency_status": "missing",
            "dependency_message": "未设置外部 LLM 默认连接，内容生成和默认项目问答将不可用。",
            "remediation_hint": "选择一个已启用且测试通过的外部 LLM 连接并保存。",
        }
    return {
        "external_llm_default": slot,
        "dependency_status": "configured",
        "dependency_message": "内容生成和默认项目问答使用当前外部 LLM 连接。",
        "remediation_hint": "变更或停用前，请先确认替代连接可用。",
    }


async def set_usage_assignments(
    session: AsyncSession,
    *,
    external_llm_default_ref: str | None,
    actor_id,
) -> dict:
    if external_llm_default_ref:
        record = await _resolve(session, external_llm_default_ref)
        if not record.model.enabled:
            raise ModelConnectionError(
                "model_usage_disabled",
                "停用的外部 LLM 不能设为默认。",
                dependency="external_llm_default",
                remediation_hint="先启用并测试该连接，或选择其他已启用连接。",
                action="enable_or_choose_external_llm",
            )
    await generation_models.set_default_model(session, external_llm_default_ref, actor_id=actor_id)
    return await get_usage_assignments(session)
