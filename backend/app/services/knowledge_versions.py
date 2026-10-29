"""Source-bound updates and permission-filtered history; never return storage or raw files."""

import re

from fastapi import HTTPException
from sqlalchemy import or_, select

from app.models.ingest import IngestTask
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetSummary, KnowledgeAssetVersion
from app.schemas.knowledge_review import Command
from app.services import knowledge_review as trust
from app.services.directories import display_path
from app.services.ingest_review_state import effective_status, reviews_by_task
from app.services.knowledge_version_baseline import replacement_baseline_matches
from app.services.permission import AccessLayer, decide
from app.services.permission_rules import load_access_policy
from app.services.summary_policy import REDACTED_SUMMARY_LEVELS


def label(version):
    if not version:
        return None
    value = (version.naming_metadata or {}).get("version")
    return value.upper() if isinstance(value, str) and value else version.version_no.upper()


def order(value):
    if not value or not re.fullmatch(r"V[1-9]\d*(?:\.\d+)*", value):
        raise trust.reject(422, "版本须为 V 加正整数序列，例如 V2 或 V2.1")
    parts = [int(part) for part in value[1:].split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


async def writable_source(session, caller, asset_id, expected_updated_at, *, lock=True):
    asset = await trust._write_asset(
        session,
        caller,
        asset_id,
        Command(expected_updated_at=expected_updated_at, reason="上传关联新版"),
        lock=lock,
    )
    if asset.asset_status not in {"active", "needs_update"} or asset.replacement_asset_id:
        raise trust.reject(409, "请在当前有效资料上发起更新")
    if await pending_adoption(session, asset.id):
        raise trust.reject(409, "请先确认这份新版替代原资料，再发起后续更新")
    version = (
        await session.get(KnowledgeAssetVersion, asset.current_version_id)
        if asset.current_version_id
        else None
    )
    if not version or version.asset_id != asset.id or version.version_status != "active":
        raise trust.reject(409, "资料缺少有效当前版本")
    if not version.directory_key:
        raise trust.reject(409, "请先编辑资料并补齐正式目录，再上传新版")
    return asset, version


async def prepare_upload(
    session, caller, asset_id, expected_updated_at, version_label, *, lock=True
):
    source, version = await writable_source(
        session, caller, asset_id, expected_updated_at, lock=lock
    )
    version_label = version_label.strip().upper()
    if len(version_label) > 20 or order(version_label) <= order(label(version)):
        raise trust.reject(422, "新版本号必须高于原版本且不超过 20 字符")
    normalized = "V" + ".".join(str(part) for part in order(version_label))
    existing = (
        await session.scalars(
            select(IngestTask).where(
                IngestTask.update_of_asset_id == source.id,
                IngestTask.update_version_label == normalized,
            )
        )
    ).all()
    reviews = await reviews_by_task(session, existing)
    if any(
        effective_status(task, reviews.get(task.id))
        not in {"cancelled", "failed", "duplicate_skipped", "rejected"}
        for task in existing
    ):
        raise trust.reject(409, "已有该版本的上传任务，请从版本历史继续处理")
    return source, version


async def update_context_for_task(session, caller, task):
    asset = await trust._load(session, caller, task.update_of_asset_id)
    if not trust.can_manage(caller, asset):
        raise trust.reject(404, "原资料不可管理")
    version = await session.get(KnowledgeAssetVersion, task.update_of_version_id)
    return dict(
        source_asset_id=str(asset.id),
        source_title=asset.title,
        target_scope=asset.scope,
        target_project_id=str(asset.project_id) if asset.project_id else None,
        target_zone=asset.zone,
        confidentiality_level=asset.confidentiality_level,
        directory_key=version.directory_key if version else None,
        version=task.update_version_label,
    )


async def pending_adoption(session, asset_id):
    incoming = await session.scalar(
        select(IngestTask.id)
        .where(IngestTask.result_asset_id == asset_id, IngestTask.update_of_asset_id.is_not(None))
        .limit(1)
    )
    accepted = (
        await session.scalar(
            select(KnowledgeAsset.id)
            .where(KnowledgeAsset.replacement_asset_id == asset_id)
            .limit(1)
        )
        if incoming
        else None
    )
    return bool(incoming and not accepted)


async def validate_update_confirmation(session, caller, task, request):
    source = await trust._load(session, caller, task.update_of_asset_id, write=True)
    if not trust.can_manage(caller, source):
        raise trust.reject(404, "原资料不可管理")
    from app.services.personal_write_policy import personal_asset_write_locked

    if source.scope == "personal" and await personal_asset_write_locked(session, source.id):
        raise trust.reject(409, "原资料正在项目审核或使用，不可更新")
    if (
        source.replacement_asset_id
        or source.asset_status not in {"active", "needs_update"}
        or source.current_version_id != task.update_of_version_id
    ):
        raise trust.reject(409, "原资料的当前版本或状态已变化，请重新发起更新")
    version = await session.get(KnowledgeAssetVersion, task.update_of_version_id)
    key = request.naming.directory_key if request.naming else request.directory_key
    if (
        request.target_scope.value,
        request.target_project_id,
        request.target_zone.value,
        request.confidentiality_level.value,
        key,
    ) != (
        source.scope,
        source.project_id,
        source.zone,
        source.confidentiality_level,
        version.directory_key if version else None,
    ):
        raise trust.reject(422, "新版须沿用原库、项目、资料区、正式目录及密级；调整请走治理流程")
    if request.naming and order(request.naming.version) != order(task.update_version_label):
        raise trust.reject(422, "确认版本与上传时的新版本不一致")


async def visible(session, caller, asset_id, policy):
    asset = await session.get(KnowledgeAsset, asset_id)
    if (
        not asset
        or asset.deleted_at
        or not decide(
            caller, trust._active_projection(asset), AccessLayer.discovery, policy=policy
        ).allowed
    ):
        raise trust.reject(404, "版本不存在或不可见")
    if (
        asset.asset_status in {"archived", "deprecated"}
        and not asset.replacement_asset_id
        and not trust.can_manage(caller, asset)
    ):
        raise trust.reject(404, "版本不存在或不可见")
    return asset


async def history(session, caller, asset_id):
    policy = await load_access_policy(session)
    source = await visible(session, caller, asset_id, policy)
    assets, frontier, truncated = {}, {source.id}, False
    for _ in range(30):
        if not frontier:
            break
        next_ids = set()
        for item_id in sorted(frontier):
            if item_id in assets:
                continue
            if len(assets) >= 50:
                truncated = True
                break
            try:
                item = await visible(session, caller, item_id, policy)
            except HTTPException as exc:
                if exc.status_code == 404:
                    continue
                raise
            assets[item.id] = item
            if item.replacement_asset_id:
                next_ids.add(item.replacement_asset_id)
            next_ids.update(
                await session.scalars(
                    select(KnowledgeAsset.id).where(KnowledgeAsset.replacement_asset_id == item.id)
                )
            )
            tasks = await session.scalars(
                select(IngestTask).where(
                    or_(
                        IngestTask.update_of_asset_id == item.id,
                        (IngestTask.result_asset_id == item.id)
                        & IngestTask.update_of_asset_id.is_not(None),
                    )
                )
            )
            for task in tasks:
                next_ids.add(task.update_of_asset_id)
                if task.result_asset_id:
                    next_ids.add(task.result_asset_id)
        frontier = next_ids - assets.keys()
    else:
        truncated = bool(frontier)
    current, seen = source, set()
    incoming = await session.scalar(
        select(IngestTask)
        .where(IngestTask.result_asset_id == source.id, IngestTask.update_of_asset_id.is_not(None))
        .order_by(IngestTask.created_at.desc())
        .limit(1)
    )
    if incoming:
        parent = assets.get(incoming.update_of_asset_id)
        if await pending_adoption(session, source.id):
            current = parent
    while current and current.replacement_asset_id:
        if current.id in seen:
            current = None
            break
        seen.add(current.id)
        current = assets.get(current.replacement_asset_id)
    rows = list(
        await session.scalars(
            select(KnowledgeAssetVersion)
            .where(KnowledgeAssetVersion.asset_id.in_(assets))
            .order_by(KnowledgeAssetVersion.created_at.desc(), KnowledgeAssetVersion.id)
            .limit(101)
        )
    )
    items = [
        dict(
            asset_id=str(v.asset_id),
            version_id=str(v.id),
            title=assets[v.asset_id].title,
            version=label(v),
            status=assets[v.asset_id].asset_status,
            version_status=v.version_status,
            created_at=v.created_at,
            is_current=bool(
                current
                and current.id == v.asset_id
                and current.current_version_id == v.id
                and current.asset_status in {"active", "needs_update"}
            ),
        )
        for v in rows[:100]
    ]
    updates = []
    if trust.can_manage(caller, source):
        tasks = await session.scalars(
            select(IngestTask)
            .where(IngestTask.update_of_asset_id == source.id)
            .order_by(IngestTask.created_at.desc())
            .limit(20)
        )
        for task in tasks:
            target = assets.get(task.result_asset_id)
            updates.append(
                dict(
                    task_id=str(task.id),
                    version=task.update_version_label,
                    status=task.status,
                    result_asset_id=str(target.id) if target else None,
                    can_replace=bool(
                        target
                        and task.update_of_version_id == source.current_version_id
                        and await replacement_baseline_matches(session, source, target)
                        and source.asset_status in {"active", "needs_update"}
                        and target.asset_status == "active"
                        and not target.replacement_asset_id
                        and trust.freshness(target) == "verified"
                        and not source.replacement_asset_id
                    ),
                )
            )
    original = (
        await session.get(KnowledgeAssetVersion, source.current_version_id)
        if source.current_version_id
        else None
    )
    original_label = label(original)
    next_version = (
        f"V{order(original_label)[0] + 1}"
        if original_label and re.fullmatch(r"V[1-9]\d*(?:\.\d+)*", original_label)
        else "V2"
    )
    return dict(
        asset_id=str(source.id),
        updated_at=source.updated_at,
        current_asset_id=str(current.id)
        if current and current.asset_status in {"active", "needs_update"}
        else None,
        can_update=trust.can_manage(caller, source)
        and source.asset_status in {"active", "needs_update"}
        and not source.replacement_asset_id
        and not await pending_adoption(session, source.id),
        suggested_version=next_version,
        items=items,
        updates=updates,
        truncated=truncated or len(rows) > 100,
    )


async def compare(session, caller, asset_id, left_id, right_id):
    state = await history(session, caller, asset_id)
    allowed = {row["version_id"] for row in state["items"]}
    if str(left_id) not in allowed or str(right_id) not in allowed:
        raise trust.reject(404, "只能比较关联且可见的版本")
    policy = await load_access_policy(session)
    snapshots = []
    for version_id in (left_id, right_id):
        version = await session.get(KnowledgeAssetVersion, version_id)
        asset = await visible(session, caller, version.asset_id, policy)
        summary = None
        if decide(
            caller, trust._active_projection(asset), AccessLayer.summary, policy=policy
        ).allowed:
            rows = await session.scalars(
                select(KnowledgeAssetSummary).where(
                    KnowledgeAssetSummary.version_id == version.id,
                    KnowledgeAssetSummary.asset_id == asset.id,
                )
            )
            smap = {row.summary_type: row.content for row in rows}
            protected = asset.confidentiality_level in REDACTED_SUMMARY_LEVELS or (
                asset.scope == "project" and asset.project_id not in caller.active_project_ids
            )
            summary = (
                (smap.get("redacted_summary") or smap.get("safe_summary"))
                if protected
                else (smap.get("detailed") or smap.get("one_liner"))
            )
        snapshots.append(
            dict(
                version=label(version),
                directory=(version.naming_metadata or {}).get("directory_name")
                or await display_path(session, version.directory_key, asset.project_id),
                summary=summary,
            )
        )
    return dict(
        left=snapshots[0],
        right=snapshots[1],
        changed_fields=[key for key in snapshots[0] if snapshots[0][key] != snapshots[1][key]],
        scope="摘要与版本元信息，不包含原文件全文；无权查看或未生成的摘要为空。",
    )
