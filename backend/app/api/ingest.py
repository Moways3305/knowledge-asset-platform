"""入库流水线 API。

只做 upload / ai-result / confirm + 可选 admin 只读列表。权限委托 service，
不写权限矩阵；不返回内部存储引用 / 真实上传下载 URL。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.ingest import (
    AdminIngestListResponse,
    IngestAiResultResponse,
    IngestConfirmRequest,
    IngestConfirmResponse,
    IngestParseRefreshResponse,
    IngestUploadResponse,
    PendingIngestListResponse,
)
from app.schemas.permission import CallerContext
from app.services import ingest as ingest_service
from app.services.desensitization import DesensitizationEngine, get_desensitizer
from app.services.llm_client import LLMClient, NullLLMClient, get_llm_client
from app.services.storage import MAX_UPLOAD_BYTES, LocalFileStorage, get_storage
from app.services.weknora_client import (
    NullWeKnoraClient,
    WeKnoraClient,
    get_weknora_client,
)

router = APIRouter(prefix="/api/v1", tags=["ingest"])


@router.post("/ingest/upload", response_model=IngestUploadResponse)
async def create_upload(
    request: Request,
    file: UploadFile = File(...),
    target_scope: str | None = Form(default=None),
    target_project_id: uuid.UUID | None = Form(default=None),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
    llm: LLMClient | NullLLMClient = Depends(get_llm_client),
    desensitizer: DesensitizationEngine = Depends(get_desensitizer),
) -> IngestUploadResponse:
    """Path B 本地上传：接收真实文件字节（multipart/form-data）并经存储服务持久化，
    随后对抽取文本调外部 LLM 出内容处理草稿（失败降级，上传不失败）。

    读取时即做大小上限保护（超限 413），避免把超大文件全部读入内存。
    """
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=413,
            detail={"denied_reason": "file_too_large", "message": "文件超出大小上限"},
        )
    return await ingest_service.create_upload(
        session,
        caller,
        content=content,
        file_name=file.filename or "file",
        file_mime_type=file.content_type,
        target_scope=target_scope,
        target_project_id=target_project_id,
        storage=storage,
        llm=llm,
        desensitizer=desensitizer,
        trace_id=get_trace_id(request),
    )


@router.get("/ingest/pending", response_model=PendingIngestListResponse)
async def list_pending(
    source: str | None = None,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> PendingIngestListResponse:
    """业务侧待确认任务列表。

    `?source=path_a_wecom` 拉取企微微盘扫描创建的待确认任务。权限与 confirm 一致：
    只返回调用人有权确认的任务（创建人本人或业务治理角色）；纯 admin → 403。
    """
    items = await ingest_service.list_pending(session, caller, source=source)
    return PendingIngestListResponse(items=items, total=len(items))


@router.get("/ingest/{task_id}/ai-result", response_model=IngestAiResultResponse)
async def get_ai_result(
    task_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> IngestAiResultResponse:
    return await ingest_service.get_ai_result(session, caller, task_id)


@router.post("/ingest/{task_id}/confirm", response_model=IngestConfirmResponse)
async def confirm(
    task_id: uuid.UUID,
    req: IngestConfirmRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
    weknora: WeKnoraClient | NullWeKnoraClient = Depends(get_weknora_client),
) -> IngestConfirmResponse:
    return await ingest_service.confirm(
        session, caller, task_id, req, get_trace_id(request),
        storage=storage, weknora=weknora,
    )


@router.post("/ingest/{task_id}/refresh-parse", response_model=IngestParseRefreshResponse)
async def refresh_parse(
    task_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    weknora: WeKnoraClient | NullWeKnoraClient = Depends(get_weknora_client),
) -> IngestParseRefreshResponse:
    return await ingest_service.refresh_parse(session, caller, task_id, weknora=weknora)


@router.get("/admin/ingest", response_model=AdminIngestListResponse)
async def list_admin_ingest(
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> AdminIngestListResponse:
    items = await ingest_service.list_admin_ingest(session, caller)
    return AdminIngestListResponse(items=items, total=len(items))

