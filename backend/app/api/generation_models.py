"""KAP 内容生成模型选项 API。

与 WeKnora 知识库模型分离：这里只描述平台标题 / 摘要 / 标签建议所用的外部 LLM
能力状态。响应只含安全 model_ref、provider 名和展示名，不含 api_key/base_url。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_caller_context
from app.schemas.enums import CompanyRole
from app.schemas.generation_models import (
    GenerationModelOptionOut,
    GenerationModelOptionsResponse,
    GenerationModelSelectionRequest,
    GenerationModelSelectionResponse,
)
from app.schemas.permission import CallerContext
from app.services import generation_models

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


@router.get("/generation/model-options", response_model=GenerationModelOptionsResponse)
async def get_generation_model_options(
    caller: CallerContext = Depends(get_caller_context),
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
        GenerationModelOptionOut(**i) for i in generation_models.safe_generation_model_options()
    ]
    return GenerationModelOptionsResponse(items=items, default_missing=len(items) == 0)


@router.put("/admin/generation/default-model", response_model=GenerationModelSelectionResponse)
async def put_generation_default_model(
    req: GenerationModelSelectionRequest,
    caller: CallerContext = Depends(get_caller_context),
) -> GenerationModelSelectionResponse:
    _require_admin(caller)
    items = generation_models.safe_generation_model_options()
    current = items[0] if items else None
    if req.model_ref and (current is None or req.model_ref != current["model_ref"]):
        raise HTTPException(
            422,
            detail={
                "denied_reason": "generation_model_ref_invalid",
                "message": "内容生成模型引用无效或当前不可用",
            },
        )
    return GenerationModelSelectionResponse(
        current_default=GenerationModelOptionOut(**current) if current else None,
        configured=current is not None,
    )
