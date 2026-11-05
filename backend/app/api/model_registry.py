"""Administrative onboarding API; secret-bearing validation errors are redacted."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.api.model_connections import _require_operator
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.model_registry import (
    ConnectionInput,
    ConnectionOut,
    ModelInput,
    RegisteredModelOut,
    RegistryOut,
    VersionInput,
)
from app.schemas.permission import CallerContext
from app.services import model_registry as registry
from app.services.generation_models import GenerationModelError
from app.services.model_provider_catalog import CATALOG, RegistryError
from app.services.weknora_client import get_weknora_client


class SafeRegistryRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                return await original(request)
            except RequestValidationError:
                raise HTTPException(
                    422,
                    detail={
                        "denied_reason": "invalid_model_configuration",
                        "message": "配置字段格式不正确，请核对必填项、能力和版本后重试。",
                    },
                ) from None
            except RegistryError as exc:
                raise HTTPException(
                    exc.status, detail={"denied_reason": exc.code, "message": exc.message}
                ) from None
            except GenerationModelError as exc:
                raise HTTPException(
                    exc.status_code, detail={"denied_reason": exc.code, "message": exc.message}
                ) from None
            except IntegrityError:
                raise HTTPException(
                    409,
                    detail={
                        "denied_reason": "configuration_conflict",
                        "message": "配置请求冲突，请刷新后重试。",
                    },
                ) from None
            except SQLAlchemyError:
                raise HTTPException(
                    503,
                    detail={
                        "denied_reason": "registry_storage_unavailable",
                        "message": "模型配置存储暂时不可用，请稍后重试。",
                    },
                ) from None

        return handler


router = APIRouter(
    prefix="/api/v1/admin/model-registry", tags=["model-registry"], route_class=SafeRegistryRoute
)


@router.get("/catalog")
async def catalog(caller: CallerContext = Depends(get_caller_context)):
    _require_operator(caller)
    return {"providers": CATALOG, "capabilities": ["chat", "embedding", "rerank"]}


@router.get("", response_model=RegistryOut)
async def inventory(
    caller: CallerContext = Depends(get_caller_context), session: AsyncSession = Depends(get_db)
):
    _require_operator(caller)
    return await registry.inventory(session)


@router.post("/connections", response_model=ConnectionOut, status_code=201)
async def create_connection(
    body: ConnectionInput,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    _require_operator(caller)
    result = await registry.save_connection(session, body)
    await registry.record_operation(
        session, caller, get_trace_id(request), "connection_created", result["id"]
    )
    return result


@router.put("/connections/{connection_id}", response_model=ConnectionOut)
async def update_connection(
    connection_id: UUID,
    body: ConnectionInput,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    _require_operator(caller)
    result = await registry.save_connection(session, body, connection_id)
    await registry.record_operation(
        session, caller, get_trace_id(request), "connection_updated", connection_id
    )
    return result


@router.post("/models", response_model=RegisteredModelOut, status_code=201)
async def create_model(
    body: ModelInput,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    _require_operator(caller)
    result = await registry.save_model(session, body)
    await registry.record_operation(
        session, caller, get_trace_id(request), "model_saved", result["id"]
    )
    return result


@router.put("/models/{model_id}", response_model=RegisteredModelOut)
async def update_model(
    model_id: UUID,
    body: ModelInput,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    _require_operator(caller)
    result = await registry.save_model(session, body, model_id)
    await registry.record_operation(
        session, caller, get_trace_id(request), "model_updated", model_id
    )
    return result


@router.post("/models/{model_id}/verify", response_model=RegisteredModelOut)
async def verify_model(
    model_id: UUID,
    body: VersionInput,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    _require_operator(caller)
    result = await registry.verify(session, model_id, body.signature)
    await registry.record_operation(
        session, caller, get_trace_id(request), "model_verified", model_id
    )
    return result


@router.post("/models/{model_id}/sync", response_model=RegisteredModelOut)
async def sync_model(
    model_id: UUID,
    body: VersionInput,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    weknora=Depends(get_weknora_client),
):
    _require_operator(caller)
    result = await registry.sync(
        session, model_id, body.signature, weknora, caller.user_id, get_trace_id(request)
    )
    await registry.record_operation(
        session, caller, get_trace_id(request), "model_synced", model_id
    )
    return result
