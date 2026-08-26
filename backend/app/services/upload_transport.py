"""Upload transport commands and per-batch safety constraints."""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingest import (
    UploadSession,
    UploadSessionItem,
    UploadTransportBatch,
)
from app.schemas.permission import CallerContext
from app.services.upload_ingest_tasks import create_uploaded_ingest_task
from app.services.upload_session_repository import _load_owned_session, _visible_names
from app.services.upload_session_types import (
    BATCH_SIZE,
    SINGLE_FILE_MAX_BYTES,
    TRANSPORT_BATCH_MAX_BYTES,
    TRANSPORT_BATCH_MAX_FILES,
    UploadCandidate,
    _denied,
    _display_name,
    _normalized_name,
    authorize_create,
)


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
        task = await create_uploaded_ingest_task(
            session,
            storage_ref=candidate.storage_ref,
            file_name=item.file_name,
            file_type=candidate.file_type,
            file_size=candidate.file_size,
            content_hash=candidate.content_hash,
            suggested_formed_on=item.suggested_formed_on,
            target_scope=value.target_scope,
            target_project_id=value.target_project_id,
            created_by=caller.user_id,
        )
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
    task = await create_uploaded_ingest_task(
        session,
        storage_ref=candidate.storage_ref,
        file_name=item.file_name,
        file_type=candidate.file_type,
        file_size=candidate.file_size,
        content_hash=candidate.content_hash,
        suggested_formed_on=item.suggested_formed_on,
        target_scope=value.target_scope,
        target_project_id=value.target_project_id,
        created_by=caller.user_id,
    )
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
