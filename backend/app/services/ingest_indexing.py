"""Post-confirmation indexing boundary for ingest.

This module owns the irreversible hand-off from a persisted asset version to the
search foundation. It never decides the destination and never rolls back an
already committed human confirmation.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingest import IngestTask
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.schemas.enums import (
    AlertSeverity,
    AuditAction,
    AuditLogType,
    AuditRiskLevel,
)
from app.schemas.permission import CallerContext
from app.services import audit as audit_service
from app.services import error_catalog, indexing
from app.services.storage import LocalFileStorage
from app.services.weknora_client import NullWeKnoraClient, WeKnoraClient


async def index_confirmed_asset(
    session: AsyncSession,
    caller: CallerContext,
    task: IngestTask,
    asset: KnowledgeAsset,
    version: KnowledgeAssetVersion,
    *,
    scope: str,
    owner_id: uuid.UUID,
    project_id: uuid.UUID | None,
    confidentiality: str,
    weknora: WeKnoraClient | NullWeKnoraClient,
    storage: LocalFileStorage,
    trace_id: str,
    embedding_model_ref: str | None = None,
    rerank_model_ref: str | None = None,
) -> tuple[str, str | None]:
    """Index one already-persisted version and return only safe terminal states."""
    asset_id = asset.id
    version_id = version.id
    try:
        from app.services.canonical_markdown import ensure_version_markdown

        markdown = await ensure_version_markdown(
            session,
            storage,
            asset_id=asset_id,
            version_id=version_id,
        )
    except Exception as exc:  # canonical service exposes only safe codes
        outcome = await indexing.mark_index_failed(
            session,
            version_id=version_id,
            error_code=getattr(exc, "code", "canonical_markdown_unavailable"),
        )
        await _record_index_failure(
            session, caller, asset_id, outcome.error_code, trace_id, project_id
        )
        return outcome.index_status, outcome.parse_status

    outcome = await indexing.index_asset_version(
        session,
        weknora,
        asset_id=asset_id,
        version_id=version_id,
        scope=scope,
        owner_user_id=owner_id,
        project_id=project_id,
        confidentiality=confidentiality,
        file_bytes=markdown.content,
        source_file_name=markdown.file_name,
        source_file_mime=markdown.mime,
        channel=task.source,
        trace_id=trace_id,
        embedding_model_ref=embedding_model_ref,
        rerank_model_ref=rerank_model_ref,
    )
    if outcome.index_status in {"indexed", "indexing"}:
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.ingest_weknora_indexed.value,
            trace_id=trace_id,
            target_type="knowledge_asset",
            target_id=asset_id,
            extra={
                "parse_status": outcome.parse_status,
                "is_duplicate": outcome.is_duplicate,
                "scope": scope,
            },
            project_id=project_id,
        )
        await session.commit()
    else:
        await _record_index_failure(
            session, caller, asset_id, outcome.error_code, trace_id, project_id
        )
    return outcome.index_status, outcome.parse_status


async def _record_index_failure(
    session: AsyncSession,
    caller: CallerContext,
    asset_id: uuid.UUID,
    error_code: str | None,
    trace_id: str,
    project_id: uuid.UUID | None,
) -> None:
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.exception,
        action=AuditAction.ingest_index_failed.value,
        trace_id=trace_id,
        target_type="knowledge_asset",
        target_id=asset_id,
        severity=AlertSeverity.warning,
        risk_level=AuditRiskLevel.high.value,
        extra={"failure_stage": "weknora_index", "error_code": error_catalog.safe_code(error_code)},
        project_id=project_id,
    )
    await session.commit()
