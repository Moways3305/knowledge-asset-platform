"""Unified model connection view over KAP encrypted records and WeKnora models.

The encrypted KAP row is canonical for newly created connections. Existing WeKnora-only
models remain visible through a virtual adapter and are never copied or deleted.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.generation_model import ContentGenerationModel
from app.schemas.weknora_admin import (
    DefaultModelsUpdateRequest,
    ModelCheckRequest,
    ModelMutateRequest,
    ModelOut,
)
from app.services import generation_models, weknora_defaults, weknora_models
from app.services.weknora_client import NullWeKnoraClient, WeKnoraClient, WeKnoraError

CAPABILITIES = {"chat", "embedding", "rerank"}


class ModelConnectionError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(code)


@dataclass
class ConnectionRecord:
    model_ref: str
    display_name: str
    capability_type: str
    provider: str | None
    model_name: str
    enabled: bool
    canonical: ContentGenerationModel | None = None
    weknora: ModelOut | None = None
    legacy_adapter: bool = False

    def safe_out(self) -> dict:
        if self.capability_type == "chat":
            usages = ["knowledge_chat"]
            if self.canonical:
                usages.insert(0, "content_generation")
        else:
            usages = {
                "embedding": ["knowledge_embedding"],
                "rerank": ["knowledge_rerank"],
            }.get(self.capability_type, [])
        return {
            "model_ref": self.model_ref,
            "display_name": self.display_name,
            "capability_type": self.capability_type,
            "provider": self.provider,
            "model_name": self.model_name,
            "enabled": self.enabled,
            "health_status": "registered" if self.weknora else "configured",
            "available_usages": usages,
            "legacy_adapter": self.legacy_adapter,
        }


def _legacy_ref(weknora_ref: str) -> str:
    key = (get_settings().generation_model_ref_secret or "kap-generation-model-ref-v1").encode()
    return hmac.new(key, f"legacy-weknora:{weknora_ref}".encode(), hashlib.sha256).hexdigest()


def _same_connection(model: ContentGenerationModel, wk: ModelOut) -> bool:
    return (
        model.capability_type == wk.type
        and model.model_name.strip().casefold() == wk.name.strip().casefold()
        and (model.provider or "").strip().casefold() == (wk.provider or "").strip().casefold()
    )


async def _records(
    session: AsyncSession,
    client: WeKnoraClient | NullWeKnoraClient,
    *,
    trace_id: str | None,
) -> tuple[list[ConnectionRecord], str | None]:
    canonical = await generation_models.all_connection_models(session)
    warning = None
    try:
        wk_models = await weknora_models.list_models(client, model_type=None, trace_id=trace_id)
    except WeKnoraError:
        wk_models = []
        warning = "知识库模型连接暂时无法加载，请检查 WeKnora 配置后刷新"

    by_ref = {item.model_ref: item for item in wk_models}
    consumed: set[str] = set()
    records: list[ConnectionRecord] = []
    for model in canonical:
        wk = by_ref.get(model.weknora_model_ref or "")
        if wk is None:
            wk = next(
                (
                    candidate
                    for candidate in wk_models
                    if candidate.model_ref not in consumed and _same_connection(model, candidate)
                ),
                None,
            )
        if wk:
            consumed.add(wk.model_ref)
        records.append(
            ConnectionRecord(
                model_ref=generation_models.connection_model_ref(model),
                display_name=model.display_name,
                capability_type=model.capability_type,
                provider=model.provider,
                model_name=model.model_name,
                enabled=model.enabled and (wk.enabled if wk else True),
                canonical=model,
                weknora=wk,
                legacy_adapter=model.weknora_model_ref is None,
            )
        )
    for wk in wk_models:
        if wk.model_ref in consumed or wk.type not in CAPABILITIES:
            continue
        records.append(
            ConnectionRecord(
                model_ref=_legacy_ref(wk.model_ref),
                display_name=wk.name,
                capability_type=wk.type,
                provider=wk.provider,
                model_name=wk.name,
                enabled=wk.enabled,
                weknora=wk,
                legacy_adapter=True,
            )
        )
    return records, warning


async def list_connections(
    session: AsyncSession,
    client: WeKnoraClient | NullWeKnoraClient,
    *,
    trace_id: str | None,
) -> tuple[list[dict], str | None]:
    records, warning = await _records(session, client, trace_id=trace_id)
    return [record.safe_out() for record in records], warning


async def _resolve(
    session: AsyncSession,
    client: WeKnoraClient | NullWeKnoraClient,
    model_ref: str,
    *,
    trace_id: str | None,
) -> ConnectionRecord:
    records, _ = await _records(session, client, trace_id=trace_id)
    for record in records:
        if hmac.compare_digest(record.model_ref, model_ref):
            return record
    raise ModelConnectionError("model_connection_not_found", "模型连接不存在", 404)


def _validate_capability(capability_type: str) -> str:
    if capability_type not in CAPABILITIES:
        raise ModelConnectionError("model_connection_type_invalid", "不支持的模型能力类型")
    return capability_type


def _wk_request(
    *,
    display_name: str,
    capability_type: str,
    provider: str,
    base_url: str | None,
    api_key: str | None,
    enabled: bool,
) -> ModelMutateRequest:
    return ModelMutateRequest(
        name=display_name,
        type=capability_type,
        source="remote",
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        enabled=enabled,
    )


async def create_connection(
    session: AsyncSession,
    client: WeKnoraClient | NullWeKnoraClient,
    *,
    display_name: str,
    capability_type: str,
    provider: str,
    model_name: str,
    base_url: str,
    api_key: str,
    enabled: bool,
    actor_id,
    trace_id: str | None,
) -> dict:
    capability = _validate_capability(capability_type)
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
        capability_type=capability,
    )
    model = await generation_models.resolve_connection_ref(session, created["model_ref"])
    assert model is not None
    try:
        wk = await weknora_models.create_model(
            client,
            _wk_request(
                display_name=model_name,
                capability_type=capability,
                provider=provider,
                base_url=base_url,
                api_key=api_key,
                enabled=enabled,
            ),
            trace_id=trace_id,
        )
        model.weknora_model_ref = wk.model_ref
    except WeKnoraError as exc:
        if capability != "chat" or exc.code != "weknora_not_configured":
            raise
    await session.flush()
    record = ConnectionRecord(
        model_ref=created["model_ref"],
        display_name=model.display_name,
        capability_type=model.capability_type,
        provider=model.provider,
        model_name=model.model_name,
        enabled=model.enabled,
        canonical=model,
        legacy_adapter=False,
    )
    return record.safe_out()


async def update_connection(
    session: AsyncSession,
    client: WeKnoraClient | NullWeKnoraClient,
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
    trace_id: str | None,
) -> dict:
    record = await _resolve(session, client, model_ref, trace_id=trace_id)
    if _validate_capability(capability_type) != record.capability_type:
        raise ModelConnectionError(
            "model_connection_type_locked", "已有模型连接的能力类型不可修改", 409
        )
    if not enabled:
        assignments = await get_usage_assignments(session, client, trace_id=trace_id)
        if any(slot and slot.get("model_ref") == record.model_ref for slot in assignments.values()):
            raise ModelConnectionError(
                "model_connection_in_use",
                "请先调整平台默认用途，再停用当前模型连接",
                409,
            )
    if record.canonical:
        await generation_models.update_model(
            session,
            record.model_ref,
            display_name=display_name,
            provider=provider,
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            enabled=enabled,
            actor_id=actor_id,
        )
    if record.weknora:
        await weknora_models.update_model(
            client,
            record.weknora.model_ref,
            _wk_request(
                display_name=model_name,
                capability_type=record.capability_type,
                provider=provider,
                base_url=base_url,
                api_key=api_key,
                enabled=enabled,
            ),
            trace_id=trace_id,
        )
        if record.canonical:
            record.canonical.weknora_model_ref = record.weknora.model_ref
    elif record.canonical:
        endpoint, secret = generation_models.decrypt_connection_secrets(record.canonical)
        try:
            wk = await weknora_models.create_model(
                client,
                _wk_request(
                    display_name=model_name,
                    capability_type=record.capability_type,
                    provider=provider,
                    base_url=base_url or endpoint,
                    api_key=api_key or secret,
                    enabled=enabled,
                ),
                trace_id=trace_id,
            )
            record.canonical.weknora_model_ref = wk.model_ref
        except WeKnoraError as exc:
            if record.capability_type != "chat" or exc.code != "weknora_not_configured":
                raise
    await session.flush()
    refreshed = await _resolve(
        session,
        client,
        generation_models.connection_model_ref(record.canonical) if record.canonical else model_ref,
        trace_id=trace_id,
    )
    return refreshed.safe_out()


async def test_connection(
    session: AsyncSession,
    client: WeKnoraClient | NullWeKnoraClient,
    model_ref: str,
    *,
    trace_id: str | None,
) -> dict:
    record = await _resolve(session, client, model_ref, trace_id=trace_id)
    if record.canonical and record.capability_type == "chat":
        return await generation_models.test_model_connection(session, record.model_ref)
    if record.canonical:
        endpoint, secret = generation_models.decrypt_connection_secrets(record.canonical)
        started = time.monotonic()
        result = await weknora_models.check_model(
            client,
            ModelCheckRequest(
                model_type=record.capability_type,
                api_url=endpoint,
                api_key=secret,
                model=record.model_name,
            ),
            trace_id=trace_id,
        )
        return {
            "success": result.success,
            "message": "连接测试成功" if result.success else "连接测试失败，请检查模型连接",
            "duration_ms": round((time.monotonic() - started) * 1000),
        }
    return {
        "success": bool(record.weknora and record.weknora.enabled),
        "message": "连接已在知识库底座注册" if record.enabled else "模型连接已停用",
        "duration_ms": 0,
    }


def _usage_slot(record: ConnectionRecord | None) -> dict | None:
    if record is None:
        return None
    return {
        "model_ref": record.model_ref,
        "display_name": record.display_name,
        "capability_type": record.capability_type,
    }


async def get_usage_assignments(
    session: AsyncSession,
    client: WeKnoraClient | NullWeKnoraClient,
    *,
    trace_id: str | None,
) -> dict:
    records, _ = await _records(session, client, trace_id=trace_id)
    generation_default = next(
        (item for item in await generation_models.list_admin_models(session) if item["is_default"]),
        None,
    )
    content = next(
        (
            r
            for r in records
            if generation_default and r.model_ref == generation_default["model_ref"]
        ),
        None,
    )
    try:
        defaults = await weknora_models.get_default_models_out(session, client, trace_id=trace_id)
    except WeKnoraError:
        defaults = None

    def by_wk(slot) -> ConnectionRecord | None:
        if not slot or not slot.model_ref:
            return None
        return next(
            (r for r in records if r.weknora and r.weknora.model_ref == slot.model_ref), None
        )

    return {
        "content_generation": _usage_slot(content),
        "knowledge_embedding": _usage_slot(by_wk(defaults.embedding) if defaults else None),
        "knowledge_chat": _usage_slot(by_wk(defaults.chat) if defaults else None),
        "knowledge_rerank": _usage_slot(by_wk(defaults.rerank) if defaults else None),
    }


async def _weknora_ref_for_usage(
    session: AsyncSession,
    client: WeKnoraClient | NullWeKnoraClient,
    record: ConnectionRecord,
    *,
    actor_id,
    trace_id: str | None,
) -> str:
    if record.weknora:
        if record.canonical and not record.canonical.weknora_model_ref:
            record.canonical.weknora_model_ref = record.weknora.model_ref
            record.canonical.updated_by = actor_id
            await session.flush()
        return record.weknora.model_ref
    if not record.canonical:
        raise ModelConnectionError("model_connection_adapter_missing", "模型连接尚未接入知识库")
    endpoint, secret = generation_models.decrypt_connection_secrets(record.canonical)
    wk = await weknora_models.create_model(
        client,
        _wk_request(
            display_name=record.model_name,
            capability_type=record.capability_type,
            provider=record.provider or "custom",
            base_url=endpoint,
            api_key=secret,
            enabled=record.enabled,
        ),
        trace_id=trace_id,
    )
    record.canonical.weknora_model_ref = wk.model_ref
    record.canonical.updated_by = actor_id
    await session.flush()
    return wk.model_ref


async def set_usage_assignments(
    session: AsyncSession,
    client: WeKnoraClient | NullWeKnoraClient,
    *,
    content_generation_ref: str | None,
    knowledge_embedding_ref: str | None,
    knowledge_chat_ref: str | None,
    knowledge_rerank_ref: str | None,
    actor_id,
    trace_id: str | None,
) -> dict:
    async def selected(ref: str | None, expected: str) -> ConnectionRecord | None:
        if not ref:
            return None
        record = await _resolve(session, client, ref, trace_id=trace_id)
        if record.capability_type != expected:
            raise ModelConnectionError("model_usage_type_mismatch", "所选模型能力与用途不匹配")
        if not record.enabled:
            raise ModelConnectionError("model_usage_disabled", "停用的模型不能设为默认")
        return record

    content = await selected(content_generation_ref, "chat")
    embedding = await selected(knowledge_embedding_ref, "embedding")
    chat = await selected(knowledge_chat_ref, "chat")
    rerank = await selected(knowledge_rerank_ref, "rerank")
    if content and not content.canonical:
        raise ModelConnectionError(
            "content_generation_credentials_unavailable",
            "该旧知识库连接未由平台保管凭据，不能直接用于内容生成",
            409,
        )
    await generation_models.set_default_model(
        session, content.model_ref if content else None, actor_id=actor_id
    )
    if not any((embedding, chat, rerank)):
        current_row = await weknora_defaults.get_defaults(session)
        await weknora_defaults.set_defaults(
            session,
            embedding_model_id=None,
            chat_model_id=None,
            rerank_model_id=None,
            multimodal_id=(current_row.default_multimodal_model_id if current_row else None),
            updated_by=actor_id,
        )
        return await get_usage_assignments(session, client, trace_id=trace_id)
    current = await weknora_models.get_default_models_out(session, client, trace_id=trace_id)
    await weknora_models.set_default_models(
        session,
        client,
        DefaultModelsUpdateRequest(
            embedding_model_ref=(
                await _weknora_ref_for_usage(
                    session, client, embedding, actor_id=actor_id, trace_id=trace_id
                )
                if embedding
                else None
            ),
            chat_model_ref=(
                await _weknora_ref_for_usage(
                    session, client, chat, actor_id=actor_id, trace_id=trace_id
                )
                if chat
                else None
            ),
            rerank_model_ref=(
                await _weknora_ref_for_usage(
                    session, client, rerank, actor_id=actor_id, trace_id=trace_id
                )
                if rerank
                else None
            ),
            multimodal_ref=current.multimodal.model_ref if current.multimodal else None,
        ),
        updated_by=actor_id,
        trace_id=trace_id,
    )
    return await get_usage_assignments(session, client, trace_id=trace_id)
