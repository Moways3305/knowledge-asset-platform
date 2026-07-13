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
from typing import TYPE_CHECKING, TypeAlias

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.identity import Project, User
from app.models.weknora import WeknoraKbMapping
from app.schemas.weknora_admin import (
    DefaultModelsOut,
    DefaultModelsUpdateRequest,
    KbConfigOut,
    KbInitUpdateRequest,
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
    )


async def list_providers(
    client: _CheckClient, *, model_type: str | None, trace_id: str | None
) -> list[ProviderOut]:
    raw = await client.list_model_providers(model_type, trace_id=trace_id)
    out: list[ProviderOut] = []
    for p in raw:
        if not isinstance(p, dict):
            continue
        # 只取安全字段：value/label/description/modelTypes。**不**透传 defaultUrls（含 provider host）。
        out.append(
            ProviderOut(
                value=str(p.get("value") or ""),
                label=str(p.get("label") or p.get("value") or ""),
                description=p.get("description"),
                model_types=[str(t) for t in (p.get("modelTypes") or p.get("model_types") or [])],
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
    created = await client.create_model(_build_model_payload(req), trace_id=trace_id)
    mid = created.get("id") if isinstance(created, dict) else None
    if not mid:
        # 底座未返回有效 id → fail-closed：不生成 model_ref 假成功（调用方据此不写成功审计）。
        raise _denied(
            502, "weknora_model_create_no_id", "底座创建模型未返回有效标识，模型未确认创建成功"
        )
    return ModelMutateResponse(
        model_ref=_model_ref(str(mid)),
        name=str(created.get("name") or req.name),
        type=req.type,
        provider=req.provider,
    )


async def update_model(
    client: _CheckClient, model_ref: str, req: ModelMutateRequest, *, trace_id: str | None
) -> ModelMutateResponse:
    model_id = await _resolve_ref(client, model_ref, trace_id)
    if model_id is None:
        raise _denied(404, "weknora_model_not_found", "模型不存在")
    _validate_update_sensitive_inputs(req)
    await client.update_model(
        model_id, _build_model_payload(req, keep_blank_sensitive=False), trace_id=trace_id
    )
    return ModelMutateResponse(
        model_ref=_model_ref(model_id),
        name=req.name,
        type=req.type,
        provider=req.provider,
    )


async def delete_model(client: _CheckClient, model_ref: str, *, trace_id: str | None) -> None:
    model_id = await _resolve_ref(client, model_ref, trace_id)
    if model_id is None:
        raise _denied(404, "weknora_model_not_found", "模型不存在")
    await client.delete_model(model_id, trace_id=trace_id)


def _safe_check_message(message: str, req: ModelCheckRequest) -> str:
    """连通性测试文案兜底脱敏：剔除可能回显的 key / url。"""
    msg = message
    for v in (req.api_key, req.api_url):
        if v and v in msg:
            msg = msg.replace(v, "[redacted]")
    return msg


async def check_model(
    client: _CheckClient, req: ModelCheckRequest, *, trace_id: str | None
) -> ModelCheckResponse:
    fn = {
        "chat": client.check_remote_model,
        "embedding": client.test_embedding_model,
        "rerank": client.check_rerank_model,
        "vllm": client.test_multimodal_model,
    }.get(req.model_type)
    if fn is None:
        raise _denied(422, "invalid_model_type", "非法的模型类型")
    res = await fn(api_url=req.api_url, api_key=req.api_key, model=req.model, trace_id=trace_id)
    success = bool(res.get("success", True)) if isinstance(res, dict) else False
    message = str((res or {}).get("message") or ("可用" if success else "不可用"))
    return ModelCheckResponse(success=success, message=_safe_check_message(message, req))


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


async def list_kb_configs(
    session: AsyncSession, client: _CheckClient, *, trace_id: str | None
) -> list[KbConfigOut]:
    mappings = list(
        (await session.execute(select(WeknoraKbMapping).order_by(WeknoraKbMapping.scope)))
        .scalars()
        .all()
    )
    # id → 安全模型元数据（用于把底座初始化配置里的 server-only id 映射成安全名称）。
    id_meta = await _id_meta_map(client, trace_id)

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
        chat = embedding = rerank = multimodal = None
        config_error = None
        try:
            cfg = await client.get_initialization_config(mp.weknora_kb_id, trace_id=trace_id)
        except WeKnoraError:
            cfg = None
            config_error = "读取底座初始化配置失败，可重试或检查底座可用性"
        if cfg:
            chat = _slot(cfg.get("chat_model_id"), id_meta)
            embedding = _slot(cfg.get("embedding_model_id"), id_meta)
            rerank = _slot(cfg.get("rerank_model_id"), id_meta)
            multimodal = _slot(cfg.get("multimodal_id"), id_meta)
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
    refs = {
        "chat_model_id": req.chat_model_ref,
        "embedding_model_id": req.embedding_model_ref,
        "rerank_model_id": req.rerank_model_ref,
        "multimodal_id": req.multimodal_ref,
    }
    provided = {k: v for k, v in refs.items() if v}
    if not provided:
        raise _denied(422, "no_model_selected", "至少选择一个模型")
    ref_map = await _ref_to_id_map(client, trace_id)
    resolved: dict = {}
    for slot, ref in provided.items():
        mid = ref_map.get(ref)
        if mid is None:
            raise _denied(404, "weknora_model_not_found", "所选模型不存在")
        resolved[slot] = mid
    # 调底座更新初始化配置（失败抛 WeKnoraError，API 转安全 502，mapping 状态不变）。
    await client.update_initialization_config(mp.weknora_kb_id, trace_id=trace_id, **resolved)
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
    # 一次列模型，建 ref → (server-only id, 前端类型别名)。
    raw = await client.list_models(trace_id=trace_id)
    entries: dict[str, tuple[str, str]] = {}
    for m in raw:
        if isinstance(m, dict) and m.get("id"):
            mid = str(m["id"])
            entries[_model_ref(mid)] = (mid, _alias(m.get("type")))

    def _resolve(ref: str | None, slot: str) -> str | None:
        if not ref:
            return None
        entry = entries.get(ref)
        if entry is None:
            raise _denied(404, "weknora_model_not_found", "所选模型不存在")
        mid, alias = entry
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
