"""Knowledge 读 API+ 受控删除。

读：列表 / 详情 / 个人知识。删除：受控软删除 / 撤下。权限判断全部委托
`app.services.knowledge`（其内部调用集中权限服务），本层不写权限矩阵。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.models.knowledge import KnowledgeAsset
from app.schemas.bulk_operations import (
    BulkOperationResponse,
    KnowledgeBulkDeleteRequest,
)
from app.schemas.enums import (
    AssetStatus,
    AssetType,
    AuditAction,
    ConfidentialityLevel,
    KnowledgeScope,
    KnowledgeZone,
    PersonalKnowledgeState,
)
from app.schemas.knowledge import (
    DirectoryListResponse,
    KnowledgeDeleteRequest,
    KnowledgeDeleteResponse,
    KnowledgeDetailOut,
    KnowledgeLibraryProjectListResponse,
    KnowledgeListResponse,
    KnowledgeSortField,
    RetryIndexRequest,
    RetryIndexResponse,
    SortDirection,
)
from app.schemas.knowledge_insights import KnowledgeOpsInsightsResponse
from app.schemas.my_knowledge import PersonalKnowledgeListResponse
from app.schemas.permission import CallerContext
from app.services import bulk_operations as bulk_service
from app.services import knowledge as knowledge_service
from app.services import knowledge_insights as insights_service
from app.services.storage import LocalFileStorage, get_storage
from app.services.weknora_client import get_weknora_client

router = APIRouter(prefix="/api/v1", tags=["knowledge"])


@router.post("/knowledge/bulk-delete", response_model=BulkOperationResponse)
async def bulk_delete_knowledge_assets(
    body: KnowledgeBulkDeleteRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    weknora=Depends(get_weknora_client),
) -> BulkOperationResponse:
    """按声明范围逐项重鉴权删除，不允许把个人/其他项目资产混入批次。"""
    operation_id = uuid.uuid4()
    trace_id = get_trace_id(request)

    async def process_batch(batch):
        batch_results = []
        for asset_id in batch:
            try:
                asset = (
                    await session.execute(
                        select(KnowledgeAsset).where(KnowledgeAsset.id == asset_id)
                    )
                ).scalar_one_or_none()
                scope_matches = asset is not None and asset.scope == body.scope
                project_matches = body.scope != "project" or (
                    asset is not None and asset.project_id == body.project_id
                )
                if not scope_matches or not project_matches:
                    batch_results.append(
                        bulk_service.BulkItemResult(
                            item_id=asset_id,
                            status="skipped",
                            reason_code="knowledge_asset_not_found",
                            message="资料不存在或已不属于当前范围",
                        )
                    )
                    continue
                await knowledge_service.delete_asset(
                    session,
                    caller,
                    asset_id,
                    reason=body.reason,
                    weknora=weknora,
                    trace_id=trace_id,
                )
                batch_results.append(
                    bulk_service.BulkItemResult(item_id=asset_id, status="succeeded")
                )
            except HTTPException as exc:
                await session.rollback()
                batch_results.append(bulk_service.skipped_from_http(asset_id, exc))
            except Exception:
                await session.rollback()
                batch_results.append(bulk_service.failed_item(asset_id))
        return batch_results

    results = await bulk_service.execute_in_controlled_batches(body.item_ids, process_batch)
    response = bulk_service.terminal_response(operation_id, body.item_ids, results)
    await bulk_service.record_terminal_audit(
        session,
        caller=caller,
        action=AuditAction.knowledge_asset_bulk_deleted.value,
        trace_id=trace_id,
        response=response,
        operation="delete",
        target_scope=body.scope,
        project_id=body.project_id,
        client_operation_id=body.client_operation_id,
        request_index=body.request_index,
        request_count=body.request_count,
        total_submitted=body.total_submitted,
    )
    return response


def _validate_time_range(
    start: datetime | None, end: datetime | None, *, field: str, message: str
) -> None:
    if any(value is not None and value.utcoffset() is None for value in (start, end)):
        raise HTTPException(
            status_code=422,
            detail={
                "denied_reason": f"{field}_timezone_required",
                "message": "时间参数必须包含时区",
            },
        )
    if start and end and start > end:
        raise HTTPException(
            status_code=422,
            detail={"denied_reason": f"{field}_range_invalid", "message": message},
        )


@router.get("/knowledge", response_model=KnowledgeListResponse)
async def list_knowledge(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    keyword: str | None = Query(default=None, min_length=1, max_length=100),
    scope: KnowledgeScope | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    zone: KnowledgeZone | None = Query(default=None),
    asset_type: AssetType | None = Query(default=None),
    asset_status: AssetStatus | None = Query(default=None),
    confidentiality_level: ConfidentialityLevel | None = Query(default=None),
    directory_key: str | None = Query(default=None, min_length=1, max_length=100),
    include_descendants: bool = Query(default=False),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    updated_from: datetime | None = Query(default=None),
    updated_to: datetime | None = Query(default=None),
    sort_by: KnowledgeSortField = Query(default=KnowledgeSortField.updated_at),
    sort_direction: SortDirection = Query(default=SortDirection.desc),
    include_archived: bool = Query(default=False),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> KnowledgeListResponse:
    """知识列表：只返回调用人可发现的资产。"""
    _validate_time_range(created_from, created_to, field="created_time", message="创建时间范围无效")
    _validate_time_range(updated_from, updated_to, field="updated_time", message="更新时间范围无效")
    clean_keyword = keyword.strip() if keyword else None
    if keyword is not None and not clean_keyword:
        raise HTTPException(
            status_code=422,
            detail={"denied_reason": "keyword_invalid", "message": "关键词不能为空"},
        )
    return await knowledge_service.list_knowledge(
        session,
        caller,
        scope=scope.value if scope else None,
        project_id=project_id,
        include_archived=include_archived,
        keyword=clean_keyword,
        zone=zone.value if zone else None,
        asset_type=asset_type.value if asset_type else None,
        asset_status=asset_status.value if asset_status else None,
        confidentiality_level=confidentiality_level.value if confidentiality_level else None,
        directory_key=directory_key,
        include_descendants=include_descendants,
        created_from=created_from,
        created_to=created_to,
        updated_from=updated_from,
        updated_to=updated_to,
        sort_by=sort_by.value,
        sort_direction=sort_direction.value,
        page=page,
        page_size=page_size,
        require_directory_context=True,
    )


@router.get("/projects/{project_id}/knowledge", response_model=KnowledgeListResponse)
async def list_project_workspace_knowledge(
    project_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    keyword: str | None = Query(default=None, min_length=1, max_length=100),
    zone: KnowledgeZone | None = Query(default=None),
    asset_type: AssetType | None = Query(default=None),
    asset_status: AssetStatus | None = Query(default=None),
    confidentiality_level: ConfidentialityLevel | None = Query(default=None),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    updated_from: datetime | None = Query(default=None),
    updated_to: datetime | None = Query(default=None),
    sort_by: KnowledgeSortField = Query(default=KnowledgeSortField.updated_at),
    sort_direction: SortDirection = Query(default=SortDirection.desc),
    include_archived: bool = Query(default=False),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> KnowledgeListResponse:
    """Project workspace listing; separate from governed directory browsing."""
    _validate_time_range(created_from, created_to, field="created_time", message="创建时间范围无效")
    _validate_time_range(updated_from, updated_to, field="updated_time", message="更新时间范围无效")
    clean_keyword = keyword.strip() if keyword else None
    if keyword is not None and not clean_keyword:
        raise HTTPException(
            status_code=422,
            detail={"denied_reason": "keyword_invalid", "message": "关键词不能为空"},
        )
    return await knowledge_service.list_knowledge(
        session,
        caller,
        scope=KnowledgeScope.project.value,
        project_id=project_id,
        include_archived=include_archived,
        keyword=clean_keyword,
        zone=zone.value if zone else None,
        asset_type=asset_type.value if asset_type else None,
        asset_status=asset_status.value if asset_status else None,
        confidentiality_level=confidentiality_level.value if confidentiality_level else None,
        created_from=created_from,
        created_to=created_to,
        updated_from=updated_from,
        updated_to=updated_to,
        sort_by=sort_by.value,
        sort_direction=sort_direction.value,
        page=page,
        page_size=page_size,
        require_directory_context=False,
    )


@router.get("/knowledge/directories", response_model=DirectoryListResponse)
async def list_knowledge_directories(
    scope: KnowledgeScope | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> DirectoryListResponse:
    """Return only governed directories the current caller may browse."""
    return await knowledge_service.list_directories(
        session,
        caller,
        scope=scope.value if scope else None,
        project_id=project_id,
    )


@router.get("/knowledge/projects", response_model=KnowledgeLibraryProjectListResponse)
async def list_knowledge_library_projects(
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> KnowledgeLibraryProjectListResponse:
    """Stable active project folders; asset permissions are evaluated elsewhere."""
    return await knowledge_service.list_knowledge_library_projects(session, caller)


@router.get("/knowledge/ops-insights", response_model=KnowledgeOpsInsightsResponse)
async def knowledge_ops_insights(
    scope: str | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    days: int = Query(default=30),
    limit: int = Query(default=10),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> KnowledgeOpsInsightsResponse:
    """Knowledge 运营洞察：真实表安全聚合 + 安全提示。

    权限：业务用户按其可见范围、纯 admin 系统运维聚合（title_visible=false）、inactive/非业务非 admin → 403。
    不绕过 `/knowledge` 发现权限；响应绝不含 WeKnora id / 存储引用 / 原文 / 文件名 / token。"""
    return await insights_service.get_ops_insights(
        session,
        caller,
        scope=scope,
        project_id=project_id,
        days=days,
        limit=limit,
    )


@router.get("/my/knowledge", response_model=PersonalKnowledgeListResponse)
async def list_my_knowledge(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    keyword: str | None = Query(default=None, min_length=1, max_length=100),
    asset_type: AssetType | None = Query(default=None),
    personal_state: PersonalKnowledgeState | None = Query(default=None),
    sort_by: KnowledgeSortField = Query(default=KnowledgeSortField.updated_at),
    sort_direction: SortDirection = Query(default=SortDirection.desc),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> PersonalKnowledgeListResponse:
    """个人知识：仅返回本人的 scope=personal 资产；纯 admin 返回 403。"""
    clean_keyword = keyword.strip() if keyword else None
    if keyword is not None and not clean_keyword:
        raise HTTPException(
            status_code=422,
            detail={"denied_reason": "keyword_invalid", "message": "关键词不能为空"},
        )
    if sort_by not in {
        KnowledgeSortField.updated_at,
        KnowledgeSortField.created_at,
        KnowledgeSortField.title_,
    }:
        raise HTTPException(
            status_code=422,
            detail={"denied_reason": "sort_field_invalid", "message": "个人知识不支持该排序字段"},
        )
    return await knowledge_service.list_my_knowledge(
        session,
        caller,
        page=page,
        page_size=page_size,
        keyword=clean_keyword,
        asset_type=asset_type.value if asset_type else None,
        personal_state=personal_state.value if personal_state else None,
        sort_by=sort_by.value,
        sort_direction=sort_direction.value,
    )


@router.get("/knowledge/{asset_id}", response_model=KnowledgeDetailOut)
async def get_knowledge_detail(
    asset_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> KnowledgeDetailOut:
    """知识详情：discovery 被拒时按安全口径返回（l5/personal/archived → 404）。"""
    return await knowledge_service.get_detail(session, caller, asset_id)


@router.post("/knowledge/{asset_id}/delete", response_model=KnowledgeDeleteResponse)
async def delete_knowledge_asset(
    asset_id: uuid.UUID,
    body: KnowledgeDeleteRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    weknora=Depends(get_weknora_client),
) -> KnowledgeDeleteResponse:
    """受控删除 / 撤下知识资产。权限：个人 owner / 项目 active
    project_manager / 公司总经理·咨询总监；纯 admin 不可。删除后资产立即退出
    列表 / 检索 / 问答 / 预览 / Agent / 原文授权运行时。"""
    return await knowledge_service.delete_asset(
        session,
        caller,
        asset_id,
        reason=body.reason,
        weknora=weknora,
        trace_id=get_trace_id(request),
    )


@router.post("/knowledge/{asset_id}/retry-index", response_model=RetryIndexResponse)
async def retry_index(
    asset_id: uuid.UUID,
    request: Request,
    req: RetryIndexRequest | None = None,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
    weknora=Depends(get_weknora_client),
) -> RetryIndexResponse:
    """重试底座索引：仅对 index_failed / not_indexed / skipped 的资产，
    且调用人有业务管理权（个人 owner / 项目 PM·coach / 公司治理）。纯 admin 不可。
    复用 confirm 的安全索引机制；响应只回安全索引状态，绝不含 kb_id / doc_id / storage_ref。"""
    body = req or RetryIndexRequest()
    return await knowledge_service.retry_index(
        session,
        caller,
        asset_id,
        weknora=weknora,
        storage=storage,
        trace_id=get_trace_id(request),
        embedding_model_ref=body.embedding_model_ref,
        rerank_model_ref=body.rerank_model_ref,
    )
