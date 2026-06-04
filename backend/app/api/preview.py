"""预览凭证 API（IMPLEMENT-07 最小闭环）。

- POST /api/v1/knowledge/{asset_id}/preview：签发受控预览凭证。
- GET  /api/v1/preview/{credential_id}：平台受控占位预览入口。

权限判断委托 `app.services.preview`（其内部复用集中权限服务）。
不返回完整 token / 对象存储 URL / storage_ref / bucket。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.permission import CallerContext
from app.schemas.preview import (
    PreviewEntryResponse,
    PreviewIssueRequest,
    PreviewIssueResponse,
)
from app.services import preview as preview_service
from app.services.storage import LocalFileStorage, get_storage

router = APIRouter(prefix="/api/v1", tags=["preview"])


@router.post("/knowledge/{asset_id}/preview", response_model=PreviewIssueResponse)
async def issue_preview(
    asset_id: uuid.UUID,
    request: Request,
    req: PreviewIssueRequest | None = None,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> PreviewIssueResponse:
    version_id = req.version_id if req else None
    return await preview_service.issue_preview(
        session, caller, asset_id, version_id, get_trace_id(request)
    )


@router.get("/preview/{credential_id}", response_model=PreviewEntryResponse)
async def use_preview_entry(
    credential_id: uuid.UUID,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> PreviewEntryResponse:
    return await preview_service.use_preview_entry(
        session, caller, credential_id, get_trace_id(request)
    )


@router.get("/preview/{credential_id}/file")
async def serve_preview_file(
    credential_id: uuid.UUID,
    ft: str = Query(..., description="短时受控取件 token（Document Server 回取用）"),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
) -> Response:
    """ONLYOFFICE 受控取件端点（服务端到服务端，凭 fetch_token 授权，无会话）。

    仅返回经平台存储引用读出的原文字节；响应头不含 storage_ref / 内部路径。
    """
    data, media_type, filename = await preview_service.serve_preview_file(
        session, credential_id, ft, storage=storage
    )
    # inline 展示安全文件名；不暴露任何内部引用。
    headers = {"Content-Disposition": f'inline; filename="{filename}"', "Cache-Control": "no-store"}
    return Response(content=data, media_type=media_type, headers=headers)
