"""企微微盘扫描 API（R6 Path A，契约 §17）。

- GET   /api/v1/admin/wecom-scan/configs                         （admin / boss / 咨询总监）
- PATCH /api/v1/admin/wecom-scan/configs/{config_id}            （admin；启停）
- POST  /api/v1/admin/wecom-scan/configs/{config_id}/scan       （admin；手动触发，可带 Idempotency-Key）
- GET   /api/v1/admin/wecom-scan/configs/{config_id}/records    （admin / boss / 咨询总监）

权限委托 service；响应只含安全运营元数据，绝不含 storage_ref / 下载 URL / file_id / token。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.permission import CallerContext
from app.schemas.wecom import (
    WecomOwnerOptionsResponse,
    WecomProjectOptionsResponse,
    WecomScanConfigCreateBody,
    WecomScanConfigsResponse,
    WecomScanConfigOut,
    WecomScanConfigUpdateBody,
    WecomScanRecordOut,
    WecomScanRecordsResponse,
)
from app.services import wecom_scan as scan_service
from app.services.desensitization import get_desensitizer
from app.services.llm_client import get_llm_client
from app.services.storage import get_storage
from app.services.wecom_client import get_wecom_drive_client

router = APIRouter(prefix="/api/v1/admin/wecom-scan", tags=["wecom-scan"])


@router.get("/configs", response_model=WecomScanConfigsResponse)
async def list_configs(
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> WecomScanConfigsResponse:
    return await scan_service.list_configs(session, caller)


@router.get("/project-options", response_model=WecomProjectOptionsResponse)
async def list_project_options(
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> WecomProjectOptionsResponse:
    """目标项目候选（active 项目 id + 名称），供创建/编辑配置选择。读权限同配置读。"""
    return await scan_service.list_project_options(session, caller)


@router.get("/owner-options", response_model=WecomOwnerOptionsResponse)
async def list_owner_options(
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> WecomOwnerOptionsResponse:
    """业务归属人候选（active 业务用户，排除纯 admin）。读权限同配置读。"""
    return await scan_service.list_owner_options(session, caller)


@router.post("/configs", response_model=WecomScanConfigOut, status_code=201)
async def create_config(
    body: WecomScanConfigCreateBody,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> WecomScanConfigOut:
    """创建扫描目录配置（仅 admin，配置操作人 = 审计 actor）。`created_by` 写入校验通过的
    业务归属人（task_owner_user_id），即扫描产物 path_a_wecom 任务的归属人。"""
    return await scan_service.create_config(session, caller, body, get_trace_id(request))


@router.patch("/configs/{config_id}", response_model=WecomScanConfigOut)
async def update_config(
    config_id: uuid.UUID,
    body: WecomScanConfigUpdateBody,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> WecomScanConfigOut:
    return await scan_service.update_config(
        session, caller, config_id, body, get_trace_id(request)
    )


@router.post("/configs/{config_id}/scan", response_model=WecomScanRecordOut)
async def trigger_scan(
    config_id: uuid.UUID,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    drive=Depends(get_wecom_drive_client),
    storage=Depends(get_storage),
    llm=Depends(get_llm_client),
    desensitizer=Depends(get_desensitizer),
) -> WecomScanRecordOut:
    return await scan_service.trigger_scan(
        session, caller, config_id,
        drive=drive, storage=storage, llm=llm, desensitizer=desensitizer,
        trace_id=get_trace_id(request), idempotency_key=idempotency_key,
    )


@router.get("/configs/{config_id}/records", response_model=WecomScanRecordsResponse)
async def list_records(
    config_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> WecomScanRecordsResponse:
    return await scan_service.list_records(session, caller, config_id)
