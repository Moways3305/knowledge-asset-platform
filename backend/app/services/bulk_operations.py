"""Helpers for bounded bulk execution with terminal, non-sensitive results."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.bulk_operations import BulkItemResult, BulkOperationResponse
from app.schemas.enums import AuditLogType
from app.schemas.permission import CallerContext
from app.services import audit as audit_service

SYNC_ITEM_LIMIT = 50
CONTROLLED_BATCH_SIZE = SYNC_ITEM_LIMIT

_ItemT = TypeVar("_ItemT")

_SAFE_REASON_MESSAGES = {
    "knowledge_asset_not_found": "资料不存在或已不可操作",
    "knowledge_delete_forbidden": "当前无权删除该资料",
    "admin_business_permission_denied": "当前身份无业务操作权限",
    "personal_asset_project_locked": "资料正在审核或被项目使用",
    "review_not_found": "审核项不存在或已不可见",
    "review_not_pending": "审核项状态已变化",
    "review_forbidden": "当前无权处理该审核项",
    "original_access_request_not_found": "申请不存在或已不可见",
    "original_access_request_not_pending": "申请状态已变化",
    "original_access_review_forbidden": "当前无权处理该申请",
    "personal_asset_not_found": "资料不存在或已不可操作",
    "personal_asset_project_submission_locked": "资料已提交或正在项目流程中",
    "project_not_found": "目标项目不存在或已停用",
    "project_membership_required": "当前不具备目标项目提交资格",
    "naming_fields_required": "请补齐该资料的命名字段后重新核对",
    "naming_fields_invalid": "请修改该资料的命名字段后重新核对",
    "naming_formed_on_invalid": "请填写有效的文件形成日期",
    "naming_version_invalid": "请填写有效版本，例如 V1 或 V1.1",
    "naming_category_unavailable": "目录类别已停用或不适用于当前目标",
    "naming_asset_type_mapping_missing": "该目录类别尚未配置资产分类，请联系管理员补充后重试",
    "naming_applicable_to_required": "公司库资料必须填写适用对象",
    "naming_exact_duplicate": "已存在相同文件，请核对",
    "canonical_name_too_long": "规范名过长，请缩短主题或适用对象",
    "project_subject_customer_name_detected": "主题可能包含客户名称，请修改后继续",
}


def skipped_from_http(item_id: uuid.UUID, exc: HTTPException) -> BulkItemResult:
    detail: dict[str, object] = exc.detail if isinstance(exc.detail, dict) else {}
    code = str(detail.get("denied_reason") or "item_state_changed")
    return BulkItemResult(
        item_id=item_id,
        status="skipped" if exc.status_code < 500 else "failed",
        reason_code=code,
        message=_SAFE_REASON_MESSAGES.get(code, "当前状态或权限已变化，请刷新后重试"),
    )


def failed_item(item_id: uuid.UUID) -> BulkItemResult:
    return BulkItemResult(
        item_id=item_id,
        status="failed",
        reason_code="operation_failed",
        message="操作未完成，请稍后重试",
    )


def validation_error_result(item_id: uuid.UUID, exc: ValidationError) -> BulkItemResult:
    locations = {str(part) for error in exc.errors() for part in error.get("loc", ())}
    if "formed_on" in locations:
        code = "naming_formed_on_invalid"
    elif "version" in locations:
        code = "naming_version_invalid"
    else:
        code = "naming_fields_invalid"
    return BulkItemResult(
        item_id=item_id,
        status="skipped",
        reason_code=code,
        message=_SAFE_REASON_MESSAGES[code],
    )


async def execute_in_controlled_batches(
    items: Sequence[_ItemT],
    process_batch: Callable[[Sequence[_ItemT]], Awaitable[list[BulkItemResult]]],
    *,
    batch_size: int = CONTROLLED_BATCH_SIZE,
) -> list[BulkItemResult]:
    """Process a bounded slice at a time while preserving input/result order.

    The endpoint-provided batch callback still performs each item's authorization
    and transaction handling independently. Yielding between slices prevents a
    large request from monopolizing the event loop.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    results: list[BulkItemResult] = []
    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        batch_results = await process_batch(batch)
        if len(batch_results) != len(batch):
            raise RuntimeError("bulk batch returned an unexpected result count")
        results.extend(batch_results)
        if start + batch_size < len(items):
            await asyncio.sleep(0)
    return results


def terminal_response(
    operation_id: uuid.UUID, item_ids: list[uuid.UUID], items: list[BulkItemResult]
) -> BulkOperationResponse:
    succeeded = sum(item.status == "succeeded" for item in items)
    skipped = sum(item.status == "skipped" for item in items)
    failed = sum(item.status == "failed" for item in items)
    return BulkOperationResponse(
        operation_id=operation_id,
        status="completed" if skipped == 0 and failed == 0 else "completed_with_errors",
        execution_mode=("synchronous" if len(item_ids) <= SYNC_ITEM_LIMIT else "controlled_batch"),
        submitted=len(item_ids),
        succeeded=succeeded,
        skipped=skipped,
        failed=failed,
        items=items,
    )


async def record_terminal_audit(
    session: AsyncSession,
    *,
    caller: CallerContext,
    action: str,
    trace_id: str,
    response: BulkOperationResponse,
    operation: str,
    target_scope: str,
    project_id: uuid.UUID | None = None,
    client_operation_id: uuid.UUID | None = None,
    request_index: int | None = None,
    request_count: int | None = None,
    total_submitted: int | None = None,
) -> None:
    """Persist one safe batch summary in addition to existing per-item audits."""
    extra: dict[str, str | int] = {
        "operation": operation,
        "target_scope": target_scope,
        "execution_mode": response.execution_mode,
        "submitted": response.submitted,
        "succeeded": response.succeeded,
        "skipped": response.skipped,
        "failed": response.failed,
    }
    if client_operation_id is not None:
        extra.update(
            {
                "client_operation_id": str(client_operation_id),
                "request_index": request_index or 1,
                "request_count": request_count or 1,
                "logical_submitted": total_submitted or response.submitted,
            }
        )
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=action,
        trace_id=trace_id,
        target_type="bulk_operation",
        project_id=project_id,
        extra=extra,
    )
    await session.commit()
