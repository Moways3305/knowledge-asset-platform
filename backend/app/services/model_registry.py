"""Additive onboarding control plane. Legacy runtimes keep their own IDs and defaults.

Leases serialize connection edits and operations; every checkpoint also compares versions.
WeKnora creation is journalled before the call and reconciled by a unique marker on retry.
An ambiguous create is never blindly repeated. No implicit default assignment or KB migration.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select

from app.db.utils import utc_now
from app.models.generation_model import ContentGenerationModel
from app.models.model_registry import ProviderConnection, RegisteredModel
from app.schemas.model_registry import ConnectionInput, ModelInput
from app.schemas.weknora_admin import ModelCheckRequest
from app.services import generation_models as gm
from app.services import model_probe
from app.services import weknora_models as wm
from app.services.model_provider_catalog import RegistryError, endpoints_for
from app.services.weknora_client import WeKnoraError

LEASE = timedelta(minutes=10)


def signature(model, connection):
    return f"{model.version}:{connection.config_version}:{connection.credential_version}"


def active(model):
    started = model.operation_started
    if started and started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return bool(model.operation_token and started and utc_now() - started < LEASE)


def config(connection):
    return json.loads(gm._decrypt(connection.config_ciphertext))


async def get_connection(session, connection_id, lock=False):
    stmt = (
        select(ProviderConnection)
        .where(ProviderConnection.id == connection_id)
        .execution_options(populate_existing=True)
    )
    if lock:
        stmt = stmt.with_for_update()
    connection = (await session.execute(stmt)).scalar_one_or_none()
    if not connection:
        raise RegistryError("connection_not_found", "供应商连接不存在。", 404)
    return connection


async def get_model(session, model_id):
    model = (
        await session.execute(
            select(RegisteredModel)
            .where(RegisteredModel.id == model_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if not model:
        raise RegistryError("model_not_found", "模型不存在。", 404)
    return model


async def connection_models(session, connection_id):
    return list(
        (
            await session.scalars(
                select(RegisteredModel)
                .where(RegisteredModel.connection_id == connection_id)
                .execution_options(populate_existing=True)
            )
        ).all()
    )


def connection_out(connection, models):
    endpoints = config(connection)
    return dict(
        id=connection.id,
        name=connection.name,
        provider=connection.provider,
        config_version=connection.config_version,
        credential_version=connection.credential_version,
        capabilities=list(endpoints),
        protocols={cap: ep["protocol"] for cap, ep in endpoints.items()},
        model_count=len(models),
        affected_models=[m.display_name for m in models],
    )


def model_out(model, connection):
    sig = signature(model, connection)
    current_test = model.tested_signature == sig
    status = model.test_status if current_test else "untested"
    bindings = {}
    for usage in model.usages:
        binding = model.bindings.get(usage, {})
        current = binding.get("signature") == sig and binding.get("status") == "ready"
        code = binding.get("error_code")
        bindings[usage] = {
            "status": binding.get("status", "pending"),
            "current": current,
            "error_code": code,
            "message": model_probe.message(code)
            if code
            else "已接入当前版本"
            if current
            else "旧版本仍在使用，当前版本尚未接入"
            if binding.get("signature")
            else "尚未接入",
        }
    return dict(
        id=model.id,
        request_id=model.request_id,
        connection_id=model.connection_id,
        connection_name=connection.name,
        provider=connection.provider,
        display_name=model.display_name,
        model_name=model.model_name,
        capability=model.capability,
        dimension=model.dimension,
        usages=model.usages,
        version=model.version,
        signature=sig,
        test_status=status,
        test_code=model.test_code if current_test else None,
        test_message=model_probe.message(model.test_code or "verified")
        if current_test and status != "untested"
        else model_probe.message("untested"),
        tested_at=model.tested_at if current_test else None,
        test_duration_ms=model.test_duration_ms if current_test else None,
        observed_dimension=model.observed_dimension if current_test else None,
        bindings=bindings,
        external_ref=gm._model_ref(model.external_id) if model.external_id else None,
        knowledge_ref=wm._model_ref(model.weknora_id) if model.weknora_id else None,
        busy=active(model),
    )


async def inventory(session):
    connections = list(
        (
            await session.scalars(
                select(ProviderConnection).order_by(ProviderConnection.created_at)
            )
        ).all()
    )
    models = list(
        (
            await session.scalars(
                select(RegisteredModel).order_by(RegisteredModel.created_at.desc())
            )
        ).all()
    )
    by_id = {c.id: c for c in connections}
    return {
        "connections": [
            connection_out(c, [m for m in models if m.connection_id == c.id]) for c in connections
        ],
        "models": [model_out(m, by_id[m.connection_id]) for m in models],
    }


async def save_connection(session, body: ConnectionInput, connection_id=None):
    if not connection_id and body.request_id:
        existing = await session.get(ProviderConnection, body.request_id)
        if existing:
            if (
                existing.name != body.name
                or existing.provider != body.provider
                or config(existing) != endpoints_for(body)
                or not body.api_key
                or gm._decrypt(existing.key_ciphertext) != body.api_key.get_secret_value().strip()
            ):
                raise RegistryError(
                    "idempotency_conflict", "该连接请求已保存，请刷新后编辑已有连接。", 409
                )
            return connection_out(existing, await connection_models(session, existing.id))
    if connection_id:
        connection = await get_connection(session, connection_id, lock=True)
        models = await connection_models(session, connection.id)
        if any(active(m) for m in models):
            raise RegistryError("operation_busy", "关联模型正在验证或接入，请稍后修改连接。", 409)
        if body.expected_version != connection.config_version:
            raise RegistryError("version_conflict", "连接已被修改，请刷新后重试。", 409)
        if body.provider != connection.provider:
            raise RegistryError("provider_immutable", "更换供应商请创建新的连接。", 409)
        endpoints = (
            endpoints_for(body)
            if body.endpoints is not None or body.workspace_id
            else config(connection)
        )
        if any(m.capability not in endpoints for m in models):
            raise RegistryError("capability_in_use", "关联模型正在使用该接口，不能移除。", 409)
        connection.name = body.name
        connection.config_version += 1
    else:
        if not body.api_key or not body.api_key.get_secret_value().strip():
            raise RegistryError("credential_required", "请填写 API Key。")
        endpoints = endpoints_for(body)
        connection = ProviderConnection(
            id=body.request_id or uuid.uuid4(),
            name=body.name,
            provider=body.provider,
            config_version=1,
            credential_version=0,
        )
        session.add(connection)
        models = []
    if body.api_key and body.api_key.get_secret_value().strip():
        key = body.api_key.get_secret_value().strip()
        if "\n" in key or "\r" in key:
            raise RegistryError("credential_invalid", "API Key 格式无效。")
        connection.key_ciphertext = gm._encrypt(key)
        connection.credential_version += 1
    connection.config_ciphertext = gm._encrypt(json.dumps(endpoints))
    connection.updated_at = utc_now()
    await session.flush()
    return connection_out(connection, models)


async def save_model(session, body: ModelInput, model_id=None):
    connection = await get_connection(session, body.connection_id, lock=True)
    if body.capability not in config(connection):
        raise RegistryError("capability_missing", "该连接未配置所选能力的接口。")
    usages = sorted(set(body.usages))
    if "business" in usages and body.capability != "chat":
        raise RegistryError("usage_mismatch", "内容生成与项目问答只支持对话模型。")
    if body.capability == "embedding" and not body.dimension:
        raise RegistryError("dimension_required", "请指定向量维度，验证时将检查实际返回维度。")
    if body.capability != "embedding" and body.dimension:
        raise RegistryError("dimension_not_applicable", "只有嵌入模型可以设置向量维度。")
    if not model_id:
        existing = (
            await session.scalars(
                select(RegisteredModel).where(RegisteredModel.request_id == body.request_id)
            )
        ).first()
        if existing:
            if (
                any(
                    getattr(existing, key) != getattr(body, key)
                    for key in (
                        "connection_id",
                        "model_name",
                        "capability",
                        "dimension",
                        "display_name",
                    )
                )
                or existing.usages != usages
            ):
                raise RegistryError(
                    "idempotency_conflict", "该接入请求已保存，请编辑已有草稿或重新开始。", 409
                )
            return model_out(existing, connection)
        model = RegisteredModel(
            request_id=body.request_id,
            connection_id=connection.id,
            version=1,
            bindings={},
            test_status="untested",
        )
        session.add(model)
    else:
        model = await get_model(session, model_id)
        if active(model):
            raise RegistryError("operation_busy", "模型正在验证或接入，请稍后修改。", 409)
        if body.expected_version != model.version:
            raise RegistryError("version_conflict", "模型已被修改，请刷新后重试。", 409)
        if body.connection_id != model.connection_id or body.request_id != model.request_id:
            raise RegistryError("connection_immutable", "更换连接请创建新的模型记录。", 409)
        if model.external_id or model.weknora_id or model.creation_uncertain:
            if any(
                getattr(body, key) != getattr(model, key)
                for key in ("model_name", "capability", "dimension")
            ):
                raise RegistryError(
                    "bound_model_immutable",
                    "已接入模型不能更换模型名称、能力或维度；请新增模型并通过用途设置或知识库迁移切换。",
                    409,
                )
            if not set(model.usages).issubset(usages):
                raise RegistryError(
                    "usage_in_use", "已接入用途不能直接移除，请先处理现有依赖。", 409
                )
        changed = (
            any(
                getattr(model, key) != getattr(body, key)
                for key in ("display_name", "model_name", "capability", "dimension")
            )
            or model.usages != usages
        )
        if changed:
            model.version += 1
    for key in ("display_name", "model_name", "capability", "dimension"):
        setattr(model, key, getattr(body, key))
    model.usages = usages
    model.updated_at = utc_now()
    await session.flush()
    return model_out(model, connection)


async def begin_operation(session, model_id, expected_signature, require_verified=False):
    initial = await get_model(session, model_id)
    connection = await get_connection(session, initial.connection_id, lock=True)
    model = await get_model(session, model_id)
    sig = signature(model, connection)
    if sig != expected_signature:
        raise RegistryError("version_conflict", "配置已变化，请刷新后重新验证。", 409)
    if active(model):
        raise RegistryError("operation_busy", "模型已有操作正在进行，请稍后刷新。", 409)
    if require_verified and (model.tested_signature != sig or model.test_status != "verified"):
        raise RegistryError("verification_required", "当前配置验证通过后才能接入用途。", 409)
    token = str(uuid.uuid4())
    model.operation_token, model.operation_started = token, utc_now()
    await session.commit()
    return model, connection, sig, token


async def checkpoint(session, model_id, sig, token):
    initial = await get_model(session, model_id)
    connection = await get_connection(session, initial.connection_id, lock=True)
    model = await get_model(session, model_id)
    if model.operation_token != token or signature(model, connection) != sig:
        raise RegistryError("stale", "配置或操作已更新，旧结果已丢弃。", 409)
    return model, connection


async def verify(session, model_id, expected_signature):
    model, connection, sig, token = await begin_operation(session, model_id, expected_signature)
    started = time.monotonic()
    code, observed = None, None
    try:
        observed = await model_probe.probe(
            config(connection)[model.capability],
            gm._decrypt(connection.key_ciphertext),
            model.model_name,
            model.capability,
            model.dimension,
            connection.provider,
        )
    except RegistryError as exc:
        code = exc.code
    model, connection = await checkpoint(session, model_id, sig, token)
    model.tested_signature, model.test_status = sig, "failed" if code else "verified"
    model.test_code, model.observed_dimension = code, observed
    model.tested_at, model.test_duration_ms = utc_now(), round((time.monotonic() - started) * 1000)
    model.operation_token = None
    await session.commit()
    return model_out(model, connection)


async def _sync_business(session, model, connection, endpoint, key, actor_id):
    provider = "deepseek" if connection.provider == "deepseek" else "openai"
    if model.external_id:
        await gm.update_model(
            session,
            gm._model_ref(model.external_id),
            display_name=model.display_name,
            provider=provider,
            model_name=model.model_name,
            base_url=endpoint["url"],
            api_key=key,
            enabled=True,
            actor_id=actor_id,
        )
    else:
        runtime = ContentGenerationModel(
            display_name=model.display_name,
            provider=provider,
            model_name=model.model_name,
            capability_type="chat",
            base_url_ciphertext=gm._encrypt(endpoint["url"]),
            api_key_ciphertext=gm._encrypt(key),
            enabled=True,
            created_by=actor_id,
            updated_by=actor_id,
        )
        session.add(runtime)
        await session.flush()
        model.external_id = runtime.id
    # The probe used the same OpenAI wire protocol and saved configuration; no default is changed.
    runtime = await session.get(ContentGenerationModel, model.external_id)
    runtime.last_test_succeeded_at, runtime.last_error_category = utc_now(), None
    runtime.tested_version = runtime.config_version


async def sync(session, model_id, expected_signature, client, actor_id, trace_id=None):
    model, connection, sig, token = await begin_operation(
        session, model_id, expected_signature, require_verified=True
    )
    endpoint = config(connection)[model.capability]
    key = gm._decrypt(connection.key_ciphertext)
    usages = list(model.usages)
    for usage in usages:
        model, connection = await checkpoint(session, model_id, sig, token)
        if (
            model.bindings.get(usage, {}).get("signature") == sig
            and model.bindings[usage].get("status") == "ready"
        ):
            continue
        code = None
        try:
            if usage == "business":
                await _sync_business(session, model, connection, endpoint, key, actor_id)
            else:
                marker = f"kap-registry:{model.id}"
                provider = (
                    "aliyun"
                    if endpoint["protocol"] == "dashscope"
                    else "siliconflow"
                    if model.capability == "rerank"
                    else "openai"
                )
                params = {"base_url": endpoint["url"], "provider": provider}
                if model.capability == "embedding":
                    params["embedding_parameters"] = {
                        "dimension": model.dimension,
                        "truncate_prompt_tokens": 0,
                    }
                if model.capability == "rerank":
                    params["interface_type"] = "cohere"
                payload = {
                    "name": model.model_name,
                    "type": wm._ALIAS_TO_WK[model.capability],
                    "source": "remote",
                    "description": marker,
                    "parameters": params,
                }
                if not model.weknora_id:
                    if model.creation_uncertain:
                        found = [
                            item
                            for item in await client.list_models(trace_id=trace_id)
                            if item.get("description") == marker
                        ]
                        if len(found) != 1 or not found[0].get("id"):
                            raise RegistryError(
                                "creation_unconfirmed", model_probe.message("creation_unconfirmed")
                            )
                        model.weknora_id = str(found[0]["id"])
                    else:
                        model.creation_uncertain = sig
                        await session.commit()  # Durable intent before remote side effect.
                        created = await client.create_model(
                            {**payload, "status": "active"}, trace_id=trace_id
                        )
                        model, connection = await checkpoint(session, model_id, sig, token)
                        if not created.get("id"):
                            raise RegistryError(
                                "creation_unconfirmed", model_probe.message("creation_unconfirmed")
                            )
                        model.weknora_id = str(created["id"])
                    await session.commit()  # Keep remote ID even if credential write fails.
                await client.update_model(model.weknora_id, payload, trace_id=trace_id)
                await client.update_model_credentials(
                    model.weknora_id, api_key=key, trace_id=trace_id
                )
                credential = await client.get_model_credentials(model.weknora_id, trace_id=trace_id)
                if wm._credential_status(credential) != "configured":
                    raise RegistryError(
                        "credential_unconfirmed", model_probe.message("credential_unconfirmed")
                    )
                check = await wm.check_model(
                    client,
                    ModelCheckRequest(model_ref=wm._model_ref(model.weknora_id)),
                    trace_id=trace_id,
                )
                if not check.success:
                    raise RegistryError(
                        "runtime_check_failed", model_probe.message("runtime_check_failed")
                    )
        except RegistryError as exc:
            code = exc.code
        except (WeKnoraError, HTTPException, gm.GenerationModelError):
            code = "sync_failed"
        # Flush local runtime writes before refresh. Knowledge checkpoints have already committed IDs.
        await session.flush()
        saved_external_id = model.external_id
        model, connection = await checkpoint(session, model_id, sig, token)
        if saved_external_id:
            model.external_id = saved_external_id
        previous = model.bindings.get(usage, {})
        model.bindings = {
            **model.bindings,
            usage: {
                "status": "failed" if code else "ready",
                "signature": previous.get("signature") if code else sig,
                "error_code": code,
            },
        }
        await session.commit()
    model, connection = await checkpoint(session, model_id, sig, token)
    model.operation_token = None
    await session.commit()
    return model_out(model, connection)


async def require_legacy_unmanaged(session, model_ref, kind):
    # Existing low-level APIs may read managed models, but edits must use versioned onboarding.
    models = list((await session.scalars(select(RegisteredModel))).all())
    for model in models:
        ref = (
            gm._model_ref(model.external_id)
            if kind == "business" and model.external_id
            else wm._model_ref(model.weknora_id)
            if kind == "knowledge" and model.weknora_id
            else None
        )
        if ref == model_ref:
            raise HTTPException(
                409,
                detail={
                    "denied_reason": "managed_model",
                    "message": "该模型由共享连接管理，请在模型接入记录中修改并重新验证。",
                },
            )
