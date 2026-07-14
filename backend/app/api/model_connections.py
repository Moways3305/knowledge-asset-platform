"""Administrator API for external LLM connections and their business default."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.enums import AuditAction, AuditLogType, CompanyRole
from app.schemas.model_connections import (
    ModelConnectionCreateRequest,
    ModelConnectionListResponse,
    ModelConnectionOut,
    ModelConnectionTestResponse,
    ModelConnectionUpdateRequest,
    ModelUsageAssignmentsOut,
    ModelUsageAssignmentsUpdate,
)
from app.schemas.permission import CallerContext
from app.services import audit as audit_service
from app.services import generation_models, model_connections

router = APIRouter(prefix="/api/v1/admin/model-connections", tags=["model-connections"])


def _require_admin(caller: CallerContext) -> None:
    if CompanyRole.admin.value not in caller.active_company_roles:
        raise HTTPException(
            403,
            detail={
                "denied_reason": "model_connection_admin_required",
                "message": "仅系统管理员可管理模型连接",
            },
        )


def _require_reader(caller: CallerContext) -> None:
    if CompanyRole.admin.value in caller.active_company_roles or caller.can_discover_l5:
        return
    raise HTTPException(
        403,
        detail={
            "denied_reason": "model_connection_reader_required",
            "message": "无权查看模型连接",
        },
    )


def _wrap_connection(exc: model_connections.ModelConnectionError) -> HTTPException:
    return HTTPException(
        exc.status_code, detail={"denied_reason": exc.code, "message": exc.message}
    )


def _wrap_generation(exc: generation_models.GenerationModelError) -> HTTPException:
    return HTTPException(
        exc.status_code, detail={"denied_reason": exc.code, "message": exc.message}
    )


def _safe_dependency_error() -> HTTPException:
    return HTTPException(
        503,
        detail={
            "denied_reason": "model_connection_storage_unavailable",
            "message": "模型连接暂时无法加载，请刷新或检查模型连接服务",
        },
    )


@router.get("", response_model=ModelConnectionListResponse)
async def get_connections(
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ModelConnectionListResponse:
    _require_reader(caller)
    try:
        items, warning = await model_connections.list_connections(session)
    except SQLAlchemyError:
        raise _safe_dependency_error()
    return ModelConnectionListResponse(
        items=[ModelConnectionOut(**item) for item in items],
        total=len(items),
        warning=warning,
    )


@router.post("", response_model=ModelConnectionOut, status_code=201)
async def post_connection(
    body: ModelConnectionCreateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ModelConnectionOut:
    _require_admin(caller)
    try:
        item = await model_connections.create_connection(
            session,
            display_name=body.display_name,
            capability_type=body.capability_type,
            provider=body.provider,
            model_name=body.model_name,
            base_url=body.base_url.get_secret_value(),
            api_key=body.api_key.get_secret_value(),
            enabled=body.enabled,
            actor_id=caller.user_id,
        )
    except model_connections.ModelConnectionError as exc:
        raise _wrap_connection(exc)
    except generation_models.GenerationModelError as exc:
        raise _wrap_generation(exc)
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.generation_model_created.value,
        trace_id=get_trace_id(request),
        target_type="model_connection",
        extra={"model_ref": item["model_ref"], "capability_type": item["capability_type"]},
    )
    await session.commit()
    return ModelConnectionOut(**item)


@router.put("/items/{model_ref}", response_model=ModelConnectionOut)
async def put_connection(
    model_ref: str,
    body: ModelConnectionUpdateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ModelConnectionOut:
    _require_admin(caller)
    try:
        item = await model_connections.update_connection(
            session,
            model_ref,
            display_name=body.display_name,
            capability_type=body.capability_type,
            provider=body.provider,
            model_name=body.model_name,
            base_url=body.base_url.get_secret_value() if body.base_url else None,
            api_key=body.api_key.get_secret_value() if body.api_key else None,
            enabled=body.enabled,
            actor_id=caller.user_id,
        )
    except model_connections.ModelConnectionError as exc:
        raise _wrap_connection(exc)
    except generation_models.GenerationModelError as exc:
        raise _wrap_generation(exc)
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.generation_model_updated.value,
        trace_id=get_trace_id(request),
        target_type="model_connection",
        extra={"model_ref": item["model_ref"], "capability_type": item["capability_type"]},
    )
    await session.commit()
    return ModelConnectionOut(**item)


@router.post("/items/{model_ref}/test", response_model=ModelConnectionTestResponse)
async def post_connection_test(
    model_ref: str,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ModelConnectionTestResponse:
    _require_admin(caller)
    try:
        result = await model_connections.test_connection(session, model_ref)
    except model_connections.ModelConnectionError as exc:
        raise _wrap_connection(exc)
    except generation_models.GenerationModelError as exc:
        raise _wrap_generation(exc)
    return ModelConnectionTestResponse(**result)


@router.get("/usages/current", response_model=ModelUsageAssignmentsOut)
async def get_usages(
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ModelUsageAssignmentsOut:
    _require_reader(caller)
    try:
        result = await model_connections.get_usage_assignments(session)
    except SQLAlchemyError:
        raise _safe_dependency_error()
    return ModelUsageAssignmentsOut(**result)


@router.put("/usages/current", response_model=ModelUsageAssignmentsOut)
async def put_usages(
    body: ModelUsageAssignmentsUpdate,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ModelUsageAssignmentsOut:
    _require_admin(caller)
    try:
        result = await model_connections.set_usage_assignments(
            session,
            external_llm_default_ref=body.external_llm_default_ref,
            actor_id=caller.user_id,
        )
    except model_connections.ModelConnectionError as exc:
        raise _wrap_connection(exc)
    except generation_models.GenerationModelError as exc:
        raise _wrap_generation(exc)
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.generation_model_default_updated.value,
        trace_id=get_trace_id(request),
        target_type="model_usage_assignments",
        extra={
            "external_llm_default_ref": body.external_llm_default_ref,
        },
    )
    await session.commit()
    return ModelUsageAssignmentsOut(**result)
