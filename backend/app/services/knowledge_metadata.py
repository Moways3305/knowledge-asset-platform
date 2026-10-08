"""Scope-governed metadata changes, independent of upload and original-file mutation."""

from datetime import timezone
from hashlib import sha256

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.db.utils import utc_now
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetTag, KnowledgeAssetVersion
from app.models.original_access import AccessGrant, OriginalAccessRequest
from app.models.preview import PreviewCredential
from app.schemas.enums import AuditAction, AuditLogType
from app.services import audit
from app.services.permission import knowledge_manager_allowed


def can_edit_metadata(caller, asset):
    if asset.asset_status not in {"active", "needs_update"}:
        return False
    return knowledge_manager_allowed(caller, asset)


def denied(code, message):
    return HTTPException(
        code, detail={"denied_reason": "metadata_edit_rejected", "message": message}
    )


async def update_metadata(session, caller, asset_id, req, trace_id):
    from app.services.directories import validate_directory
    from app.services.ingest_persistence import build_summaries
    from app.services.personal_write_policy import personal_asset_write_locked

    asset = (
        await session.execute(
            select(KnowledgeAsset)
            .where(KnowledgeAsset.id == asset_id)
            .options(selectinload(KnowledgeAsset.tags), selectinload(KnowledgeAsset.summaries))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if asset is None or not can_edit_metadata(caller, asset):
        raise denied(404, "资料不存在或无编辑权限")
    if asset.scope == "personal" and await personal_asset_write_locked(session, asset.id):
        raise denied(409, "项目审核或项目使用中的资料不可直接修改")
    actual = asset.updated_at
    if (
        actual is None
        or actual.replace(tzinfo=actual.tzinfo or timezone.utc) != req.expected_updated_at
    ):
        raise denied(409, "资料已被更新，请刷新后重新编辑")
    level = (
        req.confidentiality_level.value
        if req.confidentiality_level
        else asset.confidentiality_level
    )
    changed_level = level != asset.confidentiality_level
    if level == "L5" and asset.scope != "personal" and not caller.can_discover_l5:
        raise denied(403, "当前身份不能管理 L5 资料，请交由具有该等级权限的管理人处理")
    if level < asset.confidentiality_level and not req.confirm_downgrade:
        raise denied(422, "降低保密等级可能扩大访问范围，请明确确认")
    version = (
        await session.get(KnowledgeAssetVersion, asset.current_version_id)
        if asset.current_version_id
        else None
    )
    if (req.summary is not None or req.directory_key is not None) and version is None:
        raise denied(409, "资料缺少当前版本，暂不能修改摘要或正式目录")
    before = {
        "title": asset.title,
        "asset_type": asset.asset_type,
        "tags": [tag.tag_name for tag in asset.tags],
        "confidentiality_level": asset.confidentiality_level,
        "directory_key": version.directory_key if version else None,
    }
    if req.directory_key is not None:
        if req.directory_key == "personal.pending":
            raise denied(422, "请选择正式个人目录")
        rule_version, _ = await validate_directory(
            session, directory_key=req.directory_key, scope=asset.scope, project_id=asset.project_id
        )
        version.directory_key = req.directory_key
        version.directory_rule_version = rule_version
        version.directory_confirmed_by = caller.user_id
    if req.title is not None:
        asset.title = req.title
    if req.asset_type is not None:
        asset.asset_type = req.asset_type.value
    if req.tags is not None:
        asset.tags.clear()
        # Delete old rows before inserting overlapping names (unique asset/tag key).
        await session.flush()
        asset.tags.extend(KnowledgeAssetTag(tag_name=tag) for tag in req.tags)
    if version and (req.summary is not None or changed_level):
        current = [s for s in asset.summaries if s.version_id == version.id]
        sources = {s.summary_type: s.content for s in current}
        detailed = (
            req.summary
            if req.summary is not None
            else sources.get("detailed") or sources.get("one_liner") or ""
        )
        before["summary_hash"] = sha256((sources.get("detailed") or "").encode()).hexdigest()
        for row in current:
            asset.summaries.remove(row)
        await session.flush()
        for row in build_summaries(
            level,
            one_liner=detailed[:200] if req.summary is not None else sources.get("one_liner"),
            detailed=detailed,
            key_points=[]
            if req.summary is not None
            else (sources.get("key_points") or "").splitlines(),
        ):
            row.version_id = version.id
            asset.summaries.append(row)
    asset.confidentiality_level = level
    now = utc_now()
    # Classification changes must not leave previously issued preview capabilities alive.
    if changed_level:
        await session.execute(
            update(PreviewCredential)
            .where(
                PreviewCredential.target_asset_id == asset.id,
                PreviewCredential.credential_status == "active",
            )
            .values(credential_status="revoked", revoked_at=now)
        )
        if level > before["confidentiality_level"]:
            await session.execute(
                update(OriginalAccessRequest)
                .where(
                    OriginalAccessRequest.asset_id == asset.id,
                    OriginalAccessRequest.status == "pending",
                )
                .values(status="cancelled", review_note="保密等级提升，请按新等级重新申请")
            )
            await session.execute(
                update(AccessGrant)
                .where(
                    AccessGrant.asset_id == asset.id,
                    AccessGrant.status == "active",
                )
                .values(
                    status="revoked",
                    revoked_at=now,
                    revoked_by_user_id=caller.user_id,
                    revoke_reason="保密等级提升，需重新审批",
                )
            )
    asset.updated_at = now
    after = {
        "title": asset.title,
        "asset_type": asset.asset_type,
        "tags": [tag.tag_name for tag in asset.tags],
        "confidentiality_level": level,
        "directory_key": version.directory_key if version else None,
    }
    if req.summary is not None:
        after["summary_hash"] = sha256(req.summary.encode()).hexdigest()
    await audit.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.knowledge_asset_metadata_updated.value,
        trace_id=trace_id,
        target_type="knowledge_asset",
        target_id=asset.id,
        before=before,
        after=after,
        extra={
            "reason": req.reason,
            "changed_fields": sorted(
                req.model_fields_set - {"reason", "expected_updated_at", "confirm_downgrade"}
            ),
        },
        risk_level="high" if changed_level else None,
    )
    await session.commit()
    return {"asset_id": asset.id, "updated_at": now}
