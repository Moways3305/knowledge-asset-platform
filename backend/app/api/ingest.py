"""入库流水线 API。

只做 upload / ai-result / confirm + 可选 admin 只读列表。权限委托 service，
不写权限矩阵；不返回内部存储引用 / 真实上传下载 URL。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.enums import AuditAction
from app.schemas.ingest import (
    AdminIngestListResponse,
    IngestAiResultResponse,
    IngestBulkConfirmItemResult,
    IngestBulkConfirmRequest,
    IngestBulkConfirmResponse,
    IngestConfirmRequest,
    IngestConfirmResponse,
    IngestParseRefreshResponse,
    IngestTaskStatusResponse,
    IngestUploadResponse,
    PendingIngestListResponse,
    UploadClientRejection,
    UploadSessionInitRequest,
    UploadSessionListResponse,
    UploadSessionResponse,
    UploadTransportFailureRequest,
)
from app.schemas.permission import CallerContext
from app.schemas.upload_duplicates import (
    DuplicateDecisionRequest,
    DuplicateDecisionResponse,
    MyUploadListResponse,
)
from app.services import bulk_operations as bulk_service
from app.services import ingest as ingest_service
from app.services import ingest_bulk, upload_duplicates
from app.services import ingest_status as ingest_status_service
from app.services import upload_sessions as upload_session_service
from app.services.desensitization import DesensitizationEngine, get_desensitizer
from app.services.generation_models import get_generation_llm_client
from app.services.llm_client import LLMClient, NullLLMClient
from app.services.storage import MAX_UPLOAD_BYTES, LocalFileStorage, StorageError, get_storage
from app.services.weknora_client import (
    NullWeKnoraClient,
    WeKnoraClient,
    get_weknora_client,
)

router = APIRouter(prefix="/api/v1", tags=["ingest"])

_LOCAL_UPLOAD_EXTENSIONS = {
    "md",
    "markdown",
    "txt",
    "pdf",
    "doc",
    "docx",
    "ppt",
    "pptx",
    "xls",
    "xlsx",
    "png",
    "jpg",
    "jpeg",
    "tif",
    "tiff",
    "bmp",
    "webp",
}
_UPLOAD_READ_TIMEOUT_SECONDS = 120
_MAX_CLIENT_REJECTIONS = 5000
_CLIENT_FORMED_ON_LIMIT = 200
_CLIENT_REJECTIONS_ADAPTER = TypeAdapter(list[UploadClientRejection])
_TRANSPORT_ITEM_IDS_ADAPTER = TypeAdapter(list[uuid.UUID])


def _normalize_formed_on(value: str | None) -> str | None:
    """校验客户端提交的文件形成日期建议（YYYY-MM-DD），非法 → None。"""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


def _formed_on_for(client_map: dict[str, str], file_name: str) -> str | None:
    """文件形成日期建议：客户端 lastModified 优先，其次文件名正则兜底。"""
    client_value = _normalize_formed_on(client_map.get(file_name))
    if client_value:
        return client_value
    return upload_session_service.extract_formed_on_from_filename(file_name)


@router.post("/ingest/upload-sessions/init", response_model=UploadSessionResponse)
async def initialize_upload_session(
    body: UploadSessionInitRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
    llm: LLMClient | NullLLMClient = Depends(get_generation_llm_client),
    desensitizer: DesensitizationEngine = Depends(get_desensitizer),
) -> UploadSessionResponse:
    manifest: list[dict] = []
    for item in body.manifest:
        rejection = item.rejection
        file_name = item.file_name
        metadata_message = upload_session_service.macos_metadata_error(file_name)
        extension = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        if item.file_size > MAX_UPLOAD_BYTES:
            rejection = UploadClientRejection(
                file_name=file_name,
                file_size=item.file_size,
                file_type=item.file_type,
                error_code="file_too_large",
            )
        elif metadata_message is not None:
            rejection = UploadClientRejection(
                file_name=file_name,
                file_size=item.file_size,
                file_type=item.file_type,
                error_code="macos_metadata",
            )
        elif extension not in _LOCAL_UPLOAD_EXTENSIONS:
            rejection = UploadClientRejection(
                file_name=file_name,
                file_size=item.file_size,
                file_type=item.file_type,
                error_code="unsupported_file_type",
            )
        safe_rejection = None
        if rejection is not None:
            safe_rejection = {
                "error_code": rejection.error_code,
                "error_message": {
                    "file_too_large": "文件超过 25 MiB 大小上限",
                    "unsupported_file_type": "该文件类型暂不支持上传",
                    "macos_metadata": upload_session_service.MACOS_METADATA_MESSAGE,
                }.get(rejection.error_code, upload_session_service.UNREADABLE_FILE_MESSAGE),
            }
        manifest.append(
            {
                "client_file_key": item.client_file_key,
                "file_name": file_name,
                "file_size": item.file_size,
                "file_type": item.file_type,
                "formed_on": _normalize_formed_on(item.formed_on),
                "transport_batch_index": item.transport_batch_index,
                "rejection": safe_rejection,
            }
        )
    value = await upload_session_service.initialize_transport_session(
        session,
        caller,
        session_id=body.session_id,
        manifest=manifest,
        total_transport_batches=body.total_transport_batches,
        target_scope=body.target_scope,
        target_project_id=body.target_project_id,
    )
    return await upload_session_service.get_session(
        session,
        caller,
        value.id,
        storage=storage,
        llm=llm,
        desensitizer=desensitizer,
        trace_id=get_trace_id(request),
        promote=False,
    )


@router.post("/ingest/upload-sessions/{session_id}/batches", response_model=UploadSessionResponse)
async def append_upload_transport_batch(
    session_id: uuid.UUID,
    request: Request,
    batch_id: str = Form(),
    batch_index: int = Form(),
    item_ids: str = Form(),
    files: list[UploadFile] = File(),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
    llm: LLMClient | NullLLMClient = Depends(get_generation_llm_client),
    desensitizer: DesensitizationEngine = Depends(get_desensitizer),
) -> UploadSessionResponse:
    if len(batch_id) > 100 or batch_index < 0:
        raise HTTPException(status_code=422, detail={"denied_reason": "invalid_transport_batch"})
    try:
        parsed_item_ids = _TRANSPORT_ITEM_IDS_ADAPTER.validate_python(json.loads(item_ids))
    except (json.JSONDecodeError, ValidationError):
        raise HTTPException(
            status_code=422,
            detail={"denied_reason": "invalid_transport_batch_manifest", "message": "批次清单无效"},
        ) from None
    if len(files) != len(parsed_item_ids) or not 1 <= len(files) <= 10:
        raise HTTPException(
            status_code=422,
            detail={
                "denied_reason": "invalid_transport_batch_count",
                "message": "批次文件数量无效",
            },
        )
    if await upload_session_service.preflight_transport_batch(
        session,
        caller,
        session_id=session_id,
        batch_id=batch_id,
        batch_index=batch_index,
        manifest=[
            (item_id, file.filename or "file", max(0, file.size or 0))
            for item_id, file in zip(parsed_item_ids, files, strict=True)
        ],
    ):
        return await upload_session_service.get_session(
            session,
            caller,
            session_id,
            storage=storage,
            llm=llm,
            desensitizer=desensitizer,
            trace_id=get_trace_id(request),
            promote=False,
        )
    declared_total = sum(max(0, file.size or 0) for file in files)
    if declared_total > upload_session_service.TRANSPORT_BATCH_MAX_BYTES and not (
        len(files) == 1 and declared_total <= MAX_UPLOAD_BYTES
    ):
        raise HTTPException(
            status_code=413,
            detail={"denied_reason": "transport_batch_too_large", "message": "上传批次超过 20 MiB"},
        )
    candidates: list[tuple[uuid.UUID, upload_session_service.UploadCandidate]] = []
    persisted = False
    try:
        for item_id, file in zip(parsed_item_ids, files, strict=True):
            content = await asyncio.wait_for(
                file.read(MAX_UPLOAD_BYTES + 1), timeout=_UPLOAD_READ_TIMEOUT_SECONDS
            )
            if len(content) > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail={"denied_reason": "file_too_large", "message": "文件超过 25 MiB"},
                )
            storage_ref = storage.save(content, original_name=file.filename or "file")
            candidates.append(
                (
                    item_id,
                    upload_session_service.UploadCandidate(
                        file_name=file.filename or "file",
                        file_size=len(content),
                        file_type=file.content_type,
                        storage_ref=storage_ref,
                        content_hash=hashlib.sha256(content).hexdigest(),
                    ),
                )
            )
        await upload_session_service.append_transport_batch(
            session,
            caller,
            session_id=session_id,
            batch_id=batch_id,
            batch_index=batch_index,
            candidates=candidates,
        )
        persisted = True
    except asyncio.TimeoutError:
        await upload_session_service.fail_transport_items(
            session,
            caller,
            session_id=session_id,
            item_ids=parsed_item_ids,
            error_code="upload_timeout",
            message="上传读取超过 120 秒，请检查网络后重试",
        )
        raise HTTPException(
            status_code=408,
            detail={"denied_reason": "upload_timeout", "message": "上传读取超时"},
        ) from None
    except StorageError:
        await upload_session_service.fail_transport_items(
            session,
            caller,
            session_id=session_id,
            item_ids=[item_id],
            error_code="storage_failed",
            message="文件暂时无法安全保存，请重试",
        )
        raise HTTPException(
            status_code=503,
            detail={"denied_reason": "storage_failed", "message": "文件保存失败"},
        ) from None
    finally:
        if not persisted:
            for _item_id, candidate in candidates:
                if candidate.storage_ref is not None:
                    try:
                        storage.delete(candidate.storage_ref)
                    except OSError:
                        # Cleanup is best-effort and must not mask the original safe response.
                        pass
    return await upload_session_service.get_session(
        session,
        caller,
        session_id,
        storage=storage,
        llm=llm,
        desensitizer=desensitizer,
        trace_id=get_trace_id(request),
        promote=False,
    )


@router.post(
    "/ingest/upload-sessions/{session_id}/transport-failure",
    response_model=UploadSessionResponse,
)
async def record_upload_transport_failure(
    session_id: uuid.UUID,
    body: UploadTransportFailureRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
    llm: LLMClient | NullLLMClient = Depends(get_generation_llm_client),
    desensitizer: DesensitizationEngine = Depends(get_desensitizer),
) -> UploadSessionResponse:
    message = {
        "proxy_rejected": "上传请求被网关拒绝，请缩小批次后重试",
        "upload_timeout": "上传超过 120 秒，请检查网络后重试",
        "network_interrupted": "上传连接中断；原文件仍在本浏览器时可重试",
    }[body.error_code]
    await upload_session_service.fail_transport_items(
        session,
        caller,
        session_id=session_id,
        item_ids=body.item_ids,
        error_code=body.error_code,
        message=message,
        batch_id=body.batch_id,
        batch_index=body.batch_index,
    )
    return await upload_session_service.get_session(
        session,
        caller,
        session_id,
        storage=storage,
        llm=llm,
        desensitizer=desensitizer,
        trace_id=get_trace_id(request),
        promote=False,
    )


@router.post(
    "/ingest/upload-sessions/{session_id}/items/{item_id}/bytes",
    response_model=UploadSessionResponse,
)
async def replace_upload_transport_item_bytes(
    session_id: uuid.UUID,
    item_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
    llm: LLMClient | NullLLMClient = Depends(get_generation_llm_client),
    desensitizer: DesensitizationEngine = Depends(get_desensitizer),
) -> UploadSessionResponse:
    try:
        content = await asyncio.wait_for(
            file.read(MAX_UPLOAD_BYTES + 1), timeout=_UPLOAD_READ_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        await upload_session_service.fail_transport_items(
            session,
            caller,
            session_id=session_id,
            item_ids=[item_id],
            error_code="upload_timeout",
            message="上传读取超过 120 秒，请检查网络后重试",
        )
        raise HTTPException(
            status_code=408,
            detail={"denied_reason": "upload_timeout", "message": "上传读取超时"},
        ) from None
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"denied_reason": "file_too_large", "message": "文件超过 25 MiB"},
        )
    try:
        storage_ref = storage.save(content, original_name=file.filename or "file")
    except StorageError:
        await upload_session_service.fail_transport_items(
            session,
            caller,
            session_id=session_id,
            item_ids=[item_id],
            error_code="storage_failed",
            message="文件暂时无法安全保存，请重试",
        )
        raise HTTPException(
            status_code=503,
            detail={"denied_reason": "storage_failed", "message": "文件保存失败"},
        ) from None
    await upload_session_service.replace_transport_item_bytes(
        session,
        caller,
        session_id=session_id,
        item_id=item_id,
        candidate=upload_session_service.UploadCandidate(
            file_name=file.filename or "file",
            file_size=len(content),
            file_type=file.content_type,
            storage_ref=storage_ref,
            content_hash=hashlib.sha256(content).hexdigest(),
        ),
    )
    return await upload_session_service.get_session(
        session,
        caller,
        session_id,
        storage=storage,
        llm=llm,
        desensitizer=desensitizer,
        trace_id=get_trace_id(request),
        promote=False,
    )


@router.post("/ingest/upload-sessions/{session_id}/complete", response_model=UploadSessionResponse)
async def complete_upload_transport_session(
    session_id: uuid.UUID,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
    llm: LLMClient | NullLLMClient = Depends(get_generation_llm_client),
    desensitizer: DesensitizationEngine = Depends(get_desensitizer),
) -> UploadSessionResponse:
    await upload_session_service.complete_transport_session(session, caller, session_id=session_id)
    return await upload_session_service.get_session(
        session,
        caller,
        session_id,
        storage=storage,
        llm=llm,
        desensitizer=desensitizer,
        trace_id=get_trace_id(request),
    )


@router.post("/ingest/upload", response_model=IngestUploadResponse)
async def create_upload(
    request: Request,
    file: UploadFile = File(...),
    target_scope: str | None = Form(default=None),
    target_project_id: uuid.UUID | None = Form(default=None),
    formed_on: str | None = Form(default=None),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
    llm: LLMClient | NullLLMClient = Depends(get_generation_llm_client),
    desensitizer: DesensitizationEngine = Depends(get_desensitizer),
) -> IngestUploadResponse:
    """Path B 本地上传：接收真实文件字节（multipart/form-data）并经存储服务持久化，
    随后对抽取文本调外部 LLM 出内容处理草稿（失败降级，上传不失败）。

    读取时即做大小上限保护（超限 413），避免把超大文件全部读入内存。
    """
    file_name = file.filename or "file"
    metadata_message = upload_session_service.macos_metadata_error(file_name)
    if metadata_message is not None:
        raise HTTPException(
            status_code=422,
            detail={"denied_reason": "macos_metadata", "message": metadata_message},
        )
    try:
        content = await asyncio.wait_for(
            file.read(MAX_UPLOAD_BYTES + 1),
            timeout=_UPLOAD_READ_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=422,
            detail={
                "denied_reason": "file_read_timeout",
                "message": upload_session_service.UNREADABLE_FILE_MESSAGE,
            },
        ) from None
    except (OSError, RuntimeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail={
                "denied_reason": "file_unreadable",
                "message": upload_session_service.UNREADABLE_FILE_MESSAGE,
            },
        ) from None
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"denied_reason": "file_too_large", "message": "文件超出大小上限"},
        )
    return await ingest_service.create_upload(
        session,
        caller,
        content=content,
        file_name=file_name,
        file_mime_type=file.content_type,
        target_scope=target_scope,
        target_project_id=target_project_id,
        formed_on=_normalize_formed_on(formed_on)
        or upload_session_service.extract_formed_on_from_filename(file_name),
        storage=storage,
        llm=llm,
        desensitizer=desensitizer,
        trace_id=get_trace_id(request),
    )


@router.post("/ingest/upload-sessions", response_model=UploadSessionResponse)
async def create_upload_session(
    request: Request,
    files: list[UploadFile] | None = File(default=None),
    client_rejections: str | None = Form(default=None),
    client_formed_on: str | None = Form(default=None),
    session_id: uuid.UUID | None = Form(default=None),
    target_scope: str | None = Form(default=None),
    target_project_id: uuid.UUID | None = Form(default=None),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
    llm: LLMClient | NullLLMClient = Depends(get_generation_llm_client),
    desensitizer: DesensitizationEngine = Depends(get_desensitizer),
) -> UploadSessionResponse:
    """Persist every submitted file and derive stable, unbounded 200-item batches."""
    upload_session_service.authorize_create(caller)
    existing = await upload_session_service.get_session_if_exists(
        session,
        caller,
        session_id,
        storage=storage,
        llm=llm,
        desensitizer=desensitizer,
        trace_id=get_trace_id(request),
    )
    if existing is not None:
        return existing
    candidates: list[upload_session_service.UploadCandidate] = []
    client_formed_map: dict[str, str] = {}
    if client_formed_on:
        try:
            parsed_formed_on = json.loads(client_formed_on)
            if (
                isinstance(parsed_formed_on, dict)
                and len(parsed_formed_on) <= _CLIENT_FORMED_ON_LIMIT
            ):
                client_formed_map = {
                    str(k): str(v)
                    for k, v in parsed_formed_on.items()
                    if isinstance(k, str) and isinstance(v, str)
                }
        except (json.JSONDecodeError, TypeError, ValueError):
            client_formed_map = {}
    if client_rejections:
        try:
            parsed_rejections = _CLIENT_REJECTIONS_ADAPTER.validate_python(
                json.loads(client_rejections)
            )
        except (json.JSONDecodeError, ValidationError):
            raise HTTPException(
                status_code=422,
                detail={
                    "denied_reason": "invalid_client_rejections",
                    "message": "上传失败项格式无效",
                },
            ) from None
        if len(parsed_rejections) > _MAX_CLIENT_REJECTIONS:
            raise HTTPException(
                status_code=422,
                detail={
                    "denied_reason": "too_many_client_rejections",
                    "message": "单次上传文件数量超出安全上限",
                },
            )
        for rejected in parsed_rejections:
            if len(rejected.file_name) > 500:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "denied_reason": "invalid_client_rejection_name",
                        "message": "文件名超出安全上限",
                    },
                )
            metadata_message = upload_session_service.macos_metadata_error(rejected.file_name)
            if rejected.error_code == "macos_metadata" and metadata_message is None:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "denied_reason": "invalid_macos_metadata_claim",
                        "message": "macOS 元数据判定无效",
                    },
                )
            extension = (
                rejected.file_name.rsplit(".", 1)[-1].lower() if "." in rejected.file_name else ""
            )
            if (
                rejected.error_code == "unsupported_file_type"
                and extension in _LOCAL_UPLOAD_EXTENSIONS
            ) or (
                rejected.error_code == "file_too_large" and rejected.file_size <= MAX_UPLOAD_BYTES
            ):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "denied_reason": "invalid_client_rejection_claim",
                        "message": "上传门禁判定无效",
                    },
                )
            rejection_message = {
                "macos_metadata": metadata_message,
                "unsupported_file_type": "该文件类型暂不支持上传",
                "file_too_large": "文件超过 25 MiB 大小上限",
            }.get(
                rejected.error_code,
                upload_session_service.UNREADABLE_FILE_MESSAGE,
            )
            candidates.append(
                upload_session_service.UploadCandidate(
                    file_name=rejected.file_name,
                    file_size=max(0, rejected.file_size),
                    file_type=rejected.file_type,
                    error_code=rejected.error_code,
                    error_message=rejection_message,
                )
            )
    for file in files or []:
        file_name = file.filename or "file"
        metadata_message = upload_session_service.macos_metadata_error(file_name)
        if metadata_message is not None:
            candidates.append(
                upload_session_service.UploadCandidate(
                    file_name=file_name,
                    file_size=max(0, file.size or 0),
                    file_type=file.content_type,
                    error_code="macos_metadata",
                    error_message=metadata_message,
                )
            )
            continue
        extension = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        if extension not in _LOCAL_UPLOAD_EXTENSIONS:
            candidates.append(
                upload_session_service.UploadCandidate(
                    file_name=file_name,
                    file_size=max(0, file.size or 0),
                    file_type=file.content_type,
                    error_code="unsupported_file_type",
                    error_message="该文件类型暂不支持上传",
                )
            )
            continue
        if file.size is not None and file.size > MAX_UPLOAD_BYTES:
            candidates.append(
                upload_session_service.UploadCandidate(
                    file_name=file_name,
                    file_size=file.size,
                    file_type=file.content_type,
                    error_code="file_too_large",
                    error_message="文件超过 25 MiB 大小上限",
                )
            )
            continue
        try:
            content = await asyncio.wait_for(
                file.read(MAX_UPLOAD_BYTES + 1),
                timeout=_UPLOAD_READ_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            candidates.append(
                upload_session_service.UploadCandidate(
                    file_name=file_name,
                    file_size=max(0, file.size or 0),
                    file_type=file.content_type,
                    error_code="file_read_timeout",
                    error_message=upload_session_service.UNREADABLE_FILE_MESSAGE,
                )
            )
            continue
        except (OSError, RuntimeError, ValueError):
            candidates.append(
                upload_session_service.UploadCandidate(
                    file_name=file_name,
                    file_size=max(0, file.size or 0),
                    file_type=file.content_type,
                    error_code="file_unreadable",
                    error_message=upload_session_service.UNREADABLE_FILE_MESSAGE,
                )
            )
            continue
        if len(content) > MAX_UPLOAD_BYTES:
            candidates.append(
                upload_session_service.UploadCandidate(
                    file_name=file_name,
                    file_size=len(content),
                    file_type=file.content_type,
                    error_code="file_too_large",
                    error_message="文件超过 25 MiB 大小上限",
                )
            )
        elif not content:
            candidates.append(
                upload_session_service.UploadCandidate(
                    file_name=file_name,
                    file_size=0,
                    file_type=file.content_type,
                    error_code="empty_file",
                    error_message="文件为空，请检查后重试",
                )
            )
        else:
            try:
                storage_ref = storage.save(content, original_name=file_name)
                candidates.append(
                    upload_session_service.UploadCandidate(
                        file_name=file_name,
                        file_size=len(content),
                        file_type=file.content_type,
                        storage_ref=storage_ref,
                        content_hash=hashlib.sha256(content).hexdigest(),
                        suggested_formed_on=_formed_on_for(client_formed_map, file_name),
                    )
                )
            except StorageError:
                candidates.append(
                    upload_session_service.UploadCandidate(
                        file_name=file_name,
                        file_size=len(content),
                        file_type=file.content_type,
                        error_code="storage_failed",
                        error_message="文件暂时无法安全保存，请重试",
                    )
                )
    return await upload_session_service.create_session(
        session,
        caller,
        requested_session_id=session_id,
        candidates=candidates,
        target_scope=target_scope,
        target_project_id=target_project_id,
        storage=storage,
        llm=llm,
        desensitizer=desensitizer,
        trace_id=get_trace_id(request),
    )


@router.get("/ingest/upload-sessions", response_model=UploadSessionListResponse)
async def list_upload_sessions(
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
    llm: LLMClient | NullLLMClient = Depends(get_generation_llm_client),
    desensitizer: DesensitizationEngine = Depends(get_desensitizer),
) -> UploadSessionListResponse:
    return await upload_session_service.list_sessions(
        session,
        caller,
        storage=storage,
        llm=llm,
        desensitizer=desensitizer,
        trace_id=get_trace_id(request),
    )


@router.get("/ingest/upload-sessions/{session_id}", response_model=UploadSessionResponse)
async def get_upload_session(
    session_id: uuid.UUID,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
    llm: LLMClient | NullLLMClient = Depends(get_generation_llm_client),
    desensitizer: DesensitizationEngine = Depends(get_desensitizer),
) -> UploadSessionResponse:
    return await upload_session_service.get_session(
        session,
        caller,
        session_id,
        storage=storage,
        llm=llm,
        desensitizer=desensitizer,
        trace_id=get_trace_id(request),
    )


@router.post(
    "/ingest/upload-sessions/{session_id}/items/{item_id}/retry",
    response_model=UploadSessionResponse,
)
async def retry_upload_session_item(
    session_id: uuid.UUID,
    item_id: uuid.UUID,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
    llm: LLMClient | NullLLMClient = Depends(get_generation_llm_client),
    desensitizer: DesensitizationEngine = Depends(get_desensitizer),
) -> UploadSessionResponse:
    return await upload_session_service.retry_item(
        session,
        caller,
        session_id,
        item_id,
        storage=storage,
        llm=llm,
        desensitizer=desensitizer,
        trace_id=get_trace_id(request),
    )


@router.delete(
    "/ingest/upload-sessions/{session_id}/items/{item_id}",
    response_model=UploadSessionResponse,
)
async def remove_upload_session_item(
    session_id: uuid.UUID,
    item_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
) -> UploadSessionResponse:
    return await upload_session_service.remove_item(
        session, caller, session_id, item_id, storage=storage
    )


@router.delete(
    "/ingest/upload-sessions/{session_id}/failed-items",
    response_model=UploadSessionResponse,
)
async def remove_failed_upload_session_items(
    session_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
) -> UploadSessionResponse:
    return await upload_session_service.remove_failed_items(
        session, caller, session_id, storage=storage
    )


@router.get("/ingest/pending", response_model=PendingIngestListResponse)
async def list_pending(
    source: str | None = None,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> PendingIngestListResponse:
    """业务侧待确认任务列表。

    `?source=path_a_wecom` 拉取企微微盘扫描创建的待确认任务。
    只返回调用人本人创建的待确认任务；纯 admin → 403。
    """
    items = await ingest_service.list_pending(session, caller, source=source)
    return PendingIngestListResponse(items=items, total=len(items))


@router.get("/ingest/my-uploads", response_model=MyUploadListResponse)
async def list_my_uploads(
    scope: str | None = Query(default=None),
    final_status: str | None = Query(default=None),
    duplicate_result: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> MyUploadListResponse:
    items = await upload_duplicates.list_my_uploads(
        session,
        caller,
        scope=scope,
        final_status=final_status,
        duplicate_result=duplicate_result,
        since=since,
        until=until,
    )
    return MyUploadListResponse(items=items, total=len(items))


@router.post(
    "/ingest/{task_id}/duplicate-decision",
    response_model=DuplicateDecisionResponse,
)
async def decide_upload_duplicate(
    task_id: uuid.UUID,
    body: DuplicateDecisionRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> DuplicateDecisionResponse:
    return await upload_duplicates.decide_duplicate(
        session,
        caller,
        task_id,
        action=body.action,
        reason=body.reason,
        scope=body.target_scope.value,
        project_id=body.target_project_id,
        trace_id=get_trace_id(request),
    )


@router.delete("/ingest/{task_id}")
async def delete_pending_task(
    task_id: uuid.UUID,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """删除/取消待确认入库任务。

    仅创建人本人可删除，仅未确认的非中间态任务可删。
    会清理关联的存储文件和 AI 结果，并写入审计。
    """
    trace_id = get_trace_id(request)
    await ingest_service.delete_pending_task(session, caller, task_id, trace_id=trace_id)
    return {"ok": True}


@router.get("/ingest/{task_id}/ai-result", response_model=IngestAiResultResponse)
async def get_ai_result(
    task_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> IngestAiResultResponse:
    return await ingest_service.get_ai_result(session, caller, task_id)


@router.get("/ingest/{task_id}/status", response_model=IngestTaskStatusResponse)
async def get_task_status(
    task_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> IngestTaskStatusResponse:
    return await ingest_status_service.get_task_status(session, caller, task_id)


@router.post("/ingest/{task_id}/retry", response_model=IngestTaskStatusResponse)
async def retry_task(
    task_id: uuid.UUID,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
    llm: LLMClient | NullLLMClient = Depends(get_generation_llm_client),
    desensitizer: DesensitizationEngine = Depends(get_desensitizer),
    weknora: WeKnoraClient | NullWeKnoraClient = Depends(get_weknora_client),
) -> IngestTaskStatusResponse:
    return await ingest_status_service.retry_task(
        session,
        caller,
        task_id,
        storage=storage,
        llm=llm,
        desensitizer=desensitizer,
        weknora=weknora,
        trace_id=get_trace_id(request),
    )


@router.post(
    "/ingest/bulk-confirm",
    response_model=IngestBulkConfirmResponse,
    response_model_exclude_none=True,
)
async def bulk_confirm(
    body: IngestBulkConfirmRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
    weknora: WeKnoraClient | NullWeKnoraClient = Depends(get_weknora_client),
) -> IngestBulkConfirmResponse:
    """Confirm one explicit destination while preserving per-task authorization."""
    operation_id = uuid.uuid4()
    trace_id = get_trace_id(request)
    item_ids = [item.task_id for item in body.items]

    async def process_batch(batch):
        batch_results = []
        for item in batch:
            try:
                confirmation = (
                    item.confirmation
                    if isinstance(item.confirmation, IngestConfirmRequest)
                    else IngestConfirmRequest.model_validate(item.confirmation)
                )
                confirmation_result = await ingest_service.confirm(
                    session,
                    caller,
                    item.task_id,
                    confirmation,
                    trace_id,
                    storage=storage,
                    weknora=weknora,
                )
                batch_results.append(
                    IngestBulkConfirmItemResult(
                        item_id=item.task_id,
                        status="succeeded",
                        result_asset_id=confirmation_result.result_asset_id,
                        index_status=confirmation_result.index_status,
                    )
                )
            except ValidationError as exc:
                await session.rollback()
                batch_results.append(bulk_service.validation_error_result(item.task_id, exc))
            except HTTPException as exc:
                await session.rollback()
                batch_results.append(bulk_service.skipped_from_http(item.task_id, exc))
            except Exception:
                await session.rollback()
                already = await ingest_bulk.confirmed_task_result(session, item.task_id)
                batch_results.append(
                    already if already is not None else bulk_service.failed_item(item.task_id)
                )
        return batch_results

    results = await bulk_service.execute_in_controlled_batches(body.items, process_batch)
    response = bulk_service.terminal_response(operation_id, item_ids, results)
    await bulk_service.record_terminal_audit(
        session,
        caller=caller,
        action=AuditAction.ingest_bulk_confirmed.value,
        trace_id=trace_id,
        response=response,
        operation="confirm",
        target_scope=body.target_scope.value,
        project_id=body.target_project_id,
        client_operation_id=body.client_operation_id,
        request_index=body.request_index,
        request_count=body.request_count,
        total_submitted=body.total_submitted,
    )
    return IngestBulkConfirmResponse(
        **response.model_dump(exclude={"items"}),
        items=[IngestBulkConfirmItemResult.model_validate(item.model_dump()) for item in results],
    )


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
        session,
        caller,
        task_id,
        req,
        get_trace_id(request),
        storage=storage,
        weknora=weknora,
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
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> AdminIngestListResponse:
    items = await ingest_service.list_admin_ingest(session, caller, trace_id=get_trace_id(request))
    return AdminIngestListResponse(items=items, total=len(items))


_confirmed_task_result = ingest_bulk.confirmed_task_result
