"""模型配置中心服务。

把 WeKnora `/models*` 与 `/initialization/*` 的原始结果**脱敏 + 映射**为对前端安全的形态：
- WeKnora server-only `model_id` → 单向 `model_ref`（HMAC-SHA256，前端不可逆推 id）；
- 写模型的 `api_key` / `base_url` 只代理上送 WeKnora，**平台不落库、响应不回显**；
- `weknora_kb_id` 绝不出响应——KB 初始化配置用平台 `weknora_kb_mappings.id` 定位。

错误沿用 `WeKnoraError`（code/message，不含 key）。
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from typing import TYPE_CHECKING, Any, Literal, TypeAlias

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.identity import Project, User
from app.models.indexing_job import IndexingOperationJob
from app.models.weknora import WeknoraKbMapping
from app.schemas.weknora_admin import (
    DefaultModelsOut,
    DefaultModelsUpdateRequest,
    KbConfigOut,
    KbInitUpdateRequest,
    KbMigrationStatusOut,
    ModelCheckRequest,
    ModelCheckResponse,
    ModelMutateRequest,
    ModelMutateResponse,
    ModelOptionOut,
    ModelOptionsResponse,
    ModelOut,
    ModelSlotOut,
    ProviderOut,
)
from app.services import weknora_defaults
from app.services.weknora_client import WeKnoraError

if TYPE_CHECKING:
    from app.services.weknora_client import NullWeKnoraClient, WeKnoraClient

# 前端别名 ↔ WeKnora ModelType。
_ALIAS_TO_WK = {
    "chat": "KnowledgeQA",
    "embedding": "Embedding",
    "rerank": "Rerank",
    "vllm": "VLLM",
    "asr": "ASR",
}
_WK_TO_ALIAS = {v: k for k, v in _ALIAS_TO_WK.items()}

# 类型别名：仅供静态检查。运行时值仍是同一字符串（future annotations 下注解不求值），无行为变化。
_CheckClient: TypeAlias = "WeKnoraClient | NullWeKnoraClient"
_CredentialStatus: TypeAlias = Literal["configured", "missing", "unknown"]


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"denied_reason": reason, "message": message}
    )


def _model_ref(model_id: str) -> str:
    """WeKnora server-only model_id → 对前端不可逆的 model_ref（单向 HMAC-SHA256）。

    防御：空 / "None" 的 id 直接拒绝，避免生成 HMAC("None") 这类「假成功」ref。
    """
    mid = str(model_id or "").strip()
    if not mid or mid == "None":
        raise _denied(502, "weknora_model_ref_invalid", "底座返回的模型标识无效")
    key = (get_settings().weknora_model_ref_secret or "kap-weknora-model-ref-v1").encode("utf-8")
    return hmac.new(key, mid.encode("utf-8"), hashlib.sha256).hexdigest()


def _alias(wk_type: str | None) -> str:
    return _WK_TO_ALIAS.get(wk_type or "", str(wk_type or "").lower())


def _to_model_out(raw: dict) -> ModelOut:
    params = raw.get("parameters") or {}
    status = raw.get("status")
    return ModelOut(
        model_ref=_model_ref(str(raw.get("id"))),
        name=str(raw.get("name") or ""),
        type=_alias(raw.get("type")),
        source=raw.get("source"),
        provider=params.get("provider"),
        enabled=(status == "active") if status is not None else True,
        is_builtin=bool(raw.get("is_builtin")),
        description=raw.get("description"),
        credential_status=_credential_status(raw.get("credentials")),
    )


def _credential_status(value: Any) -> _CredentialStatus:
    """Reduce upstream credential metadata to a safe tri-state without accepting secret values."""
    fields = value.get("fields") if isinstance(value, dict) else None
    # List/detail model DTOs expose the fields map directly, while the dedicated
    # credential endpoint wraps it in {fields: ...}.
    if not isinstance(fields, dict):
        fields = value if isinstance(value, dict) else None
    api_key = fields.get("api_key") if isinstance(fields, dict) else None
    configured = api_key.get("configured") if isinstance(api_key, dict) else None
    if configured is True:
        return "configured"
    if configured is False:
        return "missing"
    return "unknown"


async def _confirmed_credential_status(
    client: _CheckClient, model_id: str, trace_id: str | None
) -> _CredentialStatus:
    metadata = await client.get_model_credentials(model_id, trace_id=trace_id)
    return _credential_status(metadata)


async def _require_confirmed_credential(
    client: _CheckClient, model_id: str, trace_id: str | None
) -> None:
    status = await _confirmed_credential_status(client, model_id, trace_id)
    if status != "configured":
        reason = (
            "weknora_model_credential_missing"
            if status == "missing"
            else "weknora_model_credential_unconfirmed"
        )
        raise _denied(422, reason, "凭据未能确认保存，请重新配置并测试")


async def list_providers(
    client: _CheckClient, *, model_type: str | None, trace_id: str | None
) -> list[ProviderOut]:
    raw = await client.list_model_providers(model_type, trace_id=trace_id)
    out: list[ProviderOut] = []
    for p in raw:
        if not isinstance(p, dict):
            continue
        # 只取安全字段：value/label/description/modelTypes，外加**公开**的 defaultUrls
        # （供应商官方端点，非密钥），供前端"选 provider 自动带出默认地址"使用。
        out.append(
            ProviderOut(
                value=str(p.get("value") or ""),
                label=str(p.get("label") or p.get("value") or ""),
                description=p.get("description"),
                model_types=[str(t) for t in (p.get("modelTypes") or p.get("model_types") or [])],
                default_urls={
                    str(k): str(v)
                    for k, v in (p.get("defaultUrls") or p.get("default_urls") or {}).items()
                    if isinstance(v, str) and v.startswith(("http://", "https://"))
                },
            )
        )
    return out


async def list_models(
    client: _CheckClient, *, model_type: str | None, trace_id: str | None
) -> list[ModelOut]:
    raw = await client.list_models(trace_id=trace_id)
    out: list[ModelOut] = []
    for m in raw:
        if not isinstance(m, dict) or not m.get("id"):
            continue
        item = _to_model_out(m)
        if model_type and item.type != model_type:
            continue
        if not _is_valid_model_name(item.name):
            continue
        out.append(item)
    return out


async def _ref_to_id_map(client: _CheckClient, trace_id: str | None) -> dict[str, str]:
    """单向 model_ref → server-only model_id 的解析表（每次实时从 WeKnora 列举重建）。"""
    raw = await client.list_models(trace_id=trace_id)
    return {
        _model_ref(str(m["id"])): str(m["id"]) for m in raw if isinstance(m, dict) and m.get("id")
    }


async def _resolve_ref(client: _CheckClient, ref: str, trace_id: str | None) -> str | None:
    return (await _ref_to_id_map(client, trace_id)).get(ref)


def _is_http_url(value: str | None) -> bool:
    return str(value or "").strip().lower().startswith(("http://", "https://"))


# 已知合法模型名称前缀（白名单），防止拼写错误（如 deepsekk）进入系统。
# 来源：各厂商官方文档（DashScope/百炼、DeepSeek、Moonshot 等）。
# Qwen 系列同时存在旧命名 qwen-plus/qwen-turbo/qwen-max 与新命名 qwen3.x-plus/qwen3.x-max。
_APPROVED_MODEL_NAME_PREFIXES: tuple[str, ...] = (
    "deepseek-",
    "qwen-",
    "qwen2-",
    "qwen2.5-",
    "qwen3",
    "qwq-",
    "kimi-",
    "glm-",
    "minimax-",
    "gpt-",
    "text-embedding-",
    "embedding-",
    "bge-",
    "rerank",
    "whisper-",
    "funasr",
    "sensenova-",
    "ernie-",
    "hunyuan-",
    "yi-",
    "moonshot-",
    "baichuan-",
    "llama",
)


def _validate_model_name(name: str, context: str = "create") -> None:
    """校验模型名称是否符合已知格式，阻止拼写错误（如 deepsekk）注入 WeKnora。

    规则：
    只有明确配置的模型家族前缀可通过；未知名称没有语法回退或隐式 custom escape hatch。
    """
    if _is_valid_model_name(name):
        return
    raise _denied(
        422,
        "weknora_model_name_invalid",
        f"模型名称 '{name}' 不符合已知模型命名规范，{context} 被拒绝",
    )


def _is_valid_model_name(name: str | None) -> bool:
    """检查模型名称是否合法（不抛异常，供列表过滤使用）。"""
    if not name:
        return False
    lowered = (name or "").strip().lower()
    if not lowered:
        return False
    return any(lowered.startswith(prefix) for prefix in _APPROVED_MODEL_NAME_PREFIXES)


def _validate_remote_secret_inputs(req: ModelMutateRequest) -> None:
    if req.source != "remote":
        return
    if not (req.base_url or "").strip():
        raise _denied(422, "weknora_model_base_url_required", "远程模型需要填写 API 地址")
    if not (req.api_key or "").strip():
        raise _denied(422, "weknora_model_api_key_required", "远程模型需要填写访问密钥")
    if not _is_http_url(req.base_url):
        raise _denied(
            422, "weknora_model_base_url_invalid", "API 地址必须以 http:// 或 https:// 开头"
        )


def _validate_update_sensitive_inputs(req: ModelMutateRequest) -> None:
    if (req.base_url or "").strip() and not _is_http_url(req.base_url):
        raise _denied(
            422, "weknora_model_base_url_invalid", "API 地址必须以 http:// 或 https:// 开头"
        )


def _build_model_payload(req: ModelMutateRequest, *, keep_blank_sensitive: bool = True) -> dict:
    wk_type = _ALIAS_TO_WK.get(req.type)
    if wk_type is None:
        raise _denied(422, "invalid_model_type", "非法的模型类型")
    params: dict = {}
    if req.base_url is not None and (keep_blank_sensitive or str(req.base_url).strip()):
        params["base_url"] = str(req.base_url).strip()
    if req.api_key is not None and (keep_blank_sensitive or str(req.api_key).strip()):
        params["api_key"] = req.api_key
    if req.provider:
        params["provider"] = req.provider
    if req.type == "embedding" and req.dimension:
        params["embedding_parameters"] = {"dimension": req.dimension, "truncate_prompt_tokens": 0}
    payload = {
        "name": req.name,
        "type": wk_type,
        "source": req.source,
        "description": req.description or "",
        "parameters": params,
    }
    if req.enabled is not None:
        payload["status"] = "active" if req.enabled else "inactive"
    return payload


async def create_model(
    client: _CheckClient, req: ModelMutateRequest, *, trace_id: str | None
) -> ModelMutateResponse:
    _validate_remote_secret_inputs(req)
    _validate_model_name(req.name, context="创建模型")
    created = await client.create_model(_build_model_payload(req), trace_id=trace_id)
    mid = created.get("id") if isinstance(created, dict) else None
    if not mid:
        # 底座未返回有效 id → fail-closed：不生成 model_ref 假成功（调用方据此不写成功审计）。
        raise _denied(
            502, "weknora_model_create_no_id", "底座创建模型未返回有效标识，模型未确认创建成功"
        )
    if req.source == "remote":
        # Do not rely on parameters.api_key being persisted by the ordinary model endpoint.
        # Normalize create and update onto the v0.7.1 credential subresource, then perform a
        # separate metadata-only read before reporting success.
        await client.update_model_credentials(
            str(mid), api_key=str(req.api_key or "").strip(), trace_id=trace_id
        )
        await _require_confirmed_credential(client, str(mid), trace_id)
    return ModelMutateResponse(
        model_ref=_model_ref(str(mid)),
        name=str(created.get("name") or req.name),
        type=req.type,
        provider=req.provider,
        credential_status="configured" if req.source == "remote" else "unknown",
    )


async def update_model(
    client: _CheckClient, model_ref: str, req: ModelMutateRequest, *, trace_id: str | None
) -> ModelMutateResponse:
    _validate_model_name(req.name, context="更新模型")
    model_id = await _resolve_ref(client, model_ref, trace_id)
    if model_id is None:
        raise _denied(404, "weknora_model_not_found", "模型不存在")
    _validate_update_sensitive_inputs(req)
    saved = await client.get_model(model_id, trace_id=trace_id)
    api_key = str(req.api_key or "").strip()
    if req.source == "remote" and not api_key:
        # Blank means preserve only when the current credential can be authoritatively confirmed.
        await _require_confirmed_credential(client, model_id, trace_id)

    # v0.7.1 deliberately ignores credentials on PUT /models/{id}. Keep status out of the
    # metadata update so a credential-write failure cannot accidentally toggle the model.
    payload = _build_model_payload(req, keep_blank_sensitive=False)
    current_params = saved.get("parameters") if isinstance(saved, dict) else {}
    current_params = current_params if isinstance(current_params, dict) else {}
    # The upstream update DTO replaces the entire parameters object. Merge the saved safe fields
    # first, while explicitly excluding credential fields even if a non-conforming fake/upstream
    # response happens to include them.
    merged_params = {
        key: value for key, value in current_params.items() if key not in {"api_key", "app_secret"}
    }
    merged_params.update(payload.get("parameters") or {})
    merged_params.pop("api_key", None)
    merged_params.pop("app_secret", None)
    payload["parameters"] = merged_params
    # WeKnora v0.7.1 UpdateModelRequest has no status field. Omitting it preserves the current
    # enablement instead of pretending a guessed field was accepted.
    payload.pop("status", None)
    await client.update_model(model_id, payload, trace_id=trace_id)
    if req.source == "remote" and api_key:
        await client.update_model_credentials(model_id, api_key=api_key, trace_id=trace_id)
    if req.source == "remote":
        await _require_confirmed_credential(client, model_id, trace_id)
    return ModelMutateResponse(
        model_ref=_model_ref(model_id),
        name=req.name,
        type=req.type,
        provider=req.provider,
        credential_status="configured" if req.source == "remote" else "unknown",
    )


async def delete_model(client: _CheckClient, model_ref: str, *, trace_id: str | None) -> None:
    model_id = await _resolve_ref(client, model_ref, trace_id)
    if model_id is None:
        raise _denied(404, "weknora_model_not_found", "模型不存在")
    await client.delete_model(model_id, trace_id=trace_id)


async def check_model(
    client: _CheckClient, req: ModelCheckRequest, *, trace_id: str | None
) -> ModelCheckResponse:
    model_id = await _resolve_ref(client, req.model_ref, trace_id)
    if model_id is None:
        raise _denied(404, "weknora_model_not_found", "模型不存在或已被删除")

    # 模型详情仅留在服务端，用它重新取得保存时的连接配置；绝不接受浏览器提供的
    # type/name/url/key，也绝不将详情或上游原始 message 回传。
    saved = await client.get_model(model_id, trace_id=trace_id)
    params = saved.get("parameters") if isinstance(saved, dict) else {}
    params = params if isinstance(params, dict) else {}
    model_type = _alias(str(saved.get("type") or "")) if isinstance(saved, dict) else ""
    if model_type == "chat":
        fn = client.check_remote_model
    elif model_type == "embedding":
        fn = client.test_embedding_model
    elif model_type == "rerank":
        fn = client.check_rerank_model
    else:
        fn = None
    if fn is None:
        # Unsupported saved-model types must fail before inspecting optional
        # connection fields, so the user-visible error remains stable.
        raise _denied(
            422,
            "weknora_saved_model_check_unsupported",
            "当前知识底座版本不支持该类型的已保存模型连通性测试",
        )
    base_url = str(params.get("base_url") or params.get("api_url") or "").strip()
    model_name = str(saved.get("name") or "").strip() if isinstance(saved, dict) else ""
    source = str(saved.get("source") or "remote").strip()
    provider = str(params.get("provider") or "").strip() or None
    interface_type = (
        str(params.get("interface_type") or params.get("interfaceType") or "").strip() or None
    )
    # Credentials are intentionally absent from list/detail responses.  WeKnora v0.7.1
    # restores them from modelId; only non-sensitive saved-model metadata is required here.
    if not base_url or not model_name:
        raise _denied(
            422,
            "weknora_model_connection_config_missing",
            "该已保存模型缺少可用连接配置，请更新模型后重试",
        )
    credential_status: _CredentialStatus = "unknown"
    if source == "remote":
        credential_status = await _confirmed_credential_status(client, model_id, trace_id)
        if credential_status != "configured":
            return ModelCheckResponse(
                success=False,
                message="凭据未配置或保存状态未确认，请重新输入并保存后测试",
                error_code=(
                    "credential_missing"
                    if credential_status == "missing"
                    else "credential_unconfirmed"
                ),
                credential_status=credential_status,
            )
    res = await fn(
        model_id=model_id,
        model_name=model_name,
        base_url=base_url,
        source=source,
        provider=provider,
        interface_type=interface_type,
        trace_id=trace_id,
    )
    # `_unwrap` already checked the HTTP/envelope success. The v0.7.1 business result is the
    # `data` object returned here; an absent or false `available` must fail closed.
    success = isinstance(res, dict) and res.get("available") is True
    return ModelCheckResponse(
        success=success,
        message=(
            ("凭据已确认保存，连通性已验证" if source == "remote" else "模型连通性已验证")
            if success
            else "连通性测试失败，请检查凭据、网络或模型协议后重试"
        ),
        error_code=None if success else "model_unavailable",
        credential_status=credential_status,
    )


async def require_embedding_ready(
    client: _CheckClient, model_ref: str, *, trace_id: str | None
) -> None:
    """Fail-closed gate used immediately before migration/batch retry enqueue."""
    try:
        result = await check_model(
            client, ModelCheckRequest(model_ref=model_ref), trace_id=trace_id
        )
    except WeKnoraError as exc:
        raise _denied(
            409,
            "weknora_embedding_not_ready",
            "嵌入模型状态无法确认，请先到模型配置完成保存与测试",
        ) from exc
    if not result.success:
        raise _denied(
            409,
            "weknora_embedding_not_ready",
            "嵌入模型凭据未确认或连通性未通过，请先到模型配置完成保存与测试",
        )


def _slot(model_id: str | None, id_meta: dict[str, ModelOut]) -> ModelSlotOut | None:
    if not model_id:
        return None
    meta = id_meta.get(str(model_id))
    return ModelSlotOut(
        model_ref=_model_ref(str(model_id)),
        name=meta.name if meta else None,
        type=meta.type if meta else None,
        provider=meta.provider if meta else None,
    )


async def _id_meta_map(client: _CheckClient, trace_id: str | None) -> dict[str, ModelOut]:
    """server-only model_id → 安全 ModelOut 元数据（用于把 id 映射成安全名称 / 类型）。"""
    raw = await client.list_models(trace_id=trace_id)
    return {str(m["id"]): _to_model_out(m) for m in raw if isinstance(m, dict) and m.get("id")}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _kb_update_config(kb: dict[str, Any]) -> dict[str, Any]:
    """Convert the current KB resource to WeKnora's complete update DTO.

    The current WeKnora PUT handler treats omitted non-pointer fields as zero values, so preserving
    the existing KB resource is required even when KAP changes only one model slot.
    """
    chunking = _dict(kb.get("chunking_config"))
    vlm = dict(_dict(kb.get("vlm_config")))
    asr = dict(_dict(kb.get("asr_config")))
    extract = _dict(kb.get("extract_config"))
    questions = _dict(kb.get("question_generation_config"))
    storage = _dict(kb.get("storage_provider_config"))
    legacy_storage = _dict(kb.get("storage_config"))

    document_splitting: dict[str, Any] = {
        "chunkSize": chunking.get("chunk_size", 512),
        "chunkOverlap": chunking.get("chunk_overlap", 80),
        "separators": chunking.get("separators") or ["\n\n", "\n", "。", "！", "？", ";", "；"],
        "parserEngineRules": chunking.get("parser_engine_rules") or [],
        "enableParentChild": bool(chunking.get("enable_parent_child", False)),
        "parentChunkSize": chunking.get("parent_chunk_size", 0),
        "childChunkSize": chunking.get("child_chunk_size", 0),
    }
    for source_key, target_key in (
        ("strategy", "strategy"),
        ("token_limit", "tokenLimit"),
        ("languages", "languages"),
        ("table_metadata_instructions", "tableMetadataInstructions"),
    ):
        if source_key in chunking:
            document_splitting[target_key] = chunking[source_key]

    provider = storage.get("provider") or legacy_storage.get("provider") or "local"
    return {
        "llmModelId": kb.get("summary_model_id"),
        "embeddingModelId": kb.get("embedding_model_id") or "",
        "vlm_config": vlm,
        "asr_config": asr,
        "documentSplitting": document_splitting,
        "multimodal": {"enabled": bool(vlm.get("enabled", False))},
        "storageProvider": provider,
        "nodeExtract": {
            "enabled": bool(extract.get("enabled", False)),
            "text": extract.get("text") or "",
            "tags": extract.get("tags") or [],
            "nodes": extract.get("nodes") or [],
            "relations": extract.get("relations") or [],
            "customInstructions": extract.get("custom_instructions") or "",
        },
        "questionGeneration": {
            "enabled": bool(questions.get("enabled", False)),
            "questionCount": questions.get("question_count") or 3,
            "customInstructions": questions.get("custom_instructions") or "",
        },
    }


async def list_kb_configs(
    session: AsyncSession,
    client: _CheckClient,
    *,
    trace_id: str | None,
    project_ids: set[uuid.UUID] | None = None,
) -> list[KbConfigOut]:
    statement = select(WeknoraKbMapping).order_by(WeknoraKbMapping.scope)
    if project_ids is not None:
        statement = statement.where(
            WeknoraKbMapping.scope == "project",
            WeknoraKbMapping.project_id.in_(project_ids),
        )
    mappings = list((await session.execute(statement)).scalars().all())
    # id → 安全模型元数据（用于把底座初始化配置里的 server-only id 映射成安全名称）。
    id_meta = await _id_meta_map(client, trace_id)
    # 最近迁移作业（按 mapping 取最新一条，展示迁移进度 / 完成态）。
    recent_migrations = list(
        (
            await session.execute(
                select(IndexingOperationJob)
                .where(IndexingOperationJob.operation_type == "kb_migrate")
                .order_by(IndexingOperationJob.requested_at.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    migration_by_mapping: dict[uuid.UUID, IndexingOperationJob] = {}
    for job in recent_migrations:
        raw = (job.scope_filter or {}).get("mapping_id")
        if not raw:
            continue
        try:
            key = uuid.UUID(str(raw))
        except ValueError:
            continue
        migration_by_mapping.setdefault(key, job)

    project_ids = {m.project_id for m in mappings if m.project_id}
    owner_ids = {m.owner_user_id for m in mappings if m.owner_user_id}
    pmap: dict = {}
    omap: dict = {}
    if project_ids:
        for pid, pname in (
            await session.execute(
                select(Project.id, Project.name).where(Project.id.in_(project_ids))
            )
        ).all():
            pmap[pid] = pname
    if owner_ids:
        for uid, uname in (
            await session.execute(select(User.id, User.name).where(User.id.in_(owner_ids)))
        ).all():
            omap[uid] = uname

    items: list[KbConfigOut] = []
    for mp in mappings:
        migration_job = migration_by_mapping.get(mp.id)
        chat = embedding = rerank = multimodal = None
        config_error = None
        try:
            cfg = await client.get_kb(mp.weknora_kb_id, trace_id=trace_id)
        except WeKnoraError:
            cfg = None
            config_error = "读取底座初始化配置失败，可重试或检查底座可用性"
        if cfg:
            chat = _slot(cfg.get("summary_model_id"), id_meta)
            embedding = _slot(cfg.get("embedding_model_id"), id_meta)
            multimodal = _slot(_dict(cfg.get("vlm_config")).get("model_id"), id_meta)
        items.append(
            KbConfigOut(
                mapping_id=mp.id,
                scope=mp.scope,
                kb_name=mp.kb_name,
                display_name=mp.display_name,
                project_name=pmap.get(mp.project_id) if mp.project_id else None,
                owner_name=omap.get(mp.owner_user_id) if mp.owner_user_id else None,
                mapping_status=mp.status,
                chat=chat,
                embedding=embedding,
                rerank=rerank,
                multimodal=multimodal,
                config_error=config_error,
                migration=(
                    KbMigrationStatusOut(
                        job_id=migration_job.id,
                        job_status=migration_job.status,
                        total_count=migration_job.total_count,
                        success_count=migration_job.success_count,
                        completed_count=int(
                            ((migration_job.scope_filter or {}).get("reconciliation") or {}).get(
                                "completed", migration_job.success_count
                            )
                        ),
                        verified_duplicate_count=int(
                            ((migration_job.scope_filter or {}).get("reconciliation") or {}).get(
                                "verified_duplicate", 0
                            )
                        ),
                        processing_count=int(
                            ((migration_job.scope_filter or {}).get("reconciliation") or {}).get(
                                "processing", 0
                            )
                        ),
                        duplicate_pending_count=int(
                            ((migration_job.scope_filter or {}).get("reconciliation") or {}).get(
                                "duplicate_pending", 0
                            )
                        ),
                        pending_count=int(
                            ((migration_job.scope_filter or {}).get("reconciliation") or {}).get(
                                "pending", migration_job.skipped_count
                            )
                        ),
                        failed_count=migration_job.failed_count,
                        finished_at=migration_job.finished_at,
                    )
                    if migration_job is not None
                    else None
                ),
            )
        )
    return items


async def update_kb_init(
    session: AsyncSession,
    client: _CheckClient,
    mapping_id: uuid.UUID,
    req: KbInitUpdateRequest,
    *,
    trace_id: str | None,
) -> WeknoraKbMapping:
    mp = await session.get(WeknoraKbMapping, mapping_id)
    if mp is None:
        raise _denied(404, "weknora_kb_mapping_not_found", "知识库映射不存在")
    if mp.status == "migrating":
        raise _denied(409, "weknora_kb_migrating", "知识库正在重建迁移，请稍后再配置")
    refs = {
        "chat": req.chat_model_ref,
        "embedding": req.embedding_model_ref,
        "rerank": req.rerank_model_ref,
        "vllm": req.multimodal_ref,
    }
    provided = {k: v for k, v in refs.items() if v}
    if not provided:
        raise _denied(422, "no_model_selected", "至少选择一个模型")
    raw_models = await client.list_models(trace_id=trace_id)
    ref_map = {
        _model_ref(str(model["id"])): model
        for model in raw_models
        if isinstance(model, dict) and model.get("id")
    }
    resolved: dict[str, str] = {}
    for slot, ref in provided.items():
        model = ref_map.get(ref)
        if model is None:
            raise _denied(404, "weknora_model_not_found", "所选模型不存在")
        _validate_model_name(str(model.get("name") or ""), context="配置知识库模型")
        if _alias(model.get("type")) != slot:
            raise _denied(422, "weknora_model_type_mismatch", "所选模型类型与配置项不匹配")
        resolved[slot] = str(model["id"])
    if "rerank" in resolved:
        raise _denied(422, "weknora_model_slot_unsupported", "当前底座不支持按知识库更新重排模型")

    # PUT 接口要求完整配置。先读取现有资源，只在内存中合并本次模型变更。
    current_kb = await client.get_kb(mp.weknora_kb_id, trace_id=trace_id)
    config = _kb_update_config(current_kb)
    if "chat" in resolved:
        config["llmModelId"] = resolved["chat"]
    if not str(config.get("llmModelId") or "").strip():
        raise _denied(
            409, "weknora_kb_chat_model_missing", "知识库当前未配置问答模型，请先选择问答模型"
        )

    current_embedding = str(current_kb.get("embedding_model_id") or mp.embedding_model_id or "")
    next_embedding = resolved.get("embedding", current_embedding)
    # 允许在已有文件的知识库上切换 embedding：配置即时更新并回写绑定；存量文档由
    # 「重新解析」流程重新向量化，切换后先重解析再检索，避免新旧向量空间混用。
    config["embeddingModelId"] = next_embedding

    if "vllm" in resolved:
        vlm = dict(_dict(config.get("vlm_config")))
        vlm.update({"enabled": True, "model_id": resolved["vllm"]})
        config["vlm_config"] = vlm
        config["multimodal"] = {"enabled": True}

    # 失败抛 WeKnoraError；此调用之前不写 mapping，失败时数据库和现有索引保持不变。
    await client.update_initialization_config(mp.weknora_kb_id, config=config, trace_id=trace_id)
    if next_embedding:
        mp.embedding_model_id = next_embedding
    # 成功：init_failed 映射恢复 active（与 ensure-initialized 语义一致）。
    if mp.status == "init_failed":
        mp.status = "active"
    await session.commit()
    return mp


async def get_default_models_out(
    session: AsyncSession, client: _CheckClient, *, trace_id: str | None
) -> DefaultModelsOut:
    """平台默认模型安全视图（PBC-38）：DB 存 server-only id，对外只回安全 model_ref + 名称。"""
    row = await weknora_defaults.get_defaults(session)
    if row is None:
        return DefaultModelsOut()
    id_meta = await _id_meta_map(client, trace_id)
    return DefaultModelsOut(
        embedding=_slot(row.default_embedding_model_id, id_meta),
        rerank=_slot(row.default_rerank_model_id, id_meta),
        chat=_slot(row.default_chat_model_id, id_meta),
        multimodal=_slot(row.default_multimodal_model_id, id_meta),
        updated_at=row.updated_at,
    )


# 各默认槽位期望的前端模型类型别名（PBC-38 类型校验）。multimodal 对应 WeKnora VLLM（别名 vllm）。
_DEFAULT_SLOT_TYPES: dict[str, str] = {
    "embedding": "embedding",
    "rerank": "rerank",
    "chat": "chat",
    "multimodal": "vllm",
}


async def list_model_options(
    session: AsyncSession, client: _CheckClient, *, model_type: str | None, trace_id: str | None
) -> ModelOptionsResponse:
    """顾问侧只读模型选项（PBC-38）：安全展示字段 + is_default 标记 + default_missing 信号。

    复用 `list_models`（已脱敏为 model_ref，无真实 id）。is_default 仅按当前平台默认
    embedding / rerank 的 model_ref 精确匹配标注；其它模型（含 disabled / 伪造）不会被误标。
    default_missing 反映初始化必需的默认 embedding 或 KnowledgeQA 是否未配置（前端据此禁用提交）。
    """
    models = await list_models(client, model_type=model_type, trace_id=trace_id)
    defaults = await weknora_defaults.get_defaults(session)
    emb_default = (defaults.default_embedding_model_id if defaults else None) or None
    chat_default = (defaults.default_chat_model_id if defaults else None) or None
    rr_default = (defaults.default_rerank_model_id if defaults else None) or None
    default_refs: set[str] = set()
    if emb_default:
        default_refs.add(_model_ref(emb_default))
    if rr_default:
        default_refs.add(_model_ref(rr_default))
    items = [
        ModelOptionOut(
            model_ref=m.model_ref,
            name=m.name,
            type=m.type,
            provider=m.provider,
            description=m.description,
            enabled=m.enabled,
            is_default=m.model_ref in default_refs,
        )
        for m in models
    ]
    return ModelOptionsResponse(
        items=items,
        default_missing=not (bool(emb_default) and bool(chat_default)),
    )


async def set_default_models(
    session: AsyncSession,
    client: _CheckClient,
    req: DefaultModelsUpdateRequest,
    *,
    updated_by: uuid.UUID | None,
    trace_id: str | None,
) -> DefaultModelsOut:
    """更新平台默认模型（PBC-38）：前端传 model_ref，后端解析为 server-only id 并校验类型匹配。

    - ref 不存在 → 404 `weknora_model_not_found`；
    - 类型与槽位不匹配（如把 chat 模型设为默认 embedding）→ 422 `weknora_model_type_mismatch`；
    - 校验通过后存 server-only id；返回安全视图（只含 model_ref，绝不回真实 id）。
    """
    # 一次列模型，建 ref → (server-only id, 前端类型别名, 模型名称)。
    raw = await client.list_models(trace_id=trace_id)
    entries: dict[str, tuple[str, str, str]] = {}
    for m in raw:
        if isinstance(m, dict) and m.get("id"):
            mid = str(m["id"])
            entries[_model_ref(mid)] = (mid, _alias(m.get("type")), str(m.get("name") or ""))

    def _resolve(ref: str | None, slot: str) -> str | None:
        if not ref:
            return None
        entry = entries.get(ref)
        if entry is None:
            raise _denied(404, "weknora_model_not_found", "所选模型不存在")
        mid, alias, name = entry
        _validate_model_name(name, context="配置默认模型")
        expected = _DEFAULT_SLOT_TYPES[slot]
        if alias != expected:
            raise _denied(422, "weknora_model_type_mismatch", "所选模型类型与该默认槽位不匹配")
        return mid

    await weknora_defaults.set_defaults(
        session,
        embedding_model_id=_resolve(req.embedding_model_ref, "embedding"),
        rerank_model_id=_resolve(req.rerank_model_ref, "rerank"),
        chat_model_id=_resolve(req.chat_model_ref, "chat"),
        multimodal_id=_resolve(req.multimodal_ref, "multimodal"),
        updated_by=updated_by,
    )
    return await get_default_models_out(session, client, trace_id=trace_id)
