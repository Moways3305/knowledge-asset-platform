"""Historical directory governance; mutates directory metadata and nothing else."""

from __future__ import annotations

import re
import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.directory_migration import DirectoryMigrationCandidate
from app.models.identity import Project
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.schemas.directory_migration import (
    DirectoryMigrationCandidateOut,
    DirectoryMigrationConfirmRequest,
    DirectoryMigrationConfirmResponse,
    DirectoryMigrationConfirmResult,
    DirectoryMigrationOverview,
    DirectoryMigrationWorkspaceOut,
)
from app.schemas.enums import AuditAction, AuditLogType
from app.schemas.permission import CallerContext
from app.services import audit as audit_service
from app.services.directories import legacy_directory_key, published_directories, validate_directory


def _denied(status: int, reason: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"denied_reason": reason, "message": message})


def _require_governance(caller: CallerContext) -> None:
    if not caller.can_discover_l5:
        raise _denied(403, "directory_governance_required", "仅业务治理角色可管理历史目录迁移")


def _clean_name(value: object) -> str:
    return re.sub(r"^\s*\d+\s*", "", str(value or "")).strip().casefold()


def _candidate_for(asset: KnowledgeAsset, version: KnowledgeAssetVersion, rows: list[dict]):
    enabled = [row for row in rows if row.get("enabled", True) and row.get("scope") == asset.scope]
    by_key = {str(row.get("directory_key")): row for row in enabled}
    metadata = version.naming_metadata if isinstance(version.naming_metadata, dict) else {}
    old_category = (
        " / ".join(
            str(metadata.get(key)).strip()
            for key in ("category_primary", "category_secondary")
            if metadata.get(key)
        )
        or None
    )
    explicit_key = str(metadata.get("directory_key") or "").strip()
    if explicit_key and explicit_key in by_key:
        return old_category, explicit_key, explicit_key, "legacy_exact_key", "clear", "clear_match"
    primary = _clean_name(metadata.get("category_primary"))
    exact_names = {
        str(row.get("directory_key"))
        for row in enabled
        if primary and primary == _clean_name(row.get("display_name"))
    }
    if len(exact_names) == 1:
        key = next(iter(exact_names))
        return (
            old_category,
            key,
            legacy_directory_key(metadata),
            "legacy_exact_category",
            "clear",
            "clear_match",
        )
    legacy = legacy_directory_key(metadata)
    if legacy in by_key:
        # Keyword mapping is visible as a reference, never treated as a final clear decision.
        return old_category, legacy, legacy, "legacy_keyword_reference", "low", "manual_required"
    return old_category, None, legacy, "none", "none", "no_candidate"


async def refresh_candidates(session: AsyncSession, caller: CallerContext) -> None:
    _require_governance(caller)
    rule_version, directories = await published_directories(session)
    rule_version = rule_version or 1
    records = (
        await session.execute(
            select(KnowledgeAsset, KnowledgeAssetVersion)
            .join(
                KnowledgeAssetVersion, KnowledgeAssetVersion.id == KnowledgeAsset.current_version_id
            )
            .where(
                KnowledgeAsset.asset_status == "active",
                KnowledgeAssetVersion.version_status == "active",
            )
        )
    ).all()
    existing = {
        row.version_id: row
        for row in (await session.execute(select(DirectoryMigrationCandidate))).scalars().all()
    }
    valid = {
        (str(row.get("scope")), str(row.get("directory_key")))
        for row in directories
        if row.get("enabled", True)
    }
    for asset, version in records:
        if version.directory_key and (asset.scope, version.directory_key) in valid:
            row = existing.get(version.id)
            if row:
                row.status = "migrated"
                row.rule_version = version.directory_rule_version or rule_version
                row.failure_code = None
            continue
        old_category, suggested, legacy, source, confidence, status = _candidate_for(
            asset, version, directories
        )
        row = existing.get(version.id)
        if row is None:
            row = DirectoryMigrationCandidate(
                asset_id=asset.id,
                version_id=version.id,
                project_id=asset.project_id,
                scope=asset.scope,
                old_category=old_category,
                suggested_directory_key=suggested,
                legacy_reference_key=legacy,
                candidate_source=source,
                confidence=confidence,
                status=status,
                rule_version=rule_version,
            )
            session.add(row)
        elif row.status != "migrated":
            row.old_category = old_category
            row.suggested_directory_key = suggested
            row.legacy_reference_key = legacy
            row.candidate_source = source
            row.confidence = confidence
            row.status = status
            row.rule_version = rule_version
            row.failure_code = None
    await session.commit()


async def workspace(
    session: AsyncSession,
    caller: CallerContext,
    *,
    scope: str | None = None,
    project_id: uuid.UUID | None = None,
    old_category: str | None = None,
    directory_key: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> DirectoryMigrationWorkspaceOut:
    await refresh_candidates(session, caller)
    rule_version, directories = await published_directories(session)
    rule_version = rule_version or 1
    base = select(DirectoryMigrationCandidate)
    conditions = []
    if scope:
        conditions.append(DirectoryMigrationCandidate.scope == scope)
    if project_id:
        conditions.append(DirectoryMigrationCandidate.project_id == project_id)
    if old_category:
        conditions.append(
            DirectoryMigrationCandidate.old_category.ilike(f"%{old_category.strip()}%")
        )
    if directory_key:
        conditions.append(DirectoryMigrationCandidate.suggested_directory_key == directory_key)
    if status:
        conditions.append(DirectoryMigrationCandidate.status == status)
    if conditions:
        base = base.where(*conditions)
    total = int(await session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    candidates = list(
        (
            await session.execute(
                base.order_by(DirectoryMigrationCandidate.updated_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    all_counts: dict[str, int] = {
        status: int(count)
        for status, count in (
            await session.execute(
                select(DirectoryMigrationCandidate.status, func.count()).group_by(
                    DirectoryMigrationCandidate.status
                )
            )
        ).tuples()
    }
    active_total = int(
        await session.scalar(
            select(func.count())
            .select_from(KnowledgeAssetVersion)
            .where(KnowledgeAssetVersion.version_status == "active")
        )
        or 0
    )
    asset_ids = {row.asset_id for row in candidates}
    project_ids = {row.project_id for row in candidates if row.project_id}
    assets = (
        {
            row.id: row.canonical_name
            for row in (
                await session.execute(
                    select(KnowledgeAsset).where(KnowledgeAsset.id.in_(asset_ids))
                )
            )
            .scalars()
            .all()
        }
        if asset_ids
        else {}
    )
    projects = (
        {
            row.id: row.name
            for row in (await session.execute(select(Project).where(Project.id.in_(project_ids))))
            .scalars()
            .all()
        }
        if project_ids
        else {}
    )
    directory_names = {
        str(row.get("directory_key")): str(row.get("display_name") or "未命名目录")
        for row in directories
    }
    migrated = all_counts.get("migrated", 0) + max(0, active_total - sum(all_counts.values()))
    return DirectoryMigrationWorkspaceOut(
        overview=DirectoryMigrationOverview(
            total=active_total,
            migrated=migrated,
            clear_match=all_counts.get("clear_match", 0),
            manual_required=all_counts.get("manual_required", 0),
            no_candidate=all_counts.get("no_candidate", 0),
            failed=all_counts.get("failed", 0),
            rule_version=rule_version,
        ),
        items=[
            DirectoryMigrationCandidateOut(
                id=row.id,
                asset_title=assets.get(row.asset_id) or "待治理知识",
                scope=row.scope,
                project_id=row.project_id,
                project_name=projects.get(row.project_id) if row.project_id is not None else None,
                old_category=row.old_category,
                suggested_directory_key=row.suggested_directory_key,
                suggested_directory_name=(
                    directory_names.get(row.suggested_directory_key)
                    if row.suggested_directory_key is not None
                    else None
                ),
                candidate_source=row.candidate_source,
                confidence=row.confidence,
                status=row.status,
                failure_code=row.failure_code,
                updated_at=row.updated_at,
            )
            for row in candidates
        ],
        total=total,
        directories=[row for row in directories if row.get("enabled", True)],
    )


async def confirm(
    session: AsyncSession,
    caller: CallerContext,
    body: DirectoryMigrationConfirmRequest,
    trace_id: str,
) -> DirectoryMigrationConfirmResponse:
    _require_governance(caller)
    results: list[DirectoryMigrationConfirmResult] = []
    for item in body.items:
        try:
            candidate = (
                await session.execute(
                    select(DirectoryMigrationCandidate)
                    .where(DirectoryMigrationCandidate.id == item.candidate_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if candidate is None:
                results.append(
                    DirectoryMigrationConfirmResult(
                        candidate_id=item.candidate_id,
                        status="skipped",
                        reason_code="candidate_not_found",
                    )
                )
                continue
            version = (
                await session.execute(
                    select(KnowledgeAssetVersion)
                    .where(KnowledgeAssetVersion.id == candidate.version_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            asset = await session.get(KnowledgeAsset, candidate.asset_id)
            if (
                version is None
                or asset is None
                or version.version_status != "active"
                or asset.current_version_id != version.id
            ):
                candidate.status = "failed"
                candidate.failure_code = "active_version_changed"
                results.append(
                    DirectoryMigrationConfirmResult(
                        candidate_id=item.candidate_id,
                        status="failed",
                        reason_code=candidate.failure_code,
                    )
                )
                await session.commit()
                continue
            key = item.directory_key or candidate.suggested_directory_key
            if not key:
                results.append(
                    DirectoryMigrationConfirmResult(
                        candidate_id=item.candidate_id,
                        status="skipped",
                        reason_code="manual_directory_required",
                    )
                )
                continue
            if item.directory_key is None and candidate.confidence != "clear":
                results.append(
                    DirectoryMigrationConfirmResult(
                        candidate_id=item.candidate_id,
                        status="skipped",
                        reason_code="manual_directory_required",
                    )
                )
                continue
            rule_version, _ = await validate_directory(
                session, directory_key=key, scope=asset.scope, project_id=asset.project_id
            )
            rule_version = rule_version or 1
            if version.directory_key == key and version.directory_rule_version == rule_version:
                candidate.status = "migrated"
                candidate.failure_code = None
                results.append(
                    DirectoryMigrationConfirmResult(
                        candidate_id=item.candidate_id, status="migrated"
                    )
                )
                await session.commit()
                continue
            version.directory_key = key
            version.directory_rule_version = rule_version
            version.directory_confirmed_by = caller.user_id
            candidate.suggested_directory_key = key
            candidate.rule_version = rule_version
            candidate.status = "migrated"
            candidate.failure_code = None
            await audit_service.record_event(
                session,
                caller=caller,
                log_type=AuditLogType.operation,
                action=AuditAction.directory_migration_confirmed.value,
                trace_id=trace_id,
                target_type="knowledge_asset_version",
                target_id=version.id,
                before={"directory_key": None},
                after={"directory_key": key, "directory_rule_version": rule_version},
                project_id=asset.project_id,
            )
            await session.commit()
            results.append(
                DirectoryMigrationConfirmResult(candidate_id=item.candidate_id, status="migrated")
            )
        except HTTPException as exc:
            await session.rollback()
            reason = (
                exc.detail.get("denied_reason")
                if isinstance(exc.detail, dict)
                else "directory_invalid"
            )
            results.append(
                DirectoryMigrationConfirmResult(
                    candidate_id=item.candidate_id, status="failed", reason_code=reason
                )
            )
        except Exception:
            await session.rollback()
            results.append(
                DirectoryMigrationConfirmResult(
                    candidate_id=item.candidate_id, status="failed", reason_code="migration_failed"
                )
            )
    migrated = sum(row.status == "migrated" for row in results)
    skipped = sum(row.status == "skipped" for row in results)
    failed = sum(row.status == "failed" for row in results)
    return DirectoryMigrationConfirmResponse(
        submitted=len(results), migrated=migrated, skipped=skipped, failed=failed, items=results
    )
