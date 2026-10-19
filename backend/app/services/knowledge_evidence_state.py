"""Permission-trimmed platform facts for QA; document prose cannot establish adoption."""

from types import SimpleNamespace

from sqlalchemy import select

from app.models.ingest import IngestTask
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.schemas.permission import AccessChannel, AccessLayer
from app.services.knowledge_review import freshness, stamp
from app.services.knowledge_versions import label
from app.services.permission import decide
from app.services.permission_rules import load_access_policy


async def attach_platform_state(
    session, caller, evidences, recalled, *, channel=AccessChannel.human, asset_guard=None
):
    if not evidences:
        return
    by_id = {r.asset.id: r for r in recalled}
    ids = {e.asset.id for e in evidences if e.asset.id in by_id}
    if not ids:
        return
    policy = await load_access_policy(session)
    # Read scalars without refreshing the ORM objects used to collect evidence.
    # A concurrent edit must not label an older evidence snapshot as current.
    snapshots = {
        row.id: row
        for row in (
            await session.execute(
                select(
                    KnowledgeAsset.id,
                    KnowledgeAsset.current_version_id,
                    KnowledgeAsset.updated_at,
                    KnowledgeAsset.asset_status,
                    KnowledgeAsset.deleted_at,
                    KnowledgeAsset.replacement_asset_id,
                    KnowledgeAssetVersion.version_status.label("live_version_status"),
                )
                .outerjoin(
                    KnowledgeAssetVersion,
                    KnowledgeAssetVersion.id == KnowledgeAsset.current_version_id,
                )
                .where(KnowledgeAsset.id.in_(ids))
            )
        ).all()
    }

    def visible_link(source, target):
        # Replacement is only meaningful within the same library and level.
        # Do not expose even a relationship flag across a permission ceiling.
        if (
            source.deleted_at is not None
            or (source.scope, source.project_id, source.confidentiality_level)
            != (target.scope, target.project_id, target.confidentiality_level)
            or (source.scope == "personal" and source.owner_user_id != target.owner_user_id)
            or (asset_guard is not None and not asset_guard(source))
        ):
            return False
        # Historical-version discovery uses the same active projection as the
        # existing version-history service. No source IDs, titles or text leave.
        projection = SimpleNamespace(
            scope=source.scope,
            asset_status="active",
            owner_user_id=source.owner_user_id,
            project_id=source.project_id,
            confidentiality_level=source.confidentiality_level,
            visibility=source.visibility,
            ai_access_level=source.ai_access_level,
        )
        return decide(
            caller, projection, AccessLayer.discovery, channel=channel, policy=policy
        ).allowed

    accepted = set()
    sources = (
        await session.scalars(
            select(KnowledgeAsset).where(
                KnowledgeAsset.replacement_asset_id.in_(ids),
                KnowledgeAsset.asset_status == "archived",
                KnowledgeAsset.deleted_at.is_(None),
            )
        )
    ).all()
    for source in sources:
        target = by_id[source.replacement_asset_id].asset
        if visible_link(source, target):
            accepted.add(target.id)

    pending = set()
    incoming = (
        await session.execute(
            select(IngestTask.result_asset_id, KnowledgeAsset)
            .join(KnowledgeAsset, KnowledgeAsset.id == IngestTask.update_of_asset_id)
            .where(IngestTask.result_asset_id.in_(ids), IngestTask.update_of_asset_id.is_not(None))
        )
    ).all()
    for target_id, source in incoming:
        if target_id not in accepted and visible_link(source, by_id[target_id].asset):
            pending.add(target_id)

    for e in evidences:
        r = by_id.get(e.asset.id)
        if r is None:
            continue
        asset, version = r.asset, r.version
        snapshot = snapshots.get(asset.id)
        if (
            snapshot is None
            or snapshot.current_version_id != asset.current_version_id
            or stamp(snapshot.updated_at) != stamp(asset.updated_at)
            or snapshot.asset_status != asset.asset_status
            or snapshot.deleted_at is not None
            or snapshot.replacement_asset_id != asset.replacement_asset_id
            or (
                snapshot.current_version_id is not None
                and snapshot.live_version_status != version.version_status
            )
        ):
            e.platform_state = {
                "version": label(version),
                "version_selection": "unknown",
                "asset_status": "unknown",
                "review_status": "unknown",
                "adoption_status": "unknown",
            }
            continue
        selection = (
            "current"
            if asset.current_version_id == version.id
            else "legacy_active"
            if asset.current_version_id is None and version.version_status == "active"
            else "not_current"
        )
        adoption = "unknown"
        if (
            selection == "current"
            and asset.asset_status == "active"
            and version.version_status == "active"
            and not asset.replacement_asset_id
        ):
            adoption = (
                "adopted"
                if asset.id in accepted
                else "pending"
                if asset.id in pending
                else "unknown"
            )
        e.platform_state = {
            "version": label(version),
            "version_selection": selection,
            "asset_status": asset.asset_status,
            "review_status": freshness(asset),
            "adoption_status": adoption,
        }
