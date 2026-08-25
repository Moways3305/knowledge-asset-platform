"""Recoverable, caller-owned local upload sessions with stable 200-item batches."""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ingest import (
    IngestTask,
    UploadSession,
    UploadSessionItem,
    UploadTransportBatch,
)
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetFileObject
from app.schemas.enums import AuditAction, AuditLogType, IngestSource, IngestStatus
from app.schemas.ingest import (
    UploadSessionItemResponse,
    UploadSessionListResponse,
    UploadSessionResponse,
)
from app.schemas.permission import CallerContext
from app.services import audit as audit_service
from app.services.desensitization import DesensitizationEngine
from app.services.llm_client import LLMClient, NullLLMClient
from app.services.permission import discovery_filter
from app.services.storage import LocalFileStorage
from app.worker.enqueue import enqueue_ingest_processing

BATCH_SIZE = 200
TRANSPORT_BATCH_MAX_FILES = 10
TRANSPORT_BATCH_MAX_BYTES = 20 * 1024 * 1024
SINGLE_FILE_MAX_BYTES = 25 * 1024 * 1024
_TERMINAL_ITEM_STATES = {"awaiting_confirmation", "completed", "failed", "cancelled"}
_COMPLETED_ITEM_STATES = {"awaiting_confirmation", "completed", "cancelled"}
_PENDING_NAME_WARNING_STATUSES = {
    IngestStatus.pending_confirmation.value,
    IngestStatus.failed.value,
    IngestStatus.rejected.value,
    IngestStatus.waiting_review.value,
}
MACOS_METADATA_MESSAGE = "这是 macOS 元数据文件，不是原始资料；请选择不带 `._` 前缀的原文件"
UNREADABLE_FILE_MESSAGE = "文件内容当前不可读取；请先在本机完成下载后重新选择"
PROCESSING_MAX_AGE = timedelta(hours=2)
PROCESSING_ACTIVITY_GRACE = timedelta(minutes=15)

# 文件名日期识别：YYYYMMDD、YYYY-MM-DD、YYYY/MM/DD、YYYY年M月D日 等形态。
_FILENAME_DATE_RE = re.compile(r"(?<!\d)(\d{4})[-_.年/]?(\d{1,2})[-_.月/]?(\d{1,2})日?(?!\d)")


@dataclass(frozen=True)
class UploadCandidate:
    file_name: str
    file_size: int
    file_type: str | None
    storage_ref: str | None = None
    content_hash: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    # 文件形成日期建议（YYYY-MM-DD，客户端 lastModified 或文件名正则兜底）。
    suggested_formed_on: str | None = None


def extract_formed_on_from_filename(file_name: str) -> str | None:
    """从文件名提取日期（YYYY-MM-DD）；提取不到或日期非法 → None。

    只做确定性正则 + 日历合法性校验，不猜语义（如 2026-13-99 判非法）。
    """
    match = _FILENAME_DATE_RE.search(file_name or "")
    if not match:
        return None
    try:
        year, month, day = (int(g) for g in match.groups())
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return None
        return f"{year:04d}-{month:02d}-{day:02d}"
    except (TypeError, ValueError):
        return None


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"denied_reason": reason, "message": message}
    )


def _display_name(value: str) -> str:
    """Keep a display basename, never a client absolute/relative path."""
    cleaned = "".join(char for char in value if ord(char) >= 32 and ord(char) != 127)
    return (cleaned.replace("\\", "/").rsplit("/", 1)[-1].strip() or "file")[:500]


def macos_metadata_error(value: str) -> str | None:
    """Recognize only explicit macOS/archive metadata patterns."""
    normalized = value.replace("\\", "/")
    segments = [segment for segment in normalized.split("/") if segment]
    basename = segments[-1] if segments else normalized
    if (
        basename.startswith("._")
        or basename.casefold() == ".ds_store"
        or any(segment.casefold() == "__macosx" for segment in segments[:-1])
    ):
        return MACOS_METADATA_MESSAGE
    return None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _is_stale_processing(task: IngestTask, now: datetime) -> bool:
    return (
        task.source == IngestSource.path_b_upload.value
        and task.status == IngestStatus.processing.value
        and task.result_asset_id is None
        and _aware(task.created_at) <= now - PROCESSING_MAX_AGE
        and _aware(task.updated_at) <= now - PROCESSING_ACTIVITY_GRACE
    )


async def expire_stale_tasks(
    session: AsyncSession,
    caller: CallerContext,
    *,
    task_ids: list[uuid.UUID] | None = None,
    trace_id: str,
    now: datetime | None = None,
    all_owners: bool = False,
) -> int:
    """Fail only caller-owned processing tasks with no recent activity evidence."""
    if all_owners and not ("admin" in caller.active_company_roles or caller.can_discover_l5):
        raise _denied(403, "stale_task_recovery_forbidden", "无权执行全局任务收敛")
    stmt = select(IngestTask).where(
        IngestTask.source == IngestSource.path_b_upload.value,
        IngestTask.status == IngestStatus.processing.value,
        IngestTask.result_asset_id.is_(None),
    )
    if not all_owners:
        stmt = stmt.where(IngestTask.created_by == caller.user_id)
    if task_ids is not None:
        if not task_ids:
            return 0
        stmt = stmt.where(IngestTask.id.in_(task_ids))
    tasks = (await session.execute(stmt.with_for_update())).scalars().all()
    current = now or datetime.now(timezone.utc)
    expired = 0
    for task in tasks:
        if not _is_stale_processing(task, current):
            continue
        task.status = IngestStatus.failed.value
        task.processing_stage = None
        task.error_type = "processing_timeout"
        task.error_message = "文件处理超过安全时限且近期无活动"
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.ingest_failed.value,
            trace_id=trace_id,
            target_type="ingest_task",
            target_id=task.id,
            after={
                "status": task.status,
                "error_type": task.error_type,
                "processing_timeout_minutes": int(PROCESSING_MAX_AGE.total_seconds() / 60),
                "activity_grace_minutes": int(PROCESSING_ACTIVITY_GRACE.total_seconds() / 60),
            },
            project_id=task.target_project_id,
        )
        expired += 1
    if expired:
        await session.commit()
    return expired


def _normalized_name(value: str) -> str:
    return unicodedata.normalize("NFKC", _display_name(value)).casefold().strip()


def stable_batch_sizes(total: int) -> list[int]:
    """Pure batching contract used by migrations/tests/UI evidence."""
    if total <= 0:
        return []
    return [min(BATCH_SIZE, total - start) for start in range(0, total, BATCH_SIZE)]


def authorize_create(caller: CallerContext) -> None:
    if not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可发起入库")


async def initialize_transport_session(
    session: AsyncSession,
    caller: CallerContext,
    *,
    session_id: uuid.UUID,
    manifest: list[dict],
    total_transport_batches: int,
    target_scope: str | None,
    target_project_id: uuid.UUID | None,
) -> UploadSession:
    """Create a durable lightweight manifest before any multipart request is sent."""
    authorize_create(caller)
    existing = await session.get(UploadSession, session_id)
    if existing is not None:
        if existing.created_by != caller.user_id:
            raise _denied(409, "upload_session_conflict", "上传会话标识冲突，请重新提交")
        return existing
    value = UploadSession(
        id=session_id,
        created_by=caller.user_id,
        status="active",
        total_files=len(manifest),
        total_batches=total_transport_batches,
        upload_completed=False,
        next_transport_batch_index=0,
        target_scope=target_scope,
        target_project_id=target_project_id,
    )
    session.add(value)
    existing_names = await _visible_names(session, caller)
    names_in_manifest: set[str] = set()
    for ordinal, entry in enumerate(manifest):
        display_name = _display_name(str(entry["file_name"]))
        normalized = _normalized_name(display_name)
        rejection = entry.get("rejection")
        session.add(
            UploadSessionItem(
                session_id=session_id,
                ordinal=ordinal,
                batch_index=ordinal // BATCH_SIZE,
                client_file_key=str(entry["client_file_key"]),
                file_name=display_name,
                file_size=max(0, int(entry["file_size"])),
                file_type=entry.get("file_type"),
                suggested_formed_on=entry.get("formed_on"),
                transport_batch_index=entry.get("transport_batch_index"),
                status="failed" if rejection else "waiting_upload",
                safe_error_code=rejection.get("error_code") if rejection else None,
                safe_error_message=rejection.get("error_message") if rejection else None,
                same_name_warning=(normalized in existing_names or normalized in names_in_manifest),
            )
        )
        names_in_manifest.add(normalized)
    await session.commit()
    return value


async def append_transport_batch(
    session: AsyncSession,
    caller: CallerContext,
    *,
    session_id: uuid.UUID,
    batch_id: str,
    batch_index: int,
    candidates: list[tuple[uuid.UUID, UploadCandidate]],
) -> UploadSession:
    authorize_create(caller)
    if not 1 <= len(candidates) <= TRANSPORT_BATCH_MAX_FILES:
        raise _denied(422, "invalid_transport_batch_count", "每个上传批次最多包含 10 个文件")
    raw_bytes = sum(candidate.file_size for _, candidate in candidates)
    if raw_bytes > TRANSPORT_BATCH_MAX_BYTES and not (
        len(candidates) == 1 and raw_bytes <= SINGLE_FILE_MAX_BYTES
    ):
        raise _denied(413, "transport_batch_too_large", "上传批次超过 20 MiB 安全上限")
    value = await _load_owned_session(session, caller, session_id, lock=True)
    existing_batch = await session.scalar(
        select(UploadTransportBatch).where(
            UploadTransportBatch.session_id == session_id,
            UploadTransportBatch.batch_id == batch_id,
        )
    )
    if existing_batch is not None:
        if existing_batch.batch_index != batch_index:
            raise _denied(409, "transport_batch_id_conflict", "上传批次标识与顺序不一致")
        return value
    if value.upload_completed:
        raise _denied(409, "upload_session_already_completed", "上传会话已完成")
    if batch_index != value.next_transport_batch_index:
        raise _denied(409, "transport_batch_out_of_order", "上传批次顺序不一致，请恢复后重试")
    item_ids = {item.id for item in value.items}
    if len({item_id for item_id, _ in candidates}) != len(candidates) or any(
        item_id not in item_ids for item_id, _ in candidates
    ):
        raise _denied(422, "invalid_transport_batch_manifest", "上传批次文件清单无效")
    for item_id, candidate in candidates:
        item = next(item for item in value.items if item.id == item_id)
        if item.ingest_task_id is not None:
            raise _denied(409, "upload_item_already_received", "文件已上传，不得重复创建")
        if (
            candidate.file_size != item.file_size
            or _display_name(candidate.file_name) != item.file_name
        ):
            raise _denied(422, "upload_item_manifest_mismatch", "上传文件与会话清单不一致")
        if candidate.storage_ref is None or candidate.content_hash is None:
            raise _denied(422, "upload_bytes_unavailable", "文件字节未安全保存")
        task = IngestTask(
            source=IngestSource.path_b_upload.value,
            source_file_ref=candidate.storage_ref,
            source_file_name=item.file_name,
            source_file_mime_type=candidate.file_type,
            source_file_size=candidate.file_size,
            source_file_hash=candidate.content_hash,
            suggested_formed_on=item.suggested_formed_on,
            status=IngestStatus.pending.value,
            processing_stage="upload_waiting",
            target_scope=value.target_scope,
            target_project_id=value.target_project_id,
            created_by=caller.user_id,
        )
        session.add(task)
        await session.flush()
        item.ingest_task_id = task.id
        item.status = "waiting"
        item.transport_batch_index = batch_index
        item.safe_error_code = None
        item.safe_error_message = None
    session.add(
        UploadTransportBatch(
            session_id=session_id,
            batch_id=batch_id,
            batch_index=batch_index,
            status="completed",
            item_count=len(candidates),
            raw_bytes=raw_bytes,
        )
    )
    value.next_transport_batch_index += 1
    await session.commit()
    return value


async def preflight_transport_batch(
    session: AsyncSession,
    caller: CallerContext,
    *,
    session_id: uuid.UUID,
    batch_id: str,
    batch_index: int,
    manifest: list[tuple[uuid.UUID, str, int]],
) -> bool:
    """Lock and validate ordering/manifest before any browser bytes are persisted."""
    authorize_create(caller)
    value = await _load_owned_session(session, caller, session_id, lock=True)
    existing = await session.scalar(
        select(UploadTransportBatch).where(
            UploadTransportBatch.session_id == session_id,
            UploadTransportBatch.batch_id == batch_id,
        )
    )
    if existing is None:
        if value.upload_completed:
            raise _denied(409, "upload_session_already_completed", "上传会话已完成")
        if batch_index != value.next_transport_batch_index:
            raise _denied(409, "transport_batch_out_of_order", "上传批次顺序不一致，请恢复后重试")
        item_ids = {item.id for item in value.items}
        manifest_ids = [item_id for item_id, _file_name, _file_size in manifest]
        if len(set(manifest_ids)) != len(manifest_ids) or any(
            item_id not in item_ids for item_id in manifest_ids
        ):
            raise _denied(422, "invalid_transport_batch_manifest", "上传批次文件清单无效")
        for item_id, file_name, file_size in manifest:
            item = next(item for item in value.items if item.id == item_id)
            if item.ingest_task_id is not None:
                raise _denied(409, "upload_item_already_received", "文件已上传，不得重复创建")
            if file_size != item.file_size or _display_name(file_name) != item.file_name:
                raise _denied(422, "upload_item_manifest_mismatch", "上传文件与会话清单不一致")
            if item.transport_batch_index is not None and item.transport_batch_index != batch_index:
                raise _denied(409, "transport_item_batch_mismatch", "文件不属于当前传输批次")
        return False
    if existing.batch_index != batch_index:
        raise _denied(409, "transport_batch_id_conflict", "上传批次标识与顺序不一致")
    if existing.status != "completed":
        raise _denied(409, "transport_batch_failed", "失败批次需按文件逐项恢复")
    return True


async def fail_transport_items(
    session: AsyncSession,
    caller: CallerContext,
    *,
    session_id: uuid.UUID,
    item_ids: list[uuid.UUID],
    error_code: str,
    message: str,
    batch_id: str | None = None,
    batch_index: int | None = None,
) -> UploadSession:
    value = await _load_owned_session(session, caller, session_id, lock=True)
    if batch_id is not None and batch_index is not None:
        existing = await session.scalar(
            select(UploadTransportBatch).where(
                UploadTransportBatch.session_id == session_id,
                UploadTransportBatch.batch_id == batch_id,
            )
        )
        if existing is None:
            if batch_index != value.next_transport_batch_index:
                raise _denied(409, "transport_batch_out_of_order", "上传批次顺序不一致")
            session.add(
                UploadTransportBatch(
                    session_id=session_id,
                    batch_id=batch_id,
                    batch_index=batch_index,
                    status="failed",
                    item_count=len(item_ids),
                    raw_bytes=0,
                )
            )
            value.next_transport_batch_index += 1
        elif existing.batch_index != batch_index:
            raise _denied(409, "transport_batch_id_conflict", "上传批次标识与顺序不一致")
    values: dict[str, object] = {
        "status": "failed",
        "safe_error_code": error_code,
        "safe_error_message": message,
    }
    if batch_index is not None:
        values["transport_batch_index"] = batch_index
    await session.execute(
        update(UploadSessionItem)
        .where(
            UploadSessionItem.session_id == session_id,
            UploadSessionItem.id.in_(item_ids),
            UploadSessionItem.ingest_task_id.is_(None),
        )
        .values(**values)
    )
    await session.commit()
    return value


async def replace_transport_item_bytes(
    session: AsyncSession,
    caller: CallerContext,
    *,
    session_id: uuid.UUID,
    item_id: uuid.UUID,
    candidate: UploadCandidate,
) -> UploadSession:
    """Atomically attach reselected browser bytes to one manifest row."""
    authorize_create(caller)
    value = await _load_owned_session(session, caller, session_id, lock=True)
    item = next((entry for entry in value.items if entry.id == item_id), None)
    if item is None:
        raise _denied(404, "upload_item_not_found", "上传文件不存在")
    if item.ingest_task_id is not None:
        return value
    if (
        candidate.file_size != item.file_size
        or _display_name(candidate.file_name) != item.file_name
    ):
        raise _denied(422, "upload_item_manifest_mismatch", "重新选择的文件与原清单不一致")
    if candidate.file_size > SINGLE_FILE_MAX_BYTES:
        raise _denied(413, "file_too_large", "文件超过 25 MiB")
    if candidate.storage_ref is None or candidate.content_hash is None:
        raise _denied(422, "upload_bytes_unavailable", "文件字节未安全保存")
    task = IngestTask(
        source=IngestSource.path_b_upload.value,
        source_file_ref=candidate.storage_ref,
        source_file_name=item.file_name,
        source_file_mime_type=candidate.file_type,
        source_file_size=candidate.file_size,
        source_file_hash=candidate.content_hash,
        suggested_formed_on=item.suggested_formed_on,
        status=IngestStatus.pending.value,
        processing_stage="upload_waiting",
        target_scope=value.target_scope,
        target_project_id=value.target_project_id,
        created_by=caller.user_id,
    )
    session.add(task)
    await session.flush()
    item.ingest_task_id = task.id
    item.status = "waiting"
    item.safe_error_code = None
    item.safe_error_message = None
    await session.commit()
    return value


async def complete_transport_session(
    session: AsyncSession,
    caller: CallerContext,
    *,
    session_id: uuid.UUID,
) -> UploadSession:
    value = await _load_owned_session(session, caller, session_id, lock=True)
    if value.upload_completed:
        return value
    incomplete = [
        item
        for item in value.items
        if item.ingest_task_id is None
        and item.safe_error_code
        not in {
            "file_unreadable",
            "file_read_timeout",
            "macos_metadata",
            "unsupported_file_type",
            "file_too_large",
        }
    ]
    if incomplete or value.next_transport_batch_index != value.total_batches:
        raise _denied(409, "upload_session_incomplete", "仍有文件或上传批次未完成")
    value.upload_completed = True
    await session.commit()
    return value


async def _visible_names(session: AsyncSession, caller: CallerContext) -> set[str]:
    pending_names = (
        await session.execute(
            select(IngestTask.source_file_name).where(
                IngestTask.created_by == caller.user_id,
                IngestTask.result_asset_id.is_(None),
                IngestTask.status.in_(_PENDING_NAME_WARNING_STATUSES),
            )
        )
    ).scalars()
    materialized_names = (
        await session.execute(
            select(KnowledgeAssetFileObject.file_name)
            .join(KnowledgeAsset, KnowledgeAsset.id == KnowledgeAssetFileObject.asset_id)
            .where(
                KnowledgeAssetFileObject.file_variant == "original",
                discovery_filter(caller),
            )
        )
    ).scalars()
    return {_normalized_name(name) for name in [*pending_names, *materialized_names]}


async def create_session(
    session: AsyncSession,
    caller: CallerContext,
    *,
    requested_session_id: uuid.UUID | None,
    candidates: list[UploadCandidate],
    target_scope: str | None,
    target_project_id: uuid.UUID | None,
    storage: LocalFileStorage,
    llm: LLMClient | NullLLMClient,
    desensitizer: DesensitizationEngine,
    trace_id: str,
) -> UploadSessionResponse:
    authorize_create(caller)
    if not candidates:
        raise _denied(422, "empty_upload_session", "请选择至少一个文件")

    batch_sizes = stable_batch_sizes(len(candidates))
    upload_session = UploadSession(
        id=requested_session_id or uuid.uuid4(),
        created_by=caller.user_id,
        total_files=len(candidates),
        total_batches=len(batch_sizes),
        status="active",
        upload_completed=True,
        next_transport_batch_index=len(batch_sizes),
    )
    session.add(upload_session)
    await session.flush()

    existing_names = await _visible_names(session, caller)
    names_seen_in_request: set[str] = set()
    for ordinal, candidate in enumerate(candidates):
        display_name = _display_name(candidate.file_name)
        normalized = _normalized_name(display_name)
        same_name = normalized in existing_names or normalized in names_seen_in_request
        names_seen_in_request.add(normalized)
        item = UploadSessionItem(
            session_id=upload_session.id,
            ordinal=ordinal,
            batch_index=ordinal // BATCH_SIZE,
            file_name=display_name,
            file_size=candidate.file_size,
            file_type=candidate.file_type,
            status="failed" if candidate.error_code else "waiting",
            safe_error_code=candidate.error_code,
            safe_error_message=candidate.error_message,
            same_name_warning=same_name,
        )
        session.add(item)
        if candidate.error_code:
            await session.flush()
            await audit_service.record_event(
                session,
                caller=caller,
                log_type=AuditLogType.operation,
                action=AuditAction.ingest_failed.value,
                trace_id=trace_id,
                target_type="upload_session_item",
                target_id=item.id,
                after={
                    "status": "failed",
                    "error_type": candidate.error_code,
                    "upload_batch_number": item.batch_index + 1,
                },
                project_id=target_project_id,
            )
            continue
        if candidate.storage_ref is None or candidate.content_hash is None:
            item.status = "failed"
            item.safe_error_code = "storage_failed"
            item.safe_error_message = "文件暂时无法安全保存，请重试"
            continue
        task = IngestTask(
            source=IngestSource.path_b_upload.value,
            source_file_ref=candidate.storage_ref,
            source_file_name=display_name,
            source_file_mime_type=candidate.file_type,
            source_file_size=candidate.file_size,
            source_file_hash=candidate.content_hash,
            suggested_formed_on=candidate.suggested_formed_on,
            status=IngestStatus.pending.value,
            processing_stage="upload_waiting",
            target_scope=target_scope,
            target_project_id=target_project_id,
            created_by=caller.user_id,
        )
        session.add(task)
        await session.flush()
        item.ingest_task_id = task.id
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.ingest_task_created.value,
            trace_id=trace_id,
            target_type="ingest_task",
            target_id=task.id,
            after={
                "status": task.status,
                "source": task.source,
                "target_scope": task.target_scope,
                "upload_batch_number": item.batch_index + 1,
            },
            project_id=target_project_id,
        )

    await session.commit()
    await _reconcile_and_promote(
        session,
        upload_session.id,
        caller,
        storage=storage,
        llm=llm,
        desensitizer=desensitizer,
        trace_id=trace_id,
    )
    return await get_session(
        session,
        caller,
        upload_session.id,
        storage=storage,
        llm=llm,
        desensitizer=desensitizer,
        trace_id=trace_id,
        promote=False,
    )


async def get_session_if_exists(
    session: AsyncSession,
    caller: CallerContext,
    session_id: uuid.UUID | None,
    *,
    storage: LocalFileStorage,
    llm: LLMClient | NullLLMClient,
    desensitizer: DesensitizationEngine,
    trace_id: str,
) -> UploadSessionResponse | None:
    if session_id is None:
        return None
    owner_id = (
        await session.execute(
            select(UploadSession.created_by).where(UploadSession.id == session_id)
        )
    ).scalar_one_or_none()
    if owner_id is None:
        return None
    if owner_id != caller.user_id:
        raise _denied(409, "upload_session_conflict", "上传会话标识冲突，请重新提交")
    return await get_session(
        session,
        caller,
        session_id,
        storage=storage,
        llm=llm,
        desensitizer=desensitizer,
        trace_id=trace_id,
    )


def _task_item_state(task: IngestTask) -> str:
    if task.status == IngestStatus.pending_confirmation.value:
        return "awaiting_confirmation"
    if task.status in {
        IngestStatus.completed.value,
        IngestStatus.waiting_review.value,
        IngestStatus.rejected.value,
    }:
        return "completed"
    if task.status == IngestStatus.failed.value:
        return "failed"
    if task.status == IngestStatus.pending.value and task.processing_stage == "upload_waiting":
        return "waiting"
    return "processing"


async def _load_owned_session(
    session: AsyncSession, caller: CallerContext, session_id: uuid.UUID, *, lock: bool = False
) -> UploadSession:
    stmt = (
        select(UploadSession)
        .where(UploadSession.id == session_id, UploadSession.created_by == caller.user_id)
        .options(selectinload(UploadSession.items))
    )
    if lock:
        stmt = stmt.with_for_update()
    value = (await session.execute(stmt)).scalar_one_or_none()
    if value is None:
        raise _denied(404, "upload_session_not_found", "上传会话不存在")
    return value


async def _reconcile_and_promote(
    session: AsyncSession,
    session_id: uuid.UUID,
    caller: CallerContext,
    *,
    storage: LocalFileStorage,
    llm: LLMClient | NullLLMClient,
    desensitizer: DesensitizationEngine,
    trace_id: str,
) -> None:
    value = await _load_owned_session(session, caller, session_id, lock=True)
    task_ids = [item.ingest_task_id for item in value.items if item.ingest_task_id]
    await expire_stale_tasks(
        session,
        caller,
        task_ids=task_ids,
        trace_id=trace_id,
    )
    value = await _load_owned_session(session, caller, session_id, lock=True)
    tasks = (
        {
            task.id: task
            for task in (
                await session.execute(select(IngestTask).where(IngestTask.id.in_(task_ids)))
            ).scalars()
        }
        if task_ids
        else {}
    )
    for item in value.items:
        task_id = item.ingest_task_id
        task = tasks.get(task_id) if task_id is not None else None
        if task is not None:
            if item.status != "cancelled":
                item.status = _task_item_state(task)
                if item.status == "failed":
                    item.safe_error_code = task.error_type or "processing_failed"
                    item.safe_error_message = (
                        "文件处理超过安全时限且近期无活动；请重试或移除"
                        if task.error_type == "processing_timeout"
                        else "文件处理失败，请检查文件后重试"
                    )
                else:
                    # A later successful task state is authoritative. Do not retain a stale
                    # parse/queue failure from an earlier reconciliation pass.
                    item.safe_error_code = None
                    item.safe_error_message = None
        elif item.ingest_task_id is not None and item.status != "cancelled":
            # 悬空引用：item 之前关联的 IngestTask 已被删除（例如 delete_pending_task 后
            # ON DELETE SET NULL 清掉了外键）。同步把 item 也置为 cancelled，避免队列里
            # 一直显示"待确认入库"，造成和待确认入库列表/会话统计不同步。
            item.ingest_task_id = None
            item.status = "cancelled"
            item.safe_error_code = None
            item.safe_error_message = None

    batches = sorted({item.batch_index for item in value.items})
    batch_to_promote: int | None = None
    for batch_index in batches:
        items = [item for item in value.items if item.batch_index == batch_index]
        if any(item.status not in _TERMINAL_ITEM_STATES for item in items):
            if all(item.status == "waiting" for item in items if item.ingest_task_id):
                batch_to_promote = batch_index
            break
    promote_items = (
        [
            item
            for item in value.items
            if item.batch_index == batch_to_promote
            and item.status == "waiting"
            and item.ingest_task_id
        ]
        if batch_to_promote is not None
        else []
    )
    for item in promote_items:
        task_id = item.ingest_task_id
        if task_id is None:
            continue
        task = tasks[task_id]
        task.status = IngestStatus.processing.value
        task.processing_stage = "upload_saved"
        item.status = "processing"
    if promote_items:
        await session.commit()

    for item in promote_items:
        task_id = item.ingest_task_id
        if task_id is None:
            continue
        try:
            result = await enqueue_ingest_processing(
                session,
                task_id,
                storage=storage,
                llm=llm,
                desensitizer=desensitizer,
                trace_id=trace_id,
            )
            item.status = (
                "awaiting_confirmation"
                if result == IngestStatus.pending_confirmation.value
                else "failed"
                if result == IngestStatus.failed.value
                else "processing"
            )
            if item.status != "failed":
                item.safe_error_code = None
                item.safe_error_message = None
        except Exception:
            task = tasks[task_id]
            task.status = IngestStatus.failed.value
            task.error_type = "queue_unavailable"
            task.error_message = "处理任务暂时无法排队"
            item.status = "failed"
            item.safe_error_code = "queue_unavailable"
            item.safe_error_message = "处理任务暂时无法排队，请重试"
    value.status = (
        "completed"
        if all(item.status in _TERMINAL_ITEM_STATES for item in value.items)
        else "active"
    )
    await session.commit()

    if promote_items and all(item.status in _TERMINAL_ITEM_STATES for item in promote_items):
        await _reconcile_and_promote(
            session,
            session_id,
            caller,
            storage=storage,
            llm=llm,
            desensitizer=desensitizer,
            trace_id=trace_id,
        )


_VISIBLE_PROCESSING_STAGES = {
    "upload_saved",
    "text_extraction",
    "ocr_queued",
    "ocr_in_progress",
    "ocr_failed",
    "canonical_markdown_generation",
    "content_generation",
    "waiting_generation_config",
    "content_generation_failed",
    "content_result_persistence_failed",
    "processing_state_persistence_failed",
}


def _visible_processing_stage(stage: str | None) -> str | None:
    return stage if stage is not None and stage in _VISIBLE_PROCESSING_STAGES else None


async def _response(session: AsyncSession, value: UploadSession) -> UploadSessionResponse:
    visible_items = [item for item in value.items if item.status != "cancelled"]
    task_ids = [item.ingest_task_id for item in visible_items if item.ingest_task_id]
    task_facts: dict[uuid.UUID, tuple[str | None, int, str | None, datetime | None]] = {
        task_id: (processing_stage, retry_count, error_type, updated_at)
        for task_id, processing_stage, retry_count, error_type, updated_at in (
            await session.execute(
                select(
                    IngestTask.id,
                    IngestTask.processing_stage,
                    IngestTask.retry_count,
                    IngestTask.error_type,
                    IngestTask.updated_at,
                ).where(IngestTask.id.in_(task_ids))
            )
        ).all()
    }
    states = [item.status for item in visible_items]
    active_batches = [
        item.batch_index for item in visible_items if item.status not in _TERMINAL_ITEM_STATES
    ]
    completed = sum(state in _COMPLETED_ITEM_STATES for state in states)
    processing = states.count("processing") + states.count("uploading")
    waiting = states.count("waiting") + states.count("waiting_upload")
    failed = states.count("failed")
    status = "completed" if value.upload_completed and not active_batches else "active"
    return UploadSessionResponse(
        id=value.id,
        status=status,
        total_files=value.total_files,
        completed_files=completed,
        processing_files=processing,
        waiting_files=waiting,
        failed_files=failed,
        current_batch_number=min(active_batches) + 1 if active_batches else None,
        total_batches=value.total_batches,
        uploaded_files=sum(item.ingest_task_id is not None for item in visible_items),
        uploaded_batches=value.next_transport_batch_index,
        upload_completed=value.upload_completed,
        created_at=value.created_at,
        updated_at=value.updated_at,
        items=[
            UploadSessionItemResponse(
                id=item.id,
                ordinal=item.ordinal,
                batch_number=item.batch_index + 1,
                transport_batch_number=(
                    item.transport_batch_index + 1
                    if item.transport_batch_index is not None
                    else None
                ),
                file_name=item.file_name,
                file_size=item.file_size,
                file_type=item.file_type,
                status=item.status,
                error_code=item.safe_error_code,
                error_message=item.safe_error_message,
                same_name_warning=item.same_name_warning,
                retryable=(
                    item.status == "failed"
                    and item.ingest_task_id is not None
                    and task_facts.get(item.ingest_task_id, (None, 0, None, None))[2]
                    not in {"configuration_error", "authentication_error", "model_unavailable"}
                ),
                retry_count=(
                    task_facts.get(item.ingest_task_id, (None, 0, None, None))[1]
                    if item.ingest_task_id is not None
                    else 0
                ),
                last_attempt_at=(
                    task_facts.get(item.ingest_task_id, (None, 0, None, None))[3]
                    if item.ingest_task_id is not None
                    else None
                ),
                processing_stage=_visible_processing_stage(
                    task_facts.get(item.ingest_task_id, (None, 0, None, None))[0]
                    if item.ingest_task_id is not None
                    else None
                ),
                bytes_available=item.ingest_task_id is not None,
            )
            for item in visible_items
        ],
    )


async def get_session(
    session: AsyncSession,
    caller: CallerContext,
    session_id: uuid.UUID,
    *,
    storage: LocalFileStorage,
    llm: LLMClient | NullLLMClient,
    desensitizer: DesensitizationEngine,
    trace_id: str,
    promote: bool = True,
) -> UploadSessionResponse:
    if not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可查看上传会话")
    value = await _load_owned_session(session, caller, session_id)
    if promote and value.upload_completed:
        await _reconcile_and_promote(
            session,
            session_id,
            caller,
            storage=storage,
            llm=llm,
            desensitizer=desensitizer,
            trace_id=trace_id,
        )
    return await _response(session, await _load_owned_session(session, caller, session_id))


async def list_sessions(
    session: AsyncSession,
    caller: CallerContext,
    *,
    storage: LocalFileStorage,
    llm: LLMClient | NullLLMClient,
    desensitizer: DesensitizationEngine,
    trace_id: str,
) -> UploadSessionListResponse:
    if not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可查看上传会话")
    ids = list(
        (
            await session.execute(
                select(UploadSession.id)
                .where(UploadSession.created_by == caller.user_id)
                .order_by(UploadSession.created_at.desc())
                .limit(10)
            )
        ).scalars()
    )
    items = [
        await get_session(
            session,
            caller,
            session_id,
            storage=storage,
            llm=llm,
            desensitizer=desensitizer,
            trace_id=trace_id,
        )
        for session_id in ids
    ]
    return UploadSessionListResponse(items=items, total=len(items))


async def retry_item(
    session: AsyncSession,
    caller: CallerContext,
    session_id: uuid.UUID,
    item_id: uuid.UUID,
    *,
    storage: LocalFileStorage,
    llm: LLMClient | NullLLMClient,
    desensitizer: DesensitizationEngine,
    trace_id: str,
) -> UploadSessionResponse:
    value = await _load_owned_session(session, caller, session_id)
    item = next((candidate for candidate in value.items if candidate.id == item_id), None)
    if item is None:
        raise _denied(404, "upload_item_not_found", "上传文件不存在")
    if item.status != "failed" or item.ingest_task_id is None:
        raise _denied(409, "upload_item_not_retryable", "该文件当前不可重试")
    task = (
        await session.execute(
            select(IngestTask)
            .where(IngestTask.id == item.ingest_task_id, IngestTask.created_by == caller.user_id)
            .options(
                selectinload(IngestTask.ai_result), selectinload(IngestTask.canonical_markdown)
            )
        )
    ).scalar_one_or_none()
    if task is None or not storage.exists(task.source_file_ref):
        raise _denied(409, "upload_source_unavailable", "源文件不可用，请重新选择文件")
    if task.processing_stage == "waiting_generation_config" and isinstance(llm, NullLLMClient):
        raise _denied(
            409, "generation_model_not_configured", "内容生成模型尚未配置，本次重试未发起"
        )
    resume_stage = (
        "ocr_queued"
        if task.processing_stage == "ocr_failed"
        else "content_generation"
        if task.canonical_markdown and task.canonical_markdown.status == "ready"
        else "text_extraction"
    )
    item_claim = await session.execute(
        update(UploadSessionItem)
        .where(
            UploadSessionItem.id == item.id,
            UploadSessionItem.session_id == session_id,
            UploadSessionItem.ingest_task_id == task.id,
            UploadSessionItem.status == "failed",
        )
        .values(status="processing", safe_error_code=None, safe_error_message=None)
    )
    task_claim = await session.execute(
        update(IngestTask)
        .where(
            IngestTask.id == task.id,
            IngestTask.created_by == caller.user_id,
            IngestTask.status == IngestStatus.failed.value,
        )
        .values(
            status=IngestStatus.processing.value,
            processing_stage=resume_stage,
            error_type=None,
            error_message=None,
            retry_count=IngestTask.retry_count + 1,
        )
    )
    if getattr(item_claim, "rowcount", 0) != 1 or getattr(task_claim, "rowcount", 0) != 1:
        await session.rollback()
        raise _denied(409, "upload_item_not_retryable", "该文件已被处理或正在重试")
    await session.execute(
        update(UploadSession)
        .where(UploadSession.id == session_id, UploadSession.created_by == caller.user_id)
        .values(status="active")
    )
    await session.commit()
    try:
        result = await enqueue_ingest_processing(
            session,
            task.id,
            storage=storage,
            llm=llm,
            desensitizer=desensitizer,
            trace_id=trace_id,
        )
        await session.execute(
            update(UploadSessionItem)
            .where(UploadSessionItem.id == item.id, UploadSessionItem.status == "processing")
            .values(
                status=(
                    "awaiting_confirmation"
                    if result == IngestStatus.pending_confirmation.value
                    else "failed"
                    if result == IngestStatus.failed.value
                    else "processing"
                )
            )
        )
        await session.commit()
    except Exception:
        await session.rollback()
        failure_stage = "ocr_failed" if resume_stage == "ocr_queued" else resume_stage
        await session.execute(
            update(IngestTask)
            .where(IngestTask.id == task.id, IngestTask.status == IngestStatus.processing.value)
            .values(
                status=IngestStatus.failed.value,
                processing_stage=failure_stage,
                error_type="queue_unavailable",
                error_message="处理任务暂时无法排队",
            )
        )
        await session.execute(
            update(UploadSessionItem)
            .where(UploadSessionItem.id == item.id, UploadSessionItem.status == "processing")
            .values(
                status="failed",
                safe_error_code="queue_unavailable",
                safe_error_message="处理任务暂时无法排队，请重试",
            )
        )
        await session.commit()
    session.expire_all()
    return await _response(session, await _load_owned_session(session, caller, session_id))


async def remove_item(
    session: AsyncSession,
    caller: CallerContext,
    session_id: uuid.UUID,
    item_id: uuid.UUID,
    *,
    storage: LocalFileStorage,
) -> UploadSessionResponse:
    value = await _load_owned_session(session, caller, session_id, lock=True)
    item = next((candidate for candidate in value.items if candidate.id == item_id), None)
    if item is None:
        raise _denied(404, "upload_item_not_found", "上传文件不存在")
    if item.status != "failed":
        raise _denied(409, "upload_item_not_failed", "仅可移除终态失败文件")
    if item.ingest_task_id is not None:
        task = (
            await session.execute(
                select(IngestTask).where(
                    IngestTask.id == item.ingest_task_id,
                    IngestTask.created_by == caller.user_id,
                    IngestTask.status == IngestStatus.failed.value,
                    IngestTask.result_asset_id.is_(None),
                )
            )
        ).scalar_one_or_none()
        if task is None:
            raise _denied(
                409,
                "upload_item_cleanup_conflict",
                "该失败项已发生状态变化，请刷新后重试",
            )
        storage.delete(task.source_file_ref)
        await session.delete(task)
        item.ingest_task_id = None
    item.status = "cancelled"
    item.safe_error_code = None
    item.safe_error_message = None
    value.status = (
        "completed"
        if all(candidate.status in _TERMINAL_ITEM_STATES for candidate in value.items)
        else "active"
    )
    await session.commit()
    return await _response(session, await _load_owned_session(session, caller, session_id))


async def remove_failed_items(
    session: AsyncSession,
    caller: CallerContext,
    session_id: uuid.UUID,
    *,
    storage: LocalFileStorage,
) -> UploadSessionResponse:
    """Remove only caller-owned failed tasks and controlled temporary data."""
    value = await _load_owned_session(session, caller, session_id, lock=True)
    for item in [candidate for candidate in value.items if candidate.status == "failed"]:
        if item.ingest_task_id is not None:
            task = (
                await session.execute(
                    select(IngestTask).where(
                        IngestTask.id == item.ingest_task_id,
                        IngestTask.created_by == caller.user_id,
                        IngestTask.status == IngestStatus.failed.value,
                        IngestTask.result_asset_id.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if task is None:
                continue
            storage.delete(task.source_file_ref)
            await session.delete(task)
            item.ingest_task_id = None
        item.status = "cancelled"
        item.safe_error_code = None
        item.safe_error_message = None
    value.status = (
        "completed"
        if all(candidate.status in _TERMINAL_ITEM_STATES for candidate in value.items)
        else "active"
    )
    await session.commit()
    return await _response(session, await _load_owned_session(session, caller, session_id))
