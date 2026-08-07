"""知识库重建迁移作业（换 embedding 模型，绕开底座"已有文件不可改模型"锁）。

对目标 scope 的 KB：
1. 新建一个绑定新 embedding 模型的 WeKnora 知识库（新库无文件，不受底座锁限制）；
2. `weknora_kb_mappings` 切到新库 id、绑定新模型，状态置 `migrating`（期间该 scope
   新入库 fail-closed 拒绝，见 `resolve_or_create_kb` / `update_kb_init`）；
3. 库内每个 active 资产版本逐个「删旧 doc + 上传新库」（复用 reparse 的重传语义），
   新库解析 / 向量化使用新模型；
4. 全部成功 → 删除旧库、清空迁移状态、恢复 active；部分失败 → 作业
   completed_with_errors、mapping 保持 migrating（幂等续跑，只处理仍指向旧库的版本）；
   删除旧库失败 → 保留迁移状态可重试。

安全红线：`migration_state` 只存在 DB（server-only），**绝不**进 API / 审计 / 日志；
作业 `scope_filter` 只存 KAP mapping_id 与安全 model_ref；审计只含 mapping_id / counts。
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.services.source_content import resolve_version_source_task
from app.services.weknora_client import WeKnoraError, weknora_enabled
from app.services.weknora_model_selection import _safe_model_meta
from app.services.weknora_models import _kb_update_config, _model_ref

_logger = logging.getLogger(__name__)

_DONE_STATUSES = {"completed", "completed_with_errors", "failed", "no_action"}
_BATCH_LIMIT = 500


async def _build_actor(session: AsyncSession, job: IndexingOperationJob) -> CallerContext:
    """以发起人身份构建审计 actor（作业代其完成迁移）。"""
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
    """把请求里的安全 model_ref 解析为 server-only 模型元数据。"""
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
    """建新库（绑定新 embedding）+ 初始化 chat + 写入多模态配置。返回 (新 kb_id, 新 embedding id)。"""
    embedding, chat, multimodal = await _resolve_models(weknora, refs, trace_id=trace_id)
    name = (mp.display_name or "").strip() or mp.kb_name
    kb_id = await weknora.create_kb(
        name=name, embedding_model_id=embedding.model_id, trace_id=trace_id
    )
    await weknora.initialize_kb(
        kb_id,
        trace_id=trace_id,
        embedding_source=embedding.source,
        embedding_model_name=embedding.model_name,
        llm_source=chat.source,
        llm_model_name=chat.model_name,
    )
    if multimodal is not None:
        current_kb = await weknora.get_kb(kb_id, trace_id=trace_id)
        config = _kb_update_config(current_kb)
        if not str(config.get("llmModelId") or "").strip():
            config["llmModelId"] = chat.model_id
        vlm = dict(config.get("vlm_config") or {})
        vlm.update({"enabled": True, "model_id": multimodal.model_id})
        config["vlm_config"] = vlm
        config["multimodal"] = {"enabled": True}
        await weknora.update_initialization_config(kb_id, config=config, trace_id=trace_id)
    return kb_id, embedding.model_id


async def _migrate_version(
    session: AsyncSession,
    weknora,
    storage,
    *,
    asset_id: uuid.UUID,
    version_id: uuid.UUID,
    new_kb_id: str,
    trace_id: str | None,
) -> None:
    """把一个版本「删旧 doc + 上传新库」。失败抛异常由调用方计数。"""
    task = await resolve_version_source_task(session, asset_id=asset_id, version_id=version_id)
    if task is None or not task.source_file_ref:
        raise WeKnoraError("source_file_unreadable", "原文来源暂不可用")
    file_bytes = storage.resolve_path(task.source_file_ref).read_bytes()
    from app.services import chunking
    from app.services.indexing import _governance_upload

    content, upload_name, upload_mime, governance_text = _governance_upload(
        file_bytes, task.source_file_name, task.source_file_mime_type
    )
    version = (
        await session.execute(
            select(KnowledgeAssetVersion).where(KnowledgeAssetVersion.id == version_id)
        )
    ).scalar_one_or_none()
    old_doc_id = version.weknora_doc_id if version is not None else None
    asset = await session.get(KnowledgeAsset, asset_id)
    confidentiality = asset.confidentiality_level if asset is not None else "L2"
    data = await weknora.reparse_knowledge(
        kb_id=new_kb_id,
        knowledge_id=old_doc_id,
        content=content,
        file_name=upload_name,
        mime=upload_mime,
        metadata={
            "asset_id": str(asset_id),
            "version_id": str(version_id),
            "scope": task.target_scope or "",
            "confidentiality_level": confidentiality,
        },
        channel=task.source,
        trace_id=trace_id,
    )
    if version is not None:
        version.weknora_kb_id = new_kb_id
        version.weknora_doc_id = str(data.get("id") or "") or None
        version.weknora_parse_status = str(data.get("parse_status") or "processing")
        version.index_status = "indexed"
        version.indexed_at = utc_now()
        version.index_error_code = None
        version.index_error_message = None
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
                version_id=str(version_id),
            )
            await session.rollback()


async def _select_migration_versions(
    session: AsyncSession, mp: WeknoraKbMapping, new_kb_id: str
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    rows = (
        await session.execute(
            select(KnowledgeAsset.id, KnowledgeAssetVersion.id)
            .join(KnowledgeAssetVersion, KnowledgeAssetVersion.asset_id == KnowledgeAsset.id)
            .where(
                KnowledgeAssetVersion.version_status == "active",
                *_scope_conditions(mp),
                or_(
                    KnowledgeAssetVersion.weknora_kb_id.is_(None),
                    KnowledgeAssetVersion.weknora_kb_id != new_kb_id,
                ),
            )
            .order_by(KnowledgeAsset.updated_at.desc())
            .limit(_BATCH_LIMIT)
        )
    ).all()
    return [(aid, vid) for aid, vid in rows]


async def run_kb_migrate_job(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    weknora,
    storage,
    trace_id: str | None = None,
) -> str:
    """执行一个知识库迁移作业（幂等、可续跑）。返回最终 status。"""
    job = (
        await session.execute(select(IndexingOperationJob).where(IndexingOperationJob.id == job_id))
    ).scalar_one_or_none()
    if job is None:
        return "not_found"
    if job.status in _DONE_STATUSES:
        return job.status
    if not weknora_enabled():
        await _fail_job(session, job, "weknora_not_configured")
        return "failed"

    actor = await _build_actor(session, job)
    sf = job.scope_filter or {}
    mapping_id = sf.get("mapping_id")
    if not mapping_id:
        await _fail_job(session, job, "weknora_kb_migrate_invalid")
        return "failed"
    mp = await session.get(WeknoraKbMapping, uuid.UUID(str(mapping_id)))
    if mp is None:
        await _fail_job(session, job, "weknora_kb_mapping_not_found")
        return "failed"
    mapping_key = mp.id  # 标量快照：逐条失败 rollback 后 ORM 对象会过期

    job.status = "running"
    job.started_at = utc_now()
    await session.commit()

    try:
        state = mp.migration_state if isinstance(mp.migration_state, dict) else None
        if mp.status != "migrating" or not state or not state.get("to"):
            # 阶段一：建新库 + 切 mapping。
            new_kb_id, new_embedding_id = await _create_new_kb(
                session, weknora, mp, sf.get("models") or {}, trace_id=trace_id
            )
            mp.migration_state = {
                "from": mp.weknora_kb_id,
                "to": new_kb_id,
                "embedding_model_id": new_embedding_id,
                "started_at": utc_now().isoformat(),
            }
            mp.weknora_kb_id = new_kb_id
            mp.embedding_model_id = new_embedding_id
            mp.status = "migrating"
            await session.commit()
        else:
            new_kb_id = str(state["to"])

        targets = await _select_migration_versions(session, mp, new_kb_id)
        total = len(targets)
        success = failed = 0
        for asset_id, version_id in targets:
            try:
                await _migrate_version(
                    session,
                    weknora,
                    storage,
                    asset_id=asset_id,
                    version_id=version_id,
                    new_kb_id=new_kb_id,
                    trace_id=trace_id,
                )
                success += 1
            except Exception as exc:  # noqa: BLE001  # 单条失败不中断迁移
                safe_log_exception(
                    _logger,
                    "kb_migrate_item_failed",
                    exc,
                    include_summary=False,
                    level=logging.WARNING,
                    version_id=str(version_id),
                )
                await session.rollback()
                failed += 1

        # 逐条失败会 rollback 过期所有 ORM 对象，收尾前重新载入。
        mp = await session.get(WeknoraKbMapping, mapping_key)
        if mp is None:
            raise WeKnoraError("weknora_kb_mapping_not_found", "知识库映射不存在")
        state = mp.migration_state if isinstance(mp.migration_state, dict) else {}

        # 阶段三：收尾——全部成功才删旧库并恢复 active。
        if failed == 0:
            try:
                await weknora.delete_kb(str(state.get("from")), trace_id=trace_id)
            except WeKnoraError as exc:
                safe_log_exception(
                    _logger,
                    "kb_migrate_delete_old_failed",
                    exc,
                    include_summary=False,
                    level=logging.WARNING,
                )
                failed += 1
            else:
                mp.migration_state = None
                mp.status = "active"
                await session.commit()

        job = (
            await session.execute(
                select(IndexingOperationJob).where(IndexingOperationJob.id == job_id)
            )
        ).scalar_one()
        job.total_count = total
        job.success_count = success
        job.failed_count = failed
        job.skipped_count = 0
        job.status = "completed" if failed == 0 else "completed_with_errors"
        job.finished_at = utc_now()
        await session.commit()
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
                "total_count": total,
                "success_count": success,
                "failed_count": failed,
            },
            project_id=mp.project_id,
        )
        await session.commit()
        return job.status
    except Exception as exc:  # noqa: BLE001  # 作业级异常 → failed
        safe_log_exception(_logger, "kb_migrate_job_failed", exc, include_summary=False)
        await session.rollback()
        code = error_catalog.safe_code(getattr(exc, "code", None) or type(exc).__name__)
        return await _fail_job(session, job, code)


async def _fail_job(session: AsyncSession, job: IndexingOperationJob, code: str) -> str:
    job.status = "failed"
    job.error_code = error_catalog.safe_code(code)
    job.error_message = error_catalog.user_message(job.error_code)
    job.finished_at = utc_now()
    await session.commit()
    return "failed"
