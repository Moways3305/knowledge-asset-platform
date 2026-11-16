"""Read bounded snapshots inside a short transaction; external I/O happens later."""

from datetime import timedelta

from sqlalchemy import func, select

from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetChunk,
    KnowledgeAssetFileObject,
    KnowledgeAssetSummary,
    KnowledgeAssetTag,
    KnowledgeAssetVersion,
)
from app.models.knowledge_correction import KnowledgeCorrection
from app.models.maintenance_agent import MaintenanceCheck
from app.services import maintenance_access as access
from app.services.maintenance_rules import digest
from app.services.permission import knowledge_manager_allowed


async def capture(session, policy, asset, settings, now):
    caller = await access.actor_context(session, policy.authorized_by, policy.authorized_role)
    if not caller or not access.library_allowed(caller, policy.project_id):
        return None, "authorization_expired"
    if not access.eligible(asset) or not knowledge_manager_allowed(caller, asset):
        return None, "asset_out_of_scope"
    version = (
        await session.get(KnowledgeAssetVersion, asset.current_version_id)
        if asset.current_version_id
        else None
    )
    if not version or version.asset_id != asset.id or version.version_status != "active":
        return None, "current_version_unavailable"
    tags = sorted(
        (
            await session.scalars(
                select(KnowledgeAssetTag.tag_name).where(KnowledgeAssetTag.asset_id == asset.id)
            )
        ).all()
    )
    summary_query = select(KnowledgeAssetSummary).where(
        KnowledgeAssetSummary.version_id == version.id,
        KnowledgeAssetSummary.asset_id == asset.id,
        KnowledgeAssetSummary.summary_type.in_(
            [
                "one_liner",
                "detailed",
                "summary",
                "detailed_summary",
                "safe_summary",
                "redacted_summary",
            ]
        ),
    )
    has_summary = bool(
        await session.scalar(
            select(func.count()).select_from(
                summary_query.where(
                    func.length(func.trim(KnowledgeAssetSummary.content)) > 0
                ).subquery()
            )
        )
    )
    responsible = await access.recipients(session, asset)
    facts = {
        "id": str(asset.id),
        "version_id": str(version.id),
        "title": asset.title,
        "directory": version.directory_key,
        "tags": tags,
        "has_summary": has_summary,
        "valid_maintainer": bool(
            asset.maintainer_user_id
            and any(x["id"] == str(asset.maintainer_user_id) for x in responsible)
        ),
        "review_due": access.stamp(asset.review_due_at),
        "updated_at": access.stamp(asset.updated_at),
        "parse_status": version.weknora_parse_status,
        "index_status": version.index_status,
        "file_hash": version.file_hash,
        "status": asset.asset_status,
        "old_correction": bool(
            await session.scalar(
                select(KnowledgeCorrection.id)
                .where(
                    KnowledgeCorrection.asset_id == asset.id,
                    KnowledgeCorrection.status == "open",
                    KnowledgeCorrection.updated_at <= now - timedelta(days=settings.overdue_days),
                )
                .limit(1)
            )
        ),
    }
    # Full eligible library, not the daily delta. A cap is explicit incomplete coverage.
    pairs = (
        await session.execute(
            select(KnowledgeAsset, KnowledgeAssetVersion)
            .join(
                KnowledgeAssetVersion, KnowledgeAsset.current_version_id == KnowledgeAssetVersion.id
            )
            .where(
                access.scope_filter(policy.project_id),
                access.manager_filter(caller),
                KnowledgeAssetVersion.version_status == "active",
            )
            .order_by(KnowledgeAsset.id)
            .limit(501)
        )
    ).all()
    candidates = [
        {
            "id": str(a.id),
            "version_id": str(v.id),
            "title": a.title,
            "file_hash": v.file_hash,
            "stamp": str(a.updated_at),
        }
        for a, v in pairs[:500]
    ]
    allowed = policy.content_authorized and await access.original_allowed(
        session, caller, asset, agent=True
    )
    body, summary, refs = "", "", []
    coverage = {
        "integrity": "complete",
        "maintenance": "complete",
        "duplicates": "complete" if len(pairs) <= 500 else "candidate_limit",
        "availability": "complete",
        "quality": "complete",
    }
    if allowed:
        chunk_filter = (
            KnowledgeAssetChunk.asset_id == asset.id,
            KnowledgeAssetChunk.version_id == version.id,
            KnowledgeAssetChunk.chunk_status == "active",
        )
        count, length = (
            await session.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(func.length(KnowledgeAssetChunk.content_text)), 0),
                ).where(*chunk_filter)
            )
        ).one()
        if count > 200 or length + count > settings.max_body_chars:
            coverage["quality"] = "body_limit"
        else:
            chunks = (
                await session.scalars(
                    select(KnowledgeAssetChunk)
                    .where(*chunk_filter)
                    .order_by(KnowledgeAssetChunk.chunk_index)
                    .limit(200)
                )
            ).all()
            body = "\n".join(c.content_text for c in chunks)
        if coverage["quality"] == "complete" and (
            not body.strip() or version.weknora_parse_status != "completed"
        ):
            coverage["quality"] = "body_unavailable"
        if await session.scalar(
            select(KnowledgeAssetChunk.id)
            .where(
                KnowledgeAssetChunk.version_id == version.id,
                KnowledgeAssetChunk.chunk_status != "active",
            )
            .limit(1)
        ):
            coverage["quality"] = "body_incomplete"
        summary_length = await session.scalar(
            select(func.sum(func.length(KnowledgeAssetSummary.content))).where(
                KnowledgeAssetSummary.asset_id == asset.id,
                KnowledgeAssetSummary.version_id == version.id,
            )
        )
        if (summary_length or 0) > 4900:
            coverage["quality"] = "summary_limit"
        else:
            summaries = (await session.scalars(summary_query)).all()
            summary = "\n".join(s.content or "" for s in summaries)
        refs = list(
            (
                await session.scalars(
                    select(KnowledgeAssetFileObject.storage_ref)
                    .where(
                        KnowledgeAssetFileObject.asset_id == asset.id,
                        KnowledgeAssetFileObject.version_id == version.id,
                        KnowledgeAssetFileObject.file_variant == "original",
                    )
                    .limit(21)
                )
            ).all()
        )
        if len(refs) > 20:
            coverage["availability"] = "file_limit"
    else:
        coverage["quality"] = "content_not_authorized"
        coverage["availability"] = "content_not_authorized"
    if version.weknora_parse_status in {"pending", "processing"} or version.index_status in {
        "not_indexed",
        "indexing",
    }:
        coverage["availability"] = "processing_pending"
    fingerprint = digest([facts, body, summary, refs, allowed, policy.revision, responsible])
    check = await session.scalar(
        select(MaintenanceCheck).where(
            MaintenanceCheck.policy_id == policy.id, MaintenanceCheck.asset_id == asset.id
        )
    )
    return {
        "facts": facts,
        "body": body,
        "summary": summary,
        "refs": refs,
        "allowed": allowed,
        "coverage": coverage,
        "fingerprint": fingerprint,
        "candidate_fingerprint": digest(candidates),
        "candidates": candidates,
        "responsible": responsible,
        "unchanged": bool(
            check
            and check.fingerprint == fingerprint
            and check.policy_revision == policy.revision
            and check.coverage.get("quality") == "complete"
        ),
    }, None
