"""Knowledge-base rebuild migration with version-level completion reconciliation.

The migration never treats an accepted upload as completed.  The old KB remains
intact while every active version is uploaded to the target KB and reconciled by
querying the server-held document id.  Duplicate ids are trusted only after the
same query confirms both ``parse_status=completed`` and ownership by the target
KB.  ``migration_state`` is DB-only and must never enter API, audit, or logs.
"""

from __future__ import annotations

import logging
import uuid
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.core.logging import safe_log_exception
from app.db.utils import utc_now
from app.models.identity import ProjectMember, User
from app.models.indexing_job import IndexingOperationJob
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.weknora import WeknoraKbMapping
from app.schemas.enums import AssetStatus, AuditAction, AuditLogType, KnowledgeScope
from app.schemas.permission import CallerContext
from app.services import audit as audit_service
from app.services import error_catalog
from app.services.permission import build_caller_context
from app.services.weknora_client import WeKnoraDuplicateError, WeKnoraError, weknora_enabled
from app.services.weknora_model_selection import _safe_model_meta
from app.services.weknora_models import _kb_update_config, _model_ref

_logger = logging.getLogger(__name__)

_DONE_STATUSES = {"completed", "completed_with_errors", "failed", "no_action"}
_BATCH_LIMIT = 500
_FAILED_PARSE_STATUSES = {"failed", "cancelled", "canceled"}


@dataclass
class _ReconcileCounts:
    total: int = 0
    completed: int = 0
    verified_duplicate: int = 0
    processing: int = 0
    duplicate_pending: int = 0
    failed: int = 0

    @property
    def pending(self) -> int:
        return self.processing + self.duplicate_pending

    @property
    def success(self) -> int:
        return self.completed + self.verified_duplicate

    def safe_dict(self) -> dict[str, int]:
        return {
            "total": self.total,
            "completed": self.completed,
            "verified_duplicate": self.verified_duplicate,
            "processing": self.processing,
            "duplicate_pending": self.duplicate_pending,
            "pending": self.pending,
            "failed": self.failed,
        }


async def _build_actor(session: AsyncSession, job: IndexingOperationJob) -> CallerContext:
    from sqlalchemy.orm import selectinload

    if job.requested_by_user_id is not None:
        user = (
            await session.execute(
                select(User)
                .where(User.id == job.requested_by_user_id)
                .options(
                    selectinload(User.company_roles),
                    selectinload(User.project_members).selectinload(ProjectMember.project),
                )
            )
        ).scalar_one_or_none()
        if user is not None:
            return build_caller_context(user)
    return CallerContext(
        user_id=job.requested_by_user_id or uuid.UUID(int=0),
        is_active=True,
        active_company_roles=set(),
        active_project_ids=set(),
    )


def _scope_conditions(mp: WeknoraKbMapping):
    conds = [
        KnowledgeAsset.scope == mp.scope,
        KnowledgeAsset.asset_status != AssetStatus.deleted.value,
    ]
    if mp.scope == KnowledgeScope.personal.value:
        conds.append(KnowledgeAsset.owner_user_id == mp.owner_user_id)
    elif mp.scope == KnowledgeScope.project.value:
        conds.append(KnowledgeAsset.project_id == mp.project_id)
    else:
        conds.append(KnowledgeAsset.owner_user_id.is_(None))
        conds.append(KnowledgeAsset.project_id.is_(None))
    return conds


async def _resolve_models(weknora, refs: dict, *, trace_id: str | None):
    raw = await weknora.list_models(trace_id=trace_id)
    ref_map = {_model_ref(str(m["id"])): m for m in raw if isinstance(m, dict) and m.get("id")}

    def meta(ref):
        model = ref_map.get(ref)
        return _safe_model_meta(model) if model is not None else None

    embedding = meta(refs.get("embedding_ref"))
    chat = meta(refs.get("chat_ref"))
    multimodal = meta(refs.get("multimodal_ref"))
    if embedding is None or embedding.type != "embedding":
        raise WeKnoraError("weknora_model_not_found", "所选嵌入模型不存在或类型不符")
    if chat is None or chat.type != "chat":
        raise WeKnoraError("weknora_model_not_found", "所选问答模型不存在或类型不符")
    if multimodal is not None and multimodal.type != "vllm":
        raise WeKnoraError("weknora_model_not_found", "所选多模态模型不存在或类型不符")
    return embedding, chat, multimodal


async def _create_new_kb(
    session: AsyncSession,
    weknora,
    mp: WeknoraKbMapping,
    refs: dict,
    *,
    trace_id: str | None,
) -> tuple[str, str]:
    embedding, chat, multimodal = await _resolve_models(weknora, refs, trace_id=trace_id)
    name = (mp.display_name or "").strip() or mp.kb_name
    kb_id = await weknora.create_kb(
        name=name, embedding_model_id=embedding.model_id, trace_id=trace_id
    )
    current_kb = await weknora.get_kb(kb_id, trace_id=trace_id)
    config = _kb_update_config(current_kb)
    config["llmModelId"] = chat.model_id
    config["embeddingModelId"] = embedding.model_id
    if multimodal is not None:
        vlm = dict(config.get("vlm_config") or {})
        vlm.update({"enabled": True, "model_id": multimodal.model_id})
        config["vlm_config"] = vlm
        config["multimodal"] = {"enabled": True}
    await weknora.update_initialization_config(kb_id, config=config, trace_id=trace_id)
    return kb_id, embedding.model_id


async def _active_versions(
    session: AsyncSession, mp: WeknoraKbMapping
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    rows = (
        await session.execute(
            select(KnowledgeAsset.id, KnowledgeAssetVersion.id)
            .join(KnowledgeAssetVersion, KnowledgeAssetVersion.asset_id == KnowledgeAsset.id)
            .where(
                KnowledgeAssetVersion.version_status == "active",
                *_scope_conditions(mp),
            )
            .order_by(KnowledgeAsset.updated_at.desc())
        )
    ).all()
    return [(asset_id, version_id) for asset_id, version_id in rows]


async def _target_kb_documents(
    weknora, kb_id: str, *, trace_id: str | None
) -> dict[str, dict[str, Any]]:
    """Return documents proven to belong to ``kb_id`` by the scoped list endpoint."""
    page = 1
    page_size = 1000
    found: dict[str, dict[str, Any]] = {}
    while True:
        rows, total = await weknora.list_knowledge_in_kb(
            kb_id,
            page=page,
            page_size=page_size,
            trace_id=trace_id,
        )
        for row in rows:
            doc_id = str(row.get("id") or "")
            if doc_id:
                found[doc_id] = row
        if not rows or page * page_size >= total:
            return found
        page += 1


async def _mark_version(
    session: AsyncSession,
    version_id: uuid.UUID,
    *,
    kb_id: str | None,
    doc_id: str | None,
    parse_status: str | None,
    outcome: str,
) -> None:
    version = await session.get(KnowledgeAssetVersion, version_id)
    if version is None:
        return
    if kb_id is not None:
        version.weknora_kb_id = kb_id
    if doc_id is not None:
        version.weknora_doc_id = doc_id
    version.weknora_parse_status = parse_status
    if outcome == "complete":
        version.index_status = "indexed"
        version.indexed_at = utc_now()
        version.index_error_code = None
        version.index_error_message = None
    elif outcome == "pending":
        version.index_status = "indexing"
        version.indexed_at = None
        version.index_error_code = None
        version.index_error_message = None
    else:
        version.index_status = "index_failed"
        version.indexed_at = None
        version.index_error_code = "weknora_call_failed"
        version.index_error_message = error_catalog.user_message("weknora_call_failed")


async def _upload_version(
    session: AsyncSession,
    weknora,
    storage,
    *,
    asset_id: uuid.UUID,
    version_id: uuid.UUID,
    new_kb_id: str,
    trace_id: str | None,
) -> dict[str, str | None]:
    """Upload canonical Markdown to the new KB without deleting the old document."""
    from app.services.canonical_markdown import ensure_version_markdown

    markdown = await ensure_version_markdown(
        session,
        storage,
        asset_id=asset_id,
        version_id=version_id,
    )
    from app.services import chunking
    from app.services.indexing import _governance_upload

    content, upload_name, upload_mime, governance_text = _governance_upload(
        markdown.content, markdown.file_name, markdown.mime
    )
    asset = await session.get(KnowledgeAsset, asset_id)
    confidentiality = asset.confidentiality_level if asset is not None else "L2"
    kind = "uploaded"
    try:
        data = await weknora.upload_file(
            kb_id=new_kb_id,
            content=content,
            file_name=upload_name,
            mime=upload_mime,
            metadata={
                "asset_id": str(asset_id),
                "version_id": str(version_id),
                "scope": asset.scope if asset is not None else "",
                "confidentiality_level": confidentiality,
            },
            channel=markdown.channel,
            trace_id=trace_id,
        )
        doc_id = str(data.get("id") or "") or None
        if doc_id is None:
            raise WeKnoraError("invalid_response", "WeKnora 上传未返回文档标识")
        response_status = str(data.get("parse_status") or "processing").lower()
    except WeKnoraDuplicateError as duplicate:
        kind = "duplicate"
        doc_id = duplicate.existing_knowledge_id
        response_status = "pending"
        if not doc_id:
            raise WeKnoraError("invalid_response", "WeKnora 重复响应缺少文档标识") from duplicate

    await _mark_version(
        session,
        version_id,
        kb_id=new_kb_id if kind == "uploaded" else None,
        doc_id=doc_id if kind == "uploaded" else None,
        parse_status=response_status if kind == "uploaded" else "duplicate_pending",
        outcome="pending",
    )
    await session.commit()
    if governance_text:
        try:
            await chunking.rebuild_version_chunks(
                session,
                asset_id=asset_id,
                version_id=version_id,
                governance_text=governance_text,
            )
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            safe_log_exception(
                _logger,
                "kb_migrate_chunk_rebuild_failed",
                exc,
                include_summary=False,
                level=logging.WARNING,
            )
            await session.rollback()
    return {
        "kind": kind,
        "doc_id": doc_id,
        "status": "pending",
        "parse_status": response_status,
    }


async def _reconcile_item(
    session: AsyncSession,
    *,
    version_id: uuid.UUID,
    item: dict[str, Any],
    new_kb_id: str,
    target_documents: dict[str, dict[str, Any]],
) -> str:
    kind = "duplicate" if item.get("kind") == "duplicate" else "uploaded"
    doc_id = str(item.get("doc_id") or "") or None
    if not doc_id:
        await _mark_version(
            session,
            version_id,
            kb_id=None,
            doc_id=None,
            parse_status="failed",
            outcome="failed",
        )
        item["status"] = "failed"
        return "failed"
    detail = target_documents.get(doc_id)
    if detail is None:
        # A duplicate missing from the target-KB list is unverified (not found or
        # cross-KB).  A newly uploaded document may be briefly list-invisible, so
        # keep it pending and poll it next round instead of re-uploading it.
        if kind == "uploaded":
            parse_status = str(item.get("parse_status") or "processing")
            await _mark_version(
                session,
                version_id,
                kb_id=new_kb_id,
                doc_id=doc_id,
                parse_status=parse_status,
                outcome="pending",
            )
            item["status"] = "processing"
            return "processing"
        await _mark_version(
            session,
            version_id,
            kb_id=None,
            doc_id=None,
            parse_status="failed",
            outcome="failed",
        )
        item["status"] = "failed"
        return "failed"
    parse_status = str(detail.get("parse_status") or "").strip().lower()
    if not parse_status:
        await _mark_version(
            session,
            version_id,
            kb_id=new_kb_id if kind == "uploaded" else None,
            doc_id=doc_id if kind == "uploaded" else None,
            parse_status="failed",
            outcome="failed",
        )
        item["status"] = "failed"
        return "failed"
    if parse_status == "completed":
        await _mark_version(
            session,
            version_id,
            kb_id=new_kb_id,
            doc_id=doc_id,
            parse_status=parse_status,
            outcome="complete",
        )
        item["status"] = "verified_duplicate" if kind == "duplicate" else "completed"
        return str(item["status"])
    if parse_status in _FAILED_PARSE_STATUSES:
        await _mark_version(
            session,
            version_id,
            kb_id=new_kb_id if kind == "uploaded" else None,
            doc_id=doc_id if kind == "uploaded" else None,
            parse_status=parse_status,
            outcome="failed",
        )
        item["status"] = "failed"
        return "failed"

    await _mark_version(
        session,
        version_id,
        kb_id=new_kb_id if kind == "uploaded" else None,
        doc_id=doc_id if kind == "uploaded" else None,
        parse_status=parse_status,
        outcome="pending",
    )
    item["status"] = "duplicate_pending" if kind == "duplicate" else "processing"
    return str(item["status"])


def _count_truth(
    active: list[tuple[uuid.UUID, uuid.UUID]], items: dict[str, Any]
) -> _ReconcileCounts:
    counts = _ReconcileCounts(total=len(active))
    for _asset_id, version_id in active:
        item = items.get(str(version_id))
        status = item.get("status") if isinstance(item, dict) else None
        if status == "completed":
            counts.completed += 1
        elif status == "verified_duplicate":
            counts.verified_duplicate += 1
        elif status == "duplicate_pending":
            counts.duplicate_pending += 1
        elif status == "failed":
            counts.failed += 1
        else:
            counts.processing += 1
    return counts


async def run_kb_migrate_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    weknora,
    storage,
    trace_id: str | None = None,
) -> str:
    job = await session.get(IndexingOperationJob, job_id)
    if job is None:
        return "not_found"
    if job.status in _DONE_STATUSES:
        return job.status
    if not weknora_enabled():
        return await _fail_job(session, job, "weknora_not_configured")

    actor = await _build_actor(session, job)
    scope_filter = dict(job.scope_filter or {})
    mapping_id = scope_filter.get("mapping_id")
    if not mapping_id:
        return await _fail_job(session, job, "weknora_kb_migrate_invalid")
    mp = await session.get(WeknoraKbMapping, uuid.UUID(str(mapping_id)))
    if mp is None:
        return await _fail_job(session, job, "weknora_kb_mapping_not_found")
    mapping_key = mp.id

    job.status = "running"
    job.started_at = utc_now()
    await session.commit()

    try:
        state = deepcopy(mp.migration_state) if isinstance(mp.migration_state, dict) else {}
        if mp.status != "migrating" or not state.get("to"):
            new_kb_id, new_embedding_id = await _create_new_kb(
                session, weknora, mp, scope_filter.get("models") or {}, trace_id=trace_id
            )
            state = {
                "from": mp.weknora_kb_id,
                "to": new_kb_id,
                "embedding_model_id": new_embedding_id,
                "started_at": utc_now().isoformat(),
                "items": {},
            }
            mp.weknora_kb_id = new_kb_id
            mp.embedding_model_id = new_embedding_id
            mp.status = "migrating"
            mp.migration_state = state
            await session.commit()
        else:
            new_kb_id = str(state["to"])

        active = await _active_versions(session, mp)
        items = deepcopy(state.get("items") or {})

        # Backfill migrations started by the pre-reconciliation implementation.  Versions
        # already pointing at the target KB have been submitted and must be queried, not
        # uploaded again.  The legacy ``duplicate`` marker preserves the duplicate kind.
        for _asset_id, version_id in active:
            key = str(version_id)
            if isinstance(items.get(key), dict):
                continue
            version = await session.get(KnowledgeAssetVersion, version_id)
            if (
                version is not None
                and version.weknora_kb_id == new_kb_id
                and version.weknora_doc_id
            ):
                items[key] = {
                    "kind": (
                        "duplicate" if version.weknora_parse_status == "duplicate" else "uploaded"
                    ),
                    "doc_id": version.weknora_doc_id,
                    "status": "pending",
                }

        # A resume uploads only never-entered or failed versions, bounded per round.
        candidates = [
            (asset_id, version_id)
            for asset_id, version_id in active
            if not isinstance(items.get(str(version_id)), dict)
            or items[str(version_id)].get("status") == "failed"
        ][:_BATCH_LIMIT]
        for asset_id, version_id in candidates:
            try:
                item = await _upload_version(
                    session,
                    weknora,
                    storage,
                    asset_id=asset_id,
                    version_id=version_id,
                    new_kb_id=new_kb_id,
                    trace_id=trace_id,
                )
            except Exception as exc:  # noqa: BLE001
                safe_log_exception(
                    _logger,
                    "kb_migrate_item_failed",
                    exc,
                    include_summary=False,
                    level=logging.WARNING,
                )
                await session.rollback()
                item = {"kind": "uploaded", "status": "failed"}
                await _mark_version(
                    session,
                    version_id,
                    kb_id=None,
                    doc_id=None,
                    parse_status="failed",
                    outcome="failed",
                )
            items[str(version_id)] = item
            await session.commit()

        # One target-KB-scoped snapshot proves ownership even though real document
        # detail objects omit knowledge_base_id. Reconcile every submitted item.
        target_documents = await _target_kb_documents(weknora, new_kb_id, trace_id=trace_id)
        for _asset_id, version_id in active:
            reconciliation_item = items.get(str(version_id))
            if not isinstance(reconciliation_item, dict):
                continue
            await _reconcile_item(
                session,
                version_id=version_id,
                item=reconciliation_item,
                new_kb_id=new_kb_id,
                target_documents=target_documents,
            )
            items[str(version_id)] = reconciliation_item

        mp = await session.get(WeknoraKbMapping, mapping_key)
        if mp is None:
            raise WeKnoraError("weknora_kb_mapping_not_found", "知识库映射不存在")
        state["items"] = items
        mp.migration_state = state
        flag_modified(mp, "migration_state")
        await session.commit()

        counts = _count_truth(active, items)
        close_ready = counts.pending == 0 and counts.failed == 0 and counts.success == counts.total
        delete_failed = False
        if close_ready:
            old_kb_id = state.get("from")
            try:
                if old_kb_id:
                    await weknora.delete_kb(str(old_kb_id), trace_id=trace_id)
            except WeKnoraError as exc:
                safe_log_exception(
                    _logger,
                    "kb_migrate_delete_old_failed",
                    exc,
                    include_summary=False,
                    level=logging.WARNING,
                )
                delete_failed = True
            else:
                mp.migration_state = None
                mp.status = "active"
                await session.commit()

        job = await session.get(IndexingOperationJob, job_id)
        if job is None:
            return "not_found"
        scope_filter["reconciliation"] = counts.safe_dict()
        job.scope_filter = scope_filter
        job.total_count = counts.total
        job.success_count = counts.success
        job.failed_count = counts.failed
        job.skipped_count = counts.pending
        if delete_failed:
            job.status = "failed"
            job.error_code = "weknora_call_failed"
            job.error_message = error_catalog.user_message(job.error_code)
        else:
            job.status = "completed" if close_ready else "completed_with_errors"
        job.finished_at = utc_now()
        await session.commit()
        from app.services.notifications import notify_operation_job_finished

        try:
            await notify_operation_job_finished(session, job)
            await session.commit()
        except Exception as notification_exc:  # noqa: BLE001
            safe_log_exception(
                _logger, "kb_migrate_notification_failed", notification_exc, include_summary=False
            )
            await session.rollback()

        await audit_service.record_event(
            session,
            caller=actor,
            log_type=AuditLogType.operation,
            action=AuditAction.weknora_kb_migrate_completed.value,
            trace_id=trace_id or "",
            target_type="weknora_kb_mapping",
            target_id=mp.id,
            extra={
                "mapping_id": str(mp.id),
                "job_id": str(job_id),
                "status": job.status,
                **counts.safe_dict(),
            },
            project_id=mp.project_id,
        )
        await session.commit()
        return job.status
    except Exception as exc:  # noqa: BLE001
        safe_log_exception(_logger, "kb_migrate_job_failed", exc, include_summary=False)
        await session.rollback()
        job = await session.get(IndexingOperationJob, job_id)
        if job is None:
            return "failed"
        code = error_catalog.safe_code(getattr(exc, "code", None) or type(exc).__name__)
        return await _fail_job(session, job, code)


async def _fail_job(session: AsyncSession, job: IndexingOperationJob, code: str) -> str:
    job.status = "failed"
    job.error_code = error_catalog.safe_code(code)
    job.error_message = error_catalog.user_message(job.error_code)
    job.finished_at = utc_now()
    await session.commit()
    from app.services.notifications import notify_operation_job_finished

    try:
        await notify_operation_job_finished(session, job)
        await session.commit()
    except Exception as notification_exc:  # noqa: BLE001
        safe_log_exception(
            _logger, "kb_migrate_notification_failed", notification_exc, include_summary=False
        )
        await session.rollback()
    return "failed"
