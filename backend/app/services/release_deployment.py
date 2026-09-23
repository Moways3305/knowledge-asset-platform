"""Deployment CLI only: record successful probes and create an unpublished draft."""

import uuid

import httpx
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.release_manifest import ReleaseManifest
from app.db.utils import utc_now
from app.models.release_note import ReleaseNote
from app.schemas.enums import AuditLogType
from app.services.audit import record_system_event


async def check_release_identity(session: AsyncSession, manifest: ReleaseManifest) -> None:
    """Read-only preflight before replacing running services."""
    rows = await session.scalars(
        select(ReleaseNote).where(
            or_(
                ReleaseNote.version == manifest.version,
                ReleaseNote.source_commit == manifest.commit,
            )
        )
    )
    for note in rows:
        if note.source_commit:
            if (
                note.version != manifest.version
                or note.source_commit != manifest.commit
                or note.manifest_digest != manifest.digest
            ):
                raise ValueError("版本号或提交已绑定其他发布清单，请使用新版本与新提交")
        elif note.published_at:
            raise ValueError("已有历史公告不能自动认定为本次部署，请使用新版本号")


async def verify_deployment(client: httpx.AsyncClient, manifest: ReleaseManifest) -> None:
    """Verify the user-entry frontend and its backend, not just a new container's health."""
    expected = {"version": manifest.version, "commit": manifest.commit}
    for path in ("/release-identity.json", "/health/release"):
        response = await client.get(path, headers={"Cache-Control": "no-cache"})
        response.raise_for_status()
        if response.json() != expected:
            raise ValueError("前后端版本与发布清单不一致；未登记部署")
    ready = await client.get("/health/ready")
    ready.raise_for_status()
    if ready.json().get("status") != "ready":
        raise ValueError("服务尚未就绪；未登记部署")
    config = await client.get("/health/config")
    config.raise_for_status()
    diagnostics = config.json()
    if (
        diagnostics.get("production_blockers") != []
        or diagnostics.get("production_ready") is not True
    ):
        raise ValueError("生产配置检查未通过；未登记部署")


async def record_deployment(session: AsyncSession, manifest: ReleaseManifest) -> ReleaseNote:
    """Only call after probes succeed. Atomic and retry-safe; never overwrite editorial work."""
    note = await session.scalar(
        select(ReleaseNote)
        .where(ReleaseNote.version == manifest.version)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if note and note.source_commit:
        if note.source_commit != manifest.commit or note.manifest_digest != manifest.digest:
            raise ValueError("版本号已绑定其他提交或清单；请使用新版本号")
        return note
    if note and note.published_at:
        raise ValueError("已有历史公告不能自动认定为本次部署，请使用新版本号")
    try:
        if note is None:
            note = ReleaseNote(
                id=uuid.uuid4(), **manifest.model_dump(exclude={"commit", "previous_commit"})
            )
            session.add(note)
        else:
            note.revision += 1  # Invalidate any editor opened before deployment binding.
        note.source_commit = manifest.commit
        note.previous_commit = manifest.previous_commit
        note.manifest_digest = manifest.digest
        note.deployed_at = utc_now()
        note.updated_at = utc_now()
        await session.flush()
        await record_system_event(
            session,
            log_type=AuditLogType.operation,
            action="release_note.deployment_verified",
            trace_id=f"release-{manifest.commit[:12]}",
            target_type="release_note",
            target_id=note.id,
            after={"version": note.version, "commit": note.source_commit},
        )
        await session.commit()
        return note
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(
            select(ReleaseNote).where(ReleaseNote.version == manifest.version)
        )
        if (
            existing
            and existing.source_commit == manifest.commit
            and existing.manifest_digest == manifest.digest
        ):
            return existing
        raise ValueError("版本或提交发生并发冲突；未覆盖已有日志") from None
