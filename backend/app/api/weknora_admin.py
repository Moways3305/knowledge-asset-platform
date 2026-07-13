"""模型配置中心 API（admin-only）。

让 admin 不登 WeKnora 控制台即可管理 provider / 模型 / KB 初始化配置 + 连通性测试。

权限：纯系统 admin（company role = admin）。普通业务角色（顾问 / 项目经理 / coach / 治理）
一律 403——模型配置是底座运营，不是业务知识权限；admin 的此权限**不**等于业务原文权限。

安全：响应 / 审计 / 错误**绝不**含 api_key / base_url 真实值 / 真实 model_id / weknora_kb_id /
内部存储引用 / 原始 payload。WeKnora 未配置 → 安全 503（只回 missing config 项名）。
"""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.config import get_settings
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.enums import AuditAction, AuditLogType, CompanyRole
from app.schemas.permission import CallerContext
from app.schemas.weknora_admin import (
    DefaultModelsOut,
    DefaultModelsUpdateRequest,
    KbConfigListResponse,
    KbInitUpdateRequest,
    KbInitUpdateResponse,
    ModelCheckRequest,
    ModelCheckResponse,
    ModelDeleteResponse,
    ModelListResponse,
    ModelMutateRequest,
    ModelMutateResponse,
    ProviderListResponse,
)
from app.services import audit as audit_service
from app.services import weknora_models
from app.services.weknora_client import (
    NullWeKnoraClient,
    WeKnoraClient,
    WeKnoraError,
    get_weknora_client,
    weknora_enabled,
)

router = APIRouter(prefix="/api/v1/admin/weknora", tags=["weknora-admin"])


def _require_admin(caller: CallerContext) -> None:
    if CompanyRole.admin.value not in caller.active_company_roles:
        raise HTTPException(
            403,
            detail={
                "denied_reason": "weknora_admin_required",
                "message": "仅系统管理员可管理模型配置",
            },
        )


def _require_admin_or_governance(caller: CallerContext) -> None:
    """读平台默认模型：admin 或业务治理角色（boss / 咨询总监）。普通顾问无权。"""
    roles = set(caller.active_company_roles)
    allowed = {
        CompanyRole.admin.value,
        CompanyRole.boss.value,
        CompanyRole.consulting_director.value,
    }
    if not (roles & allowed):
        raise HTTPException(
            403,
            detail={
                "denied_reason": "weknora_admin_required",
                "message": "无权查看平台默认模型配置",
            },
        )


def _require_enabled() -> None:
    """WeKnora 未配置 → 安全 503，只回 missing config 项名（不回值）。"""
    if not weknora_enabled():
        missing = ["WEKNORA_BASE_URL", "WEKNORA_API_KEY"]
        s = get_settings()
        miss = [
            m
            for m, v in (
                ("WEKNORA_BASE_URL", s.weknora_base_url),
                ("WEKNORA_API_KEY", s.weknora_api_key),
            )
            if not v
        ]
        raise HTTPException(
            503,
            detail={
                "denied_reason": "weknora_not_configured",
                "message": "WeKnora 未配置",
                "missing_config": miss or missing,
            },
        )


# 安全 code 形态：短小标识符（字母/数字/下划线）。上游 message **一律不回显**——它可能回显
# 请求里的 api_key / base_url / model_id / kb_id / 原始 payload，不符合 安全边界。
_SAFE_CODE_RE = re.compile(r"^[a-z0-9_]{1,40}$")
_WEKNORA_SAFE_MESSAGE = "底座模型配置调用失败，请检查配置或稍后重试"


def _wrap_weknora(exc: WeKnoraError, *, kb_update: bool = False) -> HTTPException:
    """WeKnora 错误 → 安全 HTTP：未配置 → 503；其余 → 502 固定安全文案。

    **绝不**把上游 `exc.message` 原样返回（可能含 api_key / base_url / model_id / kb_id / payload）。
    denied_reason 仅在 code 为简单安全标识符时透传，否则归一为 weknora_call_failed。
    """
    if exc.code == "weknora_not_configured":
        return HTTPException(
            503, detail={"denied_reason": "weknora_not_configured", "message": "WeKnora 未配置"}
        )
    if kb_update:
        if exc.status_code is not None and 400 <= exc.status_code < 500:
            return HTTPException(
                502,
                detail={
                    "denied_reason": "weknora_kb_config_rejected",
                    "message": "知识库配置被底座拒绝，请检查所选模型是否兼容",
                },
            )
        return HTTPException(
            502,
            detail={
                "denied_reason": "weknora_model_service_unavailable",
                "message": "模型连接服务暂不可用，请稍后重试",
            },
        )
    safe_code = exc.code if _SAFE_CODE_RE.match(str(exc.code or "")) else "weknora_call_failed"
    return HTTPException(502, detail={"denied_reason": safe_code, "message": _WEKNORA_SAFE_MESSAGE})


@router.get("/providers", response_model=ProviderListResponse)
async def list_providers(
    request: Request,
    model_type: str | None = None,
    caller: CallerContext = Depends(get_caller_context),
    weknora: WeKnoraClient | NullWeKnoraClient = Depends(get_weknora_client),
) -> ProviderListResponse:
    _require_admin(caller)
    _require_enabled()
    try:
        items = await weknora_models.list_providers(
            weknora, model_type=model_type, trace_id=get_trace_id(request)
        )
    except WeKnoraError as exc:
        raise _wrap_weknora(exc)
    return ProviderListResponse(items=items)


@router.get("/models", response_model=ModelListResponse)
async def list_models(
    request: Request,
    type: str | None = None,
    caller: CallerContext = Depends(get_caller_context),
    weknora: WeKnoraClient | NullWeKnoraClient = Depends(get_weknora_client),
) -> ModelListResponse:
    _require_admin(caller)
    _require_enabled()
    try:
        items = await weknora_models.list_models(
            weknora, model_type=type, trace_id=get_trace_id(request)
        )
    except WeKnoraError as exc:
        raise _wrap_weknora(exc)
    return ModelListResponse(items=items)


@router.post("/models", response_model=ModelMutateResponse)
async def create_model(
    req: ModelMutateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    weknora: WeKnoraClient | NullWeKnoraClient = Depends(get_weknora_client),
) -> ModelMutateResponse:
    _require_admin(caller)
    _require_enabled()
    trace_id = get_trace_id(request)
    try:
        res = await weknora_models.create_model(weknora, req, trace_id=trace_id)
    except WeKnoraError as exc:
        raise _wrap_weknora(exc)
    # 审计只放安全字段（名称 / 类型 / provider），绝不含 api_key / base_url / 真实 id。
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.weknora_model_created.value,
        trace_id=trace_id,
        target_type="weknora_model",
        extra={"name": res.name, "type": res.type, "provider": res.provider},
    )
    await session.commit()
    return res


@router.put("/models/{model_ref}", response_model=ModelMutateResponse)
async def update_model(
    model_ref: str,
    req: ModelMutateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    weknora: WeKnoraClient | NullWeKnoraClient = Depends(get_weknora_client),
) -> ModelMutateResponse:
    _require_admin(caller)
    _require_enabled()
    trace_id = get_trace_id(request)
    try:
        res = await weknora_models.update_model(weknora, model_ref, req, trace_id=trace_id)
    except WeKnoraError as exc:
        raise _wrap_weknora(exc)
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.weknora_model_updated.value,
        trace_id=trace_id,
        target_type="weknora_model",
        extra={"name": res.name, "type": res.type, "provider": res.provider},
    )
    await session.commit()
    return res


@router.delete("/models/{model_ref}", response_model=ModelDeleteResponse)
async def delete_model(
    model_ref: str,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    weknora: WeKnoraClient | NullWeKnoraClient = Depends(get_weknora_client),
) -> ModelDeleteResponse:
    _require_admin(caller)
    _require_enabled()
    trace_id = get_trace_id(request)
    try:
        await weknora_models.delete_model(weknora, model_ref, trace_id=trace_id)
    except WeKnoraError as exc:
        raise _wrap_weknora(exc)
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.weknora_model_deleted.value,
        trace_id=trace_id,
        target_type="weknora_model",
    )
    await session.commit()
    return ModelDeleteResponse(deleted=True)


@router.post("/models/check", response_model=ModelCheckResponse)
async def check_model(
    req: ModelCheckRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    weknora: WeKnoraClient | NullWeKnoraClient = Depends(get_weknora_client),
) -> ModelCheckResponse:
    _require_admin(caller)
    _require_enabled()
    try:
        return await weknora_models.check_model(weknora, req, trace_id=get_trace_id(request))
    except WeKnoraError as exc:
        raise _wrap_weknora(exc)


@router.get("/kb-configs", response_model=KbConfigListResponse)
async def list_kb_configs(
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    weknora: WeKnoraClient | NullWeKnoraClient = Depends(get_weknora_client),
) -> KbConfigListResponse:
    _require_admin(caller)
    _require_enabled()
    try:
        items = await weknora_models.list_kb_configs(
            session, weknora, trace_id=get_trace_id(request)
        )
    except WeKnoraError as exc:
        raise _wrap_weknora(exc)
    return KbConfigListResponse(items=items)


@router.put("/kb-configs/{mapping_id}/initialization", response_model=KbInitUpdateResponse)
async def update_kb_init(
    mapping_id: uuid.UUID,
    req: KbInitUpdateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    weknora: WeKnoraClient | NullWeKnoraClient = Depends(get_weknora_client),
) -> KbInitUpdateResponse:
    _require_admin(caller)
    _require_enabled()
    trace_id = get_trace_id(request)
    try:
        mp = await weknora_models.update_kb_init(
            session, weknora, mapping_id, req, trace_id=trace_id
        )
    except WeKnoraError as exc:
        raise _wrap_weknora(exc, kb_update=True)
    # 审计只放安全字段（mapping id / scope / 状态），绝不含 weknora_kb_id / 真实 model_id。
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.weknora_kb_config_updated.value,
        trace_id=trace_id,
        target_type="weknora_kb_mapping",
        target_id=mp.id,
        extra={"scope": mp.scope, "mapping_status": mp.status},
        project_id=mp.project_id,
    )
    await session.commit()
    return KbInitUpdateResponse(mapping_id=mp.id, mapping_status=mp.status, updated=True)


@router.get("/default-models", response_model=DefaultModelsOut)
async def get_default_models(
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    weknora: WeKnoraClient | NullWeKnoraClient = Depends(get_weknora_client),
) -> DefaultModelsOut:
    """读平台默认模型（admin / boss / 咨询总监）。只回安全 model_ref + 名称，无真实 model_id。"""
    _require_admin_or_governance(caller)
    _require_enabled()
    try:
        return await weknora_models.get_default_models_out(
            session, weknora, trace_id=get_trace_id(request)
        )
    except WeKnoraError as exc:
        raise _wrap_weknora(exc)


@router.put("/default-models", response_model=DefaultModelsOut)
async def put_default_models(
    req: DefaultModelsUpdateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    weknora: WeKnoraClient | NullWeKnoraClient = Depends(get_weknora_client),
) -> DefaultModelsOut:
    """改平台默认模型（仅 admin）。前端传 model_ref，后端解析真实 id + 校验类型；响应/审计无真实 id。"""
    _require_admin(caller)
    _require_enabled()
    trace_id = get_trace_id(request)
    try:
        out = await weknora_models.set_default_models(
            session, weknora, req, updated_by=caller.user_id, trace_id=trace_id
        )
    except WeKnoraError as exc:
        raise _wrap_weknora(exc)
    # 审计只放安全 model_ref（对底座 id 不可逆）+ 槽位名，绝不含真实 model_id / api_key / base_url。
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.weknora_default_models_updated.value,
        trace_id=trace_id,
        target_type="weknora_default_models",
        extra={
            "embedding_ref": out.embedding.model_ref if out.embedding else None,
            "rerank_ref": out.rerank.model_ref if out.rerank else None,
            "chat_ref": out.chat.model_ref if out.chat else None,
            "multimodal_ref": out.multimodal.model_ref if out.multimodal else None,
        },
    )
    await session.commit()
    return out
