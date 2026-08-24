"""KAP 内容生成模型管理与业务侧安全选项 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.enums import AuditAction, AuditLogType, CompanyRole
from app.schemas.generation_models import (
    GenerationModelAdminListResponse,
    GenerationModelCreateRequest,
    GenerationModelDeleteResponse,
    GenerationModelOptionOut,
    GenerationModelOptionsResponse,
    GenerationModelSelectionRequest,
    GenerationModelSelectionResponse,
    GenerationModelTestResponse,
    GenerationModelUpdateRequest,
)
from app.schemas.permission import CallerContext
from app.services import audit as audit_service
from app.services import generation_models
from app.services import ingest_status as ingest_status_service
from app.services.desensitization import DesensitizationEngine, get_desensitizer
from app.services.storage import LocalFileStorage, get_storage

router = APIRouter(prefix="/api/v1", tags=["generation-models"])


def _require_admin(caller: CallerContext) -> None:
    if CompanyRole.admin.value not in caller.active_company_roles:
        raise HTTPException(
            403,
            detail={
                "denied_reason": "generation_model_admin_required",
                "message": "仅系统管理员可管理内容生成模型",
            },
        )


def _require_reader(caller: CallerContext) -> None:
    if CompanyRole.admin.value in caller.active_company_roles or caller.can_discover_l5:
        return
    raise HTTPException(
        403,
        detail={
            "denied_reason": "generation_model_admin_required",
            "message": "无权查看内容生成模型配置",
        },
    )


def _wrap(exc: generation_models.GenerationModelError) -> HTTPException:
    return HTTPException(
        exc.status_code,
        detail={"denied_reason": exc.code, "message": exc.message},
    )


@router.get("/generation/model-options", response_model=GenerationModelOptionsResponse)
async def get_generation_model_options(
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> GenerationModelOptionsResponse:
    if not caller.is_business_user and CompanyRole.admin.value not in caller.active_company_roles:
        raise HTTPException(
            403,
            detail={
                "denied_reason": "generation_model_options_forbidden",
                "message": "无权查看内容生成模型选项",
            },
        )
    items = [
        GenerationModelOptionOut(**item)
        for item in await generation_models.safe_generation_model_options(session)
    ]
    return GenerationModelOptionsResponse(
        items=items,
        default_missing=not any(item.is_default and item.enabled for item in items),
    )


@router.get("/admin/generation/models", response_model=GenerationModelAdminListResponse)
async def list_generation_models(
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> GenerationModelAdminListResponse:
    _require_reader(caller)
    try:
        items = [
            GenerationModelOptionOut(**item)
            for item in await generation_models.list_admin_models(session)
        ]
    except SQLAlchemyError:
        raise HTTPException(
            503,
            detail={
                "denied_reason": "generation_model_storage_unavailable",
                "message": "模型列表加载失败，请刷新或检查模型连接",
            },
        ) from None
    return GenerationModelAdminListResponse(items=items, total=len(items))


@router.post("/admin/generation/models", response_model=GenerationModelOptionOut, status_code=201)
async def create_generation_model(
    body: GenerationModelCreateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> GenerationModelOptionOut:
    _require_admin(caller)
    try:
        item = await generation_models.create_model(
            session,
            display_name=body.display_name,
            provider=body.provider,
            model_name=body.model_name,
            base_url=body.base_url.get_secret_value(),
            api_key=body.api_key.get_secret_value(),
            enabled=body.enabled,
            make_default=body.make_default,
            actor_id=caller.user_id,
        )
    except generation_models.GenerationModelError as exc:
        raise _wrap(exc) from exc
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.generation_model_created.value,
        trace_id=get_trace_id(request),
        target_type="content_generation_model",
        extra={"model_ref": item["model_ref"]},
    )
    await session.commit()
    return GenerationModelOptionOut(**item)


@router.put("/admin/generation/models/{model_ref}", response_model=GenerationModelOptionOut)
async def update_generation_model(
    model_ref: str,
    body: GenerationModelUpdateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> GenerationModelOptionOut:
    _require_admin(caller)
    try:
        item = await generation_models.update_model(
            session,
            model_ref,
            display_name=body.display_name,
            provider=body.provider,
            model_name=body.model_name,
            base_url=body.base_url.get_secret_value() if body.base_url else None,
            api_key=body.api_key.get_secret_value() if body.api_key else None,
            enabled=body.enabled,
            actor_id=caller.user_id,
        )
    except generation_models.GenerationModelError as exc:
        raise _wrap(exc) from exc
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.generation_model_updated.value,
        trace_id=get_trace_id(request),
        target_type="content_generation_model",
        extra={"model_ref": item["model_ref"]},
    )
    await session.commit()
    return GenerationModelOptionOut(**item)


@router.delete("/admin/generation/models/{model_ref}", response_model=GenerationModelDeleteResponse)
async def delete_generation_model(
    model_ref: str,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> GenerationModelDeleteResponse:
    _require_admin(caller)
    try:
        await generation_models.delete_model(session, model_ref)
    except generation_models.GenerationModelError as exc:
        raise _wrap(exc) from exc
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.generation_model_deleted.value,
        trace_id=get_trace_id(request),
        target_type="content_generation_model",
        extra={"model_ref": model_ref},
    )
    await session.commit()
    return GenerationModelDeleteResponse()


@router.post(
    "/admin/generation/models/{model_ref}/test",
    response_model=GenerationModelTestResponse,
)
async def test_generation_model(
    model_ref: str,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> GenerationModelTestResponse:
    _require_admin(caller)
    try:
        result = await generation_models.test_model_connection(session, model_ref)
    except generation_models.GenerationModelError as exc:
        raise _wrap(exc) from exc
    await session.commit()
    return GenerationModelTestResponse(**result)


@router.put("/admin/generation/default-model", response_model=GenerationModelSelectionResponse)
async def put_generation_default_model(
    body: GenerationModelSelectionRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
    desensitizer: DesensitizationEngine = Depends(get_desensitizer),
) -> GenerationModelSelectionResponse:
    _require_admin(caller)
    try:
        item = await generation_models.set_default_model(
            session, body.model_ref, actor_id=caller.user_id
        )
    except generation_models.GenerationModelError as exc:
        raise _wrap(exc) from exc
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.generation_model_default_updated.value,
        trace_id=get_trace_id(request),
        target_type="content_generation_settings",
        extra={"model_ref": item["model_ref"] if item else None},
    )
    await session.commit()
    if item is not None:
        await ingest_status_service.resume_waiting_generation_tasks(
            session,
            storage=storage,
            llm=await generation_models.resolve_generation_llm_client(session),
            desensitizer=desensitizer,
            trace_id=get_trace_id(request),
        )
    return GenerationModelSelectionResponse(
        current_default=GenerationModelOptionOut(**item) if item else None,
        configured=item is not None,
    )
