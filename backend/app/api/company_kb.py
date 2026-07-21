"""公司知识库显式创建与状态 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.company_kb import CompanyKbCreateRequest, CompanyKbOut
from app.schemas.permission import CallerContext
from app.services import company_kb as company_kb_service
from app.services.weknora_client import (
    NullWeKnoraClient,
    WeKnoraClient,
    get_weknora_client,
)

router = APIRouter(prefix="/api/v1/company/knowledge-base", tags=["company-knowledge-base"])


@router.get("", response_model=CompanyKbOut)
async def get_company_kb(
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> CompanyKbOut:
    return await company_kb_service.get_company_kb(session, caller)


@router.post("", response_model=CompanyKbOut)
async def create_company_kb(
    req: CompanyKbCreateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    weknora: WeKnoraClient | NullWeKnoraClient = Depends(get_weknora_client),
) -> CompanyKbOut:
    return await company_kb_service.create_company_kb(
        session,
        weknora,
        caller,
        display_name=req.display_name,
        trace_id=get_trace_id(request),
    )


@router.delete("", status_code=204)
async def delete_company_kb(
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    weknora: WeKnoraClient | NullWeKnoraClient = Depends(get_weknora_client),
):
    await company_kb_service.delete_company_kb(
        session,
        weknora,
        caller,
        trace_id=get_trace_id(request),
    )
    return None
