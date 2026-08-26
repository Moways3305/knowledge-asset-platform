"""Server-authoritative duplicate detection and safe comparison projection."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal, cast

from fastapi import HTTPException
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Project
from app.models.ingest import IngestTask, UploadSessionItem
from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetFileObject,
    KnowledgeAssetSummary,
    KnowledgeAssetVersion,
)
from app.schemas.enums import AuditAction, AuditLogType, IngestStatus, KnowledgeScope, SummaryType
from app.schemas.permission import AccessLayer, CallerContext
from app.schemas.upload_duplicates import (
    DuplicateComparisonCandidate,
    DuplicateDecisionResponse,
    MyUploadItem,
    UploadDuplicateReadModel,
)
from app.services import audit as audit_service
from app.services.permission import decide

_HASH_TASK_STATES = {
    IngestStatus.processing.value,
    IngestStatus.pending_confirmation.value,
    IngestStatus.waiting_review.value,
}
_NAMESPACE = uuid.UUID("d625311b-23d1-47c5-883c-b597272528ad")


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"denied_reason": reason, "message": message},
    )


def _task_scope(
    stmt: Select, caller: CallerContext, scope: str, project_id: uuid.UUID | None
) -> Select:
    stmt = stmt.where(IngestTask.target_scope == scope)
    if scope == KnowledgeScope.personal.value:
        return stmt.where(IngestTask.created_by == caller.user_id)
    if scope == KnowledgeScope.project.value:
        return stmt.where(IngestTask.target_project_id == project_id)
    return stmt.where(IngestTask.target_project_id.is_(None))


def _asset_scope(
    stmt: Select, caller: CallerContext, scope: str, project_id: uuid.UUID | None
) -> Select:
    stmt = stmt.where(KnowledgeAsset.scope == scope)
    if scope == KnowledgeScope.personal.value:
        return stmt.where(KnowledgeAsset.owner_user_id == caller.user_id)
    if scope == KnowledgeScope.project.value:
        return stmt.where(KnowledgeAsset.project_id == project_id)
    return stmt.where(KnowledgeAsset.project_id.is_(None))


def _scope_label(scope: str) -> str:
    return {
        KnowledgeScope.personal.value: "我的个人库",
        KnowledgeScope.project.value: "当前项目库",
        KnowledgeScope.company.value: "公司知识库",
    }.get(scope, "当前目标库")


def _metadata_value(metadata: dict | None, key: str) -> str | None:
    value = (metadata or {}).get(key)
    return str(value) if value not in {None, ""} else None


async def _asset_candidate(
    session: AsyncSession,
    caller: CallerContext,
    asset: KnowledgeAsset,
    version: KnowledgeAssetVersion,
    *,
    match_type: str,
) -> DuplicateComparisonCandidate:
    discovery = decide(caller, asset, AccessLayer.discovery)
    if not discovery.allowed:
        return DuplicateComparisonCandidate(match_type="restricted_match")

    summary_decision = decide(caller, asset, AccessLayer.summary)
    original_decision = decide(caller, asset, AccessLayer.original)
    file_object = await session.scalar(
        select(KnowledgeAssetFileObject).where(
            KnowledgeAssetFileObject.version_id == version.id,
            KnowledgeAssetFileObject.file_variant == "original",
        )
    )
    safe_summary: str | None = None
    if summary_decision.allowed:
        summaries = (
            (
                await session.execute(
                    select(KnowledgeAssetSummary).where(
                        KnowledgeAssetSummary.version_id == version.id
                    )
                )
            )
            .scalars()
            .all()
        )
        preferred_types = (
            [SummaryType.redacted_summary.value, SummaryType.safe_summary.value]
            if summary_decision.summary_variant
            else [
                SummaryType.one_liner.value,
                SummaryType.safe_summary.value,
                SummaryType.redacted_summary.value,
            ]
        )
        by_type = {item.summary_type: item.content for item in summaries if item.content}
        safe_summary = next((by_type[kind] for kind in preferred_types if by_type.get(kind)), None)

    metadata = version.naming_metadata or {}
    return DuplicateComparisonCandidate(
        match_type=match_type,  # type: ignore[arg-type]
        title=asset.title,
        file_name=file_object.file_name if file_object is not None else None,
        file_size=file_object.file_size if file_object is not None else None,
        scope=asset.scope,  # type: ignore[arg-type]
        scope_label=_scope_label(asset.scope),
        directory_key=version.directory_key,
        subject=_metadata_value(metadata, "subject"),
        formed_on=_metadata_value(metadata, "formed_on"),
        version=_metadata_value(metadata, "version") or version.version_no,
        asset_status=asset.asset_status,
        ingested_at=version.activated_at or version.created_at,
        safe_summary=safe_summary,
        asset_id=asset.id,
        can_view_detail=True,
        can_view_original=original_decision.allowed,
    )


async def _exact_assets(
    session: AsyncSession,
    caller: CallerContext,
    task: IngestTask,
    scope: str,
    project_id: uuid.UUID | None,
) -> list[tuple[KnowledgeAsset, KnowledgeAssetVersion]]:
    if not task.source_file_hash:
        return []
    stmt = (
        select(KnowledgeAsset, KnowledgeAssetVersion)
        .join(KnowledgeAssetVersion, KnowledgeAssetVersion.asset_id == KnowledgeAsset.id)
        .where(
            KnowledgeAsset.asset_status == "active",
            KnowledgeAssetVersion.version_status == "active",
            KnowledgeAssetVersion.file_hash == task.source_file_hash,
        )
        .order_by(KnowledgeAsset.updated_at.desc(), KnowledgeAsset.id.asc())
    )
    return list(
        (await session.execute(_asset_scope(stmt, caller, scope, project_id))).tuples().all()
    )


async def _exact_tasks(
    session: AsyncSession,
    caller: CallerContext,
    task: IngestTask,
    scope: str,
    project_id: uuid.UUID | None,
) -> list[IngestTask]:
    if not task.source_file_hash:
        return []
    stmt = (
        select(IngestTask)
        .where(
            IngestTask.id != task.id,
            IngestTask.source_file_hash == task.source_file_hash,
            IngestTask.source_file_ref != "",
            IngestTask.result_asset_id.is_(None),
            IngestTask.status.in_(_HASH_TASK_STATES),
        )
        .order_by(IngestTask.updated_at.desc(), IngestTask.id.asc())
    )
    return list((await session.execute(_task_scope(stmt, caller, scope, project_id))).scalars())


async def _same_batch(
    session: AsyncSession, task: IngestTask
) -> tuple[uuid.UUID | None, int | None, int | None, int]:
    if not task.source_file_hash:
        return None, None, None, 0
    current = await session.scalar(
        select(UploadSessionItem).where(UploadSessionItem.ingest_task_id == task.id)
    )
    if current is None:
        return None, None, None, 0
    rows = (
        await session.execute(
            select(
                UploadSessionItem.ordinal,
                IngestTask.id,
                IngestTask.duplicate_decision,
                IngestTask.status,
            )
            .join(IngestTask, IngestTask.id == UploadSessionItem.ingest_task_id)
            .where(
                UploadSessionItem.session_id == current.session_id,
                UploadSessionItem.status != "cancelled",
                IngestTask.source_file_hash == task.source_file_hash,
                IngestTask.source_file_ref != "",
                IngestTask.status != IngestStatus.failed.value,
            )
            .order_by(UploadSessionItem.ordinal.asc(), IngestTask.id.asc())
        )
    ).all()
    if len(rows) < 2:
        return None, None, None, 0
    keeper = next(
        (
            row
            for row in rows
            if row[2] == "batch_keep" and row[3] != IngestStatus.duplicate_skipped.value
        ),
        None,
    )
    if keeper is None:
        keeper = next(
            (row for row in rows if row[3] != IngestStatus.duplicate_skipped.value), rows[0]
        )
    first_ordinal = keeper[0]
    comparison_ordinal = (
        keeper[0]
        if keeper[1] != task.id
        else next((row[0] for row in rows if row[1] != task.id), None)
    )
    group_id = uuid.uuid5(_NAMESPACE, f"{current.session_id}:{task.source_file_hash}")
    return group_id, first_ordinal, comparison_ordinal, len(rows)


async def _suspected_asset(
    session: AsyncSession,
    caller: CallerContext,
    scope: str,
    project_id: uuid.UUID | None,
    metadata: dict | None,
) -> tuple[KnowledgeAsset, KnowledgeAssetVersion] | None:
    keys = ("category_id", "subject", "formed_on", "version")
    if not metadata or any(not metadata.get(key) for key in keys):
        return None
    stmt = (
        select(KnowledgeAsset, KnowledgeAssetVersion)
        .join(KnowledgeAssetVersion, KnowledgeAssetVersion.asset_id == KnowledgeAsset.id)
        .where(
            KnowledgeAsset.asset_status == "active",
            KnowledgeAssetVersion.version_status == "active",
            KnowledgeAssetVersion.naming_metadata.is_not(None),
        )
        .order_by(KnowledgeAsset.updated_at.desc(), KnowledgeAsset.id.asc())
        .limit(500)
    )
    rows = (await session.execute(_asset_scope(stmt, caller, scope, project_id))).all()
    return next(
        (
            (asset, version)
            for asset, version in rows
            if all((version.naming_metadata or {}).get(key) == metadata.get(key) for key in keys)
        ),
        None,
    )


async def read_duplicate(
    session: AsyncSession,
    caller: CallerContext,
    task: IngestTask,
    *,
    scope: str,
    project_id: uuid.UUID | None,
    metadata: dict | None = None,
) -> UploadDuplicateReadModel:
    """Recompute one task's duplicate state for the explicit destination."""
    if scope == KnowledgeScope.project.value and (
        project_id is None or project_id not in caller.active_project_ids
    ):
        # A caller-controlled preview destination must never become a project
        # discovery oracle. The confirmation command returns the explicit
        # membership error; this read model remains neutral.
        return UploadDuplicateReadModel()
    assets = await _exact_assets(session, caller, task, scope, project_id)
    tasks = await _exact_tasks(session, caller, task, scope, project_id)
    group_id, first_ordinal, comparison_ordinal, group_count = await _same_batch(session, task)
    decision = (
        task.duplicate_decision
        if task.duplicate_decision in {"skip", "independent", "batch_keep"}
        else None
    )

    if assets:
        candidate = await _asset_candidate(
            session, caller, assets[0][0], assets[0][1], match_type="exact_content"
        )
        restricted = candidate.match_type == "restricted_match"
        return UploadDuplicateReadModel(
            duplicate_state="exact_content",
            match_type=candidate.match_type,
            match_count=None if restricted else len(assets) + len(tasks),
            preferred_candidate=candidate,
            same_batch_group_id=group_id,
            same_batch_first_ordinal=first_ordinal,
            default_selected=decision == "independent",
            decision=decision,  # type: ignore[arg-type]
        )
    if group_id is not None:
        return UploadDuplicateReadModel(
            duplicate_state="same_batch",
            match_type="same_batch",
            match_count=group_count,
            preferred_candidate=DuplicateComparisonCandidate(
                match_type="same_batch",
                same_batch_ordinal=comparison_ordinal,
                scope=(
                    cast(Literal["personal", "project", "company"], scope)
                    if scope in {"personal", "project", "company"}
                    else None
                ),
                scope_label=_scope_label(scope),
            ),
            same_batch_group_id=group_id,
            same_batch_first_ordinal=first_ordinal,
            default_selected=(
                decision == "independent"
                or (
                    decision in {None, "batch_keep"}
                    and first_ordinal is not None
                    and await _task_ordinal(session, task.id) == first_ordinal
                )
            ),
            decision=decision,  # type: ignore[arg-type]
        )
    if tasks:
        other = tasks[0]
        if other.created_by != caller.user_id:
            candidate = DuplicateComparisonCandidate(match_type="restricted_match")
            count: int | None = None
        else:
            candidate = DuplicateComparisonCandidate(
                match_type="exact_content",
                title=other.source_file_name,
                file_name=other.source_file_name,
                file_size=other.source_file_size,
                scope=scope,  # type: ignore[arg-type]
                scope_label=_scope_label(scope),
                asset_status="待确认",
                ingested_at=other.created_at,
            )
            count = len(tasks)
        return UploadDuplicateReadModel(
            duplicate_state="exact_content",
            match_type=candidate.match_type,
            match_count=count,
            preferred_candidate=candidate,
            same_batch_group_id=group_id,
            same_batch_first_ordinal=first_ordinal,
            default_selected=decision == "independent",
            decision=decision,  # type: ignore[arg-type]
        )
    suspected = await _suspected_asset(session, caller, scope, project_id, metadata)
    if suspected is not None:
        candidate = await _asset_candidate(
            session, caller, suspected[0], suspected[1], match_type="suspected_metadata"
        )
        restricted = candidate.match_type == "restricted_match"
        return UploadDuplicateReadModel(
            duplicate_state="suspected_metadata",
            match_type=candidate.match_type,
            match_count=None if restricted else 1,
            preferred_candidate=candidate,
            default_selected=decision != "skip",
            decision=decision,  # type: ignore[arg-type]
        )
    return UploadDuplicateReadModel(decision=decision)  # type: ignore[arg-type]


async def require_independent_confirmation(
    session: AsyncSession,
    caller: CallerContext,
    task: IngestTask,
    *,
    scope: str,
    project_id: uuid.UUID | None,
    metadata: dict | None,
    acknowledged_warning_codes: set[str],
) -> UploadDuplicateReadModel:
    """Revalidate duplicates immediately before routing or asset creation."""
    duplicate = await read_duplicate(
        session,
        caller,
        task,
        scope=scope,
        project_id=project_id,
        metadata=metadata,
    )
    _ = acknowledged_warning_codes  # Legacy warning acknowledgement is not a duplicate decision.
    explicitly_independent = task.duplicate_decision == "independent"
    default_same_batch_leader = (
        duplicate.duplicate_state == "same_batch" and duplicate.default_selected
    )
    if duplicate.duplicate_state in {"exact_content", "same_batch"} and not (
        explicitly_independent or default_same_batch_leader
    ):
        raise _denied(
            409,
            "duplicate_decision_required",
            "内容完全相同，请先选择本次不入库或仍作为独立资料入库",
        )
    return duplicate


async def _task_ordinal(session: AsyncSession, task_id: uuid.UUID) -> int | None:
    return await session.scalar(
        select(UploadSessionItem.ordinal).where(UploadSessionItem.ingest_task_id == task_id)
    )


async def _keep_same_batch_item(
    session: AsyncSession,
    caller: CallerContext,
    task: IngestTask,
    *,
    scope: str,
    project_id: uuid.UUID | None,
    reason: str | None,
    trace_id: str,
) -> DuplicateDecisionResponse:
    current_item = await session.scalar(
        select(UploadSessionItem)
        .where(UploadSessionItem.ingest_task_id == task.id)
        .with_for_update()
    )
    if current_item is None or not task.source_file_hash:
        raise _denied(409, "same_batch_match_changed", "同批重复组已变化，请刷新后重试")
    rows = (
        await session.execute(
            select(UploadSessionItem, IngestTask)
            .join(IngestTask, IngestTask.id == UploadSessionItem.ingest_task_id)
            .where(
                UploadSessionItem.session_id == current_item.session_id,
                UploadSessionItem.status != "cancelled",
                IngestTask.source_file_hash == task.source_file_hash,
                IngestTask.source_file_ref != "",
                IngestTask.status != IngestStatus.failed.value,
                IngestTask.created_by == caller.user_id,
            )
            .order_by(UploadSessionItem.ordinal.asc(), IngestTask.id.asc())
            .with_for_update()
        )
    ).all()
    if len(rows) < 2 or all(group_task.id != task.id for _, group_task in rows):
        raise _denied(409, "same_batch_match_changed", "同批重复组已变化，请刷新后重试")
    if any(
        group_task.result_asset_id is not None or group_task.status == IngestStatus.completed.value
        for _, group_task in rows
    ):
        raise _denied(409, "same_batch_already_confirmed", "同批重复组已有资料入库，不能切换")
    switchable_statuses = {
        IngestStatus.pending_confirmation.value,
        IngestStatus.duplicate_skipped.value,
    }
    if any(group_task.status not in switchable_statuses for _, group_task in rows):
        raise _denied(409, "same_batch_state_conflict", "同批重复组状态已推进，请刷新后重试")

    already_selected = task.duplicate_decision == "batch_keep" and all(
        group_task.id == task.id
        or (
            group_task.status == IngestStatus.duplicate_skipped.value
            and group_task.duplicate_decision == "skip"
        )
        for _, group_task in rows
    )
    if already_selected:
        duplicate = await read_duplicate(session, caller, task, scope=scope, project_id=project_id)
        return DuplicateDecisionResponse(
            task_id=task.id,
            status=task.status,
            decision="batch_keep",
            skipped_task_ids=[group_task.id for _, group_task in rows if group_task.id != task.id],
            duplicate=duplicate,
        )

    decided_at = datetime.now(timezone.utc)
    skipped_task_ids: list[uuid.UUID] = []
    for item, group_task in rows:
        if group_task.id == task.id:
            group_task.status = IngestStatus.pending_confirmation.value
            group_task.processing_stage = "awaiting_confirmation"
            group_task.duplicate_decision = "batch_keep"
            group_task.duplicate_decision_reason = (reason or "").strip() or None
            group_task.duplicate_decided_at = decided_at
            item.status = "awaiting_confirmation"
            await audit_service.record_event(
                session,
                caller=caller,
                log_type=AuditLogType.operation,
                action=AuditAction.ingest_duplicate_batch_kept.value,
                trace_id=trace_id,
                target_type="ingest_task",
                target_id=group_task.id,
                after={"status": group_task.status, "duplicate_decision": "batch_keep"},
                project_id=project_id,
            )
            continue
        skipped_task_ids.append(group_task.id)
        if not (
            group_task.status == IngestStatus.duplicate_skipped.value
            and group_task.duplicate_decision == "skip"
        ):
            group_task.status = IngestStatus.duplicate_skipped.value
            group_task.processing_stage = "duplicate_skipped"
            group_task.duplicate_decision = "skip"
            group_task.duplicate_decided_at = decided_at
            item.status = "duplicate_skipped"
            await audit_service.record_event(
                session,
                caller=caller,
                log_type=AuditLogType.operation,
                action=AuditAction.ingest_duplicate_skipped.value,
                trace_id=trace_id,
                target_type="ingest_task",
                target_id=group_task.id,
                after={"status": group_task.status, "duplicate_decision": "skip"},
                project_id=project_id,
            )
        else:
            item.status = "duplicate_skipped"
    await session.flush()
    duplicate = await read_duplicate(session, caller, task, scope=scope, project_id=project_id)
    await session.commit()
    return DuplicateDecisionResponse(
        task_id=task.id,
        status=task.status,
        decision="batch_keep",
        skipped_task_ids=skipped_task_ids,
        duplicate=duplicate,
    )


async def decide_duplicate(
    session: AsyncSession,
    caller: CallerContext,
    task_id: uuid.UUID,
    *,
    action: str,
    reason: str | None,
    scope: str,
    project_id: uuid.UUID | None,
    trace_id: str,
) -> DuplicateDecisionResponse:
    task = await session.scalar(
        select(IngestTask).where(IngestTask.id == task_id).with_for_update()
    )
    if task is None or task.created_by != caller.user_id:
        raise _denied(404, "ingest_task_not_found", "入库任务不存在")
    if not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可处理上传重复项")
    if task.target_scope is not None and task.target_scope != scope:
        raise _denied(409, "ingest_target_locked", "入库目标已由来源规则锁定")
    if scope == KnowledgeScope.project.value:
        if project_id is None or project_id not in caller.active_project_ids:
            raise _denied(403, "project_membership_required", "需为目标项目的有效成员")
        if task.target_project_id is not None and task.target_project_id != project_id:
            raise _denied(409, "ingest_target_project_locked", "目标项目已由来源规则锁定")
    elif scope == KnowledgeScope.company.value and not caller.can_discover_l5:
        raise _denied(403, "company_confirmation_requires_governance", "公司知识需治理角色确认")
    if task.result_asset_id is not None or task.status == IngestStatus.completed.value:
        raise _denied(409, "ingest_already_confirmed", "该资料已入库，不能更改重复处理决定")
    if task.status == IngestStatus.duplicate_skipped.value and action != "keep":
        if task.duplicate_decision == action == "skip":
            return DuplicateDecisionResponse(
                task_id=task.id,
                status=task.status,
                decision="skip",
                duplicate=await read_duplicate(
                    session, caller, task, scope=scope, project_id=project_id
                ),
            )
        raise _denied(409, "duplicate_decision_conflict", "该资料已选择本次不入库")
    if action not in {"skip", "independent", "keep"}:
        raise _denied(422, "duplicate_decision_invalid", "重复处理决定无效")
    duplicate = await read_duplicate(
        session,
        caller,
        task,
        scope=scope,
        project_id=project_id,
    )
    if duplicate.duplicate_state == "none":
        raise _denied(409, "duplicate_match_changed", "重复状态已变化，请刷新后重新核对")
    if action == "keep":
        if duplicate.duplicate_state != "same_batch":
            raise _denied(409, "same_batch_match_required", "仅同批重复项可以设为本批保留项")
        return await _keep_same_batch_item(
            session,
            caller,
            task,
            scope=scope,
            project_id=project_id,
            reason=reason,
            trace_id=trace_id,
        )
    if task.duplicate_decision == action:
        return DuplicateDecisionResponse(
            task_id=task.id,
            status=task.status,
            decision=action,  # type: ignore[arg-type]
        )

    task.duplicate_decision = action
    task.duplicate_decision_reason = (reason or "").strip() or None
    task.duplicate_decided_at = datetime.now(timezone.utc)
    if action == "skip":
        task.status = IngestStatus.duplicate_skipped.value
        task.processing_stage = "duplicate_skipped"
        upload_item = await session.scalar(
            select(UploadSessionItem).where(UploadSessionItem.ingest_task_id == task.id)
        )
        if upload_item is not None:
            upload_item.status = "duplicate_skipped"
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=(
            AuditAction.ingest_duplicate_skipped.value
            if action == "skip"
            else AuditAction.ingest_duplicate_independent.value
        ),
        trace_id=trace_id,
        target_type="ingest_task",
        target_id=task.id,
        after={"status": task.status, "duplicate_decision": action},
        project_id=task.target_project_id,
    )
    await session.commit()
    return DuplicateDecisionResponse(
        task_id=task.id,
        status=task.status,
        decision=action,  # type: ignore[arg-type]
        duplicate=await read_duplicate(session, caller, task, scope=scope, project_id=project_id),
    )


def my_upload_projection(task: IngestTask, *, project_name: str | None = None) -> MyUploadItem:
    if task.status == IngestStatus.duplicate_skipped.value:
        final_status = "duplicate_skipped"
    elif task.status == IngestStatus.completed.value:
        final_status = "completed"
    elif task.status == IngestStatus.failed.value:
        final_status = "failed"
    elif task.status == IngestStatus.waiting_review.value:
        final_status = "waiting_review"
    elif task.status == IngestStatus.pending_confirmation.value:
        final_status = "awaiting_confirmation"
    else:
        final_status = "processing"
    duplicate_result = (
        "skipped"
        if task.duplicate_decision == "skip"
        else "independent"
        if task.duplicate_decision == "independent"
        else "none"
    )
    return MyUploadItem(
        task_id=task.id,
        source_file_name=task.source_file_name,
        source_file_size=task.source_file_size,
        uploaded_at=task.created_at,
        target_scope=task.target_scope,
        target_project_id=task.target_project_id,
        target_project_name=project_name,
        processing_status=task.status,
        final_status=final_status,  # type: ignore[arg-type]
        duplicate_result=duplicate_result,  # type: ignore[arg-type]
        result_asset_id=task.result_asset_id,
    )


async def list_my_uploads(
    session: AsyncSession,
    caller: CallerContext,
    *,
    scope: str | None = None,
    final_status: str | None = None,
    duplicate_result: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[MyUploadItem]:
    if not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可查看自己的上传记录")
    stmt = select(IngestTask).where(IngestTask.created_by == caller.user_id)
    if scope is not None:
        stmt = stmt.where(IngestTask.target_scope == scope)
    if since is not None:
        stmt = stmt.where(IngestTask.created_at >= since)
    if until is not None:
        stmt = stmt.where(IngestTask.created_at <= until)
    tasks = list(
        (await session.execute(stmt.order_by(IngestTask.created_at.desc()).limit(500))).scalars()
    )
    permitted_project_ids = {
        task.target_project_id
        for task in tasks
        if task.target_project_id is not None
        and task.target_project_id in caller.active_project_ids
    }
    project_names = (
        dict(
            (
                await session.execute(
                    select(Project.id, Project.name).where(Project.id.in_(permitted_project_ids))
                )
            ).all()
        )
        if permitted_project_ids
        else {}
    )
    items = [
        my_upload_projection(task, project_name=project_names.get(task.target_project_id))
        for task in tasks
    ]
    if final_status is not None:
        items = [item for item in items if item.final_status == final_status]
    if duplicate_result is not None:
        items = [item for item in items if item.duplicate_result == duplicate_result]
    return items
