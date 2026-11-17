"""Knowledge trust loop. Due dates never archive content; corrections never grant access."""

import json
import time
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select

from app.db.utils import as_utc as stamp
from app.db.utils import utc_now
from app.models.identity import User
from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetSummary,
    KnowledgeAssetTag,
    KnowledgeAssetVersion,
)
from app.models.knowledge_correction import KnowledgeCorrection
from app.schemas.enums import AuditLogType
from app.schemas.knowledge_review import (
    CorrectionOut,
    MaintenanceItem,
    MaintenancePage,
    ReplacementOption,
    ReviewState,
)
from app.schemas.lifecycle import ArchiveConfirmBody
from app.services import audit, lifecycle, operation_events
from app.services.jobs import governance_scan
from app.services.knowledge_responsibility import (
    eligible_maintainers,
    maintainer_contexts,
    responsible_for,
    responsible_recipients,
)
from app.services.permission import (
    AccessLayer,
    decide,
    knowledge_maintainer_allowed,
    knowledge_manager_allowed,
)
from app.services.permission_rules import load_access_policy
from app.worker.enqueue import enqueue_outbox_delivery


def _active_projection(asset):
    return SimpleNamespace(
        scope=asset.scope,
        asset_status="active",
        owner_user_id=asset.owner_user_id,
        project_id=asset.project_id,
        confidentiality_level=asset.confidentiality_level,
        visibility=asset.visibility,
        ai_access_level=asset.ai_access_level,
    )


def can_manage(caller, asset):
    # Explicit delegated maintenance is restricted to this asset; assignment alone grants nothing.
    return asset.deleted_at is None and knowledge_maintainer_allowed(caller, asset)


def reject(status, message):
    return HTTPException(
        status, detail={"denied_reason": "knowledge_review_rejected", "message": message}
    )


async def _load(session, caller, asset_id, *, write=False):
    stmt = select(KnowledgeAsset).where(KnowledgeAsset.id == asset_id)
    if write:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    asset = (await session.execute(stmt)).scalar_one_or_none()
    if asset is None or asset.deleted_at is not None:
        raise reject(404, "资料不存在或不可见")
    policy = await load_access_policy(session)
    visible = decide(caller, asset, AccessLayer.discovery, policy=policy).allowed
    # Only managers and existing reporters can revisit an archived correction.
    if not visible and not can_manage(caller, asset):
        reporter = await session.scalar(
            select(KnowledgeCorrection.id)
            .where(
                KnowledgeCorrection.asset_id == asset.id,
                KnowledgeCorrection.reporter_user_id == caller.user_id,
            )
            .limit(1)
        )
        visible = (
            bool(reporter)
            and decide(
                caller, _active_projection(asset), AccessLayer.discovery, policy=policy
            ).allowed
        )
    if not visible and not can_manage(caller, asset):
        raise reject(404, "资料不存在或不可见")
    return asset


def check_stamp(actual, expected):
    if stamp(actual) != stamp(expected):
        raise reject(409, "记录已更新，请刷新后重试")


async def _write_asset(session, caller, asset_id, req, *, lock=True):
    from app.services.personal_write_policy import personal_asset_write_locked

    asset = await _load(session, caller, asset_id, write=lock)
    if not can_manage(caller, asset):
        raise reject(404, "资料不存在或无治理权限")
    if asset.scope == "personal" and await personal_asset_write_locked(session, asset.id):
        raise reject(409, "项目审核或项目使用中的资料不可直接修改")
    check_stamp(asset.updated_at, req.expected_updated_at)
    return asset


async def _audit(session, caller, asset, action, trace_id, **extra):
    await audit.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=f"knowledge.{action}",
        trace_id=trace_id,
        target_type="knowledge_asset",
        target_id=asset.id,
        project_id=asset.project_id,
        extra=extra,
    )


async def fingerprint(session, asset):
    """Responsibility/due-date changes are not evidence of a corrected document."""
    version = (
        await session.get(KnowledgeAssetVersion, asset.current_version_id)
        if asset.current_version_id
        else None
    )
    summaries = (
        await session.execute(
            select(KnowledgeAssetSummary.summary_type, KnowledgeAssetSummary.content).where(
                KnowledgeAssetSummary.asset_id == asset.id,
                KnowledgeAssetSummary.version_id == asset.current_version_id,
            )
        )
    ).all()
    tags = (
        await session.scalars(
            select(KnowledgeAssetTag.tag_name).where(KnowledgeAssetTag.asset_id == asset.id)
        )
    ).all()
    data = {
        "title": asset.title,
        "type": asset.asset_type,
        "level": asset.confidentiality_level,
        "version": str(asset.current_version_id),
        "directory": version.directory_key if version else None,
        "tags": sorted(tags),
        "summaries": sorted([list(row) for row in summaries]),
    }
    return sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def _maintainers(session, asset):
    candidates = await maintainer_contexts(session)
    if asset.scope == "company" and asset.confidentiality_level != "L5":
        return [
            {
                "id": str(user.id),
                "name": user.name,
                "requires_delegation": "true"
                if not any(knowledge_manager_allowed(ctx, asset) for ctx in contexts)
                else "false",
            }
            for user, contexts in candidates
            if any(ctx.is_active and ctx.is_business_user for ctx in contexts)
        ]
    return eligible_maintainers(asset, candidates)


def freshness(asset):
    if asset.asset_status in {"archived", "deprecated"}:
        return "archived"
    if asset.asset_status == "needs_update":
        return "needs_update"
    if asset.review_due_at and stamp(asset.review_due_at) <= utc_now():
        return "due"
    if asset.verified_at is None:
        return "unreviewed"
    return "verified" if stamp(asset.verified_updated_at) == stamp(asset.updated_at) else "changed"


async def get_state(session, caller, asset_id):
    asset = await _load(session, caller, asset_id)
    manager = can_manage(caller, asset)
    stmt = select(KnowledgeCorrection).where(KnowledgeCorrection.asset_id == asset.id)
    if not manager:
        stmt = stmt.where(KnowledgeCorrection.reporter_user_id == caller.user_id)
    rows = (await session.scalars(stmt.order_by(KnowledgeCorrection.created_at.desc()))).all()
    maintainer = (
        await session.get(User, asset.maintainer_user_id) if asset.maintainer_user_id else None
    )
    # Never disclose a replacement identifier across scope/permission boundaries.
    replacement_id = None
    if asset.replacement_asset_id:
        policy = await load_access_policy(session)
        cursor, seen = asset.replacement_asset_id, {asset.id}
        for _ in range(50):
            if cursor in seen:
                break
            seen.add(cursor)
            target = await session.get(KnowledgeAsset, cursor)
            if (
                not target
                or target.deleted_at
                or not decide(
                    caller, _active_projection(target), AccessLayer.discovery, policy=policy
                ).allowed
            ):
                break
            if not target.replacement_asset_id:
                if decide(caller, target, AccessLayer.discovery, policy=policy).allowed:
                    replacement_id = target.id
                break
            cursor = target.replacement_asset_id
    return ReviewState(
        asset_id=asset.id,
        updated_at=asset.updated_at,
        maintainer_user_id=asset.maintainer_user_id,
        maintainer_name=maintainer.name if maintainer else None,
        review_due_at=asset.review_due_at,
        review_interval_days=asset.review_interval_days,
        maintenance_delegated=asset.maintenance_delegated,
        can_assign=knowledge_manager_allowed(caller, asset),
        verified_at=asset.verified_at,
        freshness=freshness(asset),
        replacement_asset_id=replacement_id,
        can_manage=manager,
        corrections=[
            CorrectionOut(
                id=row.id,
                status=row.status,
                description=row.description,
                resolution=row.resolution
                if manager
                else (
                    "资料已处理，请核查你当前可访问的内容，再确认问题是否解决。"
                    if row.resolution
                    else None
                ),
                updated_at=row.updated_at,
                can_resolve=manager and row.status == "open",
                can_verify=row.reporter_user_id == caller.user_id and row.status == "resolved",
                can_withdraw=row.reporter_user_id == caller.user_id
                and row.status in {"open", "resolved"},
                can_reopen=(row.reporter_user_id == caller.user_id or manager)
                and row.status in {"resolved", "verified", "rejected", "duplicate", "withdrawn"},
                can_close=knowledge_manager_allowed(caller, asset) and row.status == "resolved",
            )
            for row in rows
        ],
        maintainers=await _maintainers(session, asset)
        if knowledge_manager_allowed(caller, asset)
        else [],
    )


async def set_policy(session, caller, asset_id, req, trace_id):
    asset = await _write_asset(session, caller, asset_id, req)
    if asset.asset_status not in {"active", "needs_update"}:
        raise reject(409, "请先处理归档或停用状态")
    if req.review_due_at and stamp(req.review_due_at) <= utc_now():
        raise reject(422, "下次复核时间必须在未来")
    if not knowledge_manager_allowed(caller, asset):
        if (
            req.maintainer_user_id != asset.maintainer_user_id
            or req.maintenance_delegated != asset.maintenance_delegated
        ):
            raise reject(403, "维护人和授权只能由知识库管理人调整")
    elif req.maintainer_user_id:
        candidates = await maintainer_contexts(session)
        eligible = eligible_maintainers(asset, candidates)
        if req.maintenance_delegated:
            if asset.scope != "company" or asset.confidentiality_level == "L5":
                raise reject(422, "受限维护授权仅适用于公司库 L1—L4 资料")
            eligible = [
                {"id": str(u.id)}
                for u, contexts in candidates
                if any(ctx.is_business_user for ctx in contexts)
            ]
        if str(req.maintainer_user_id) not in {row["id"] for row in eligible}:
            raise reject(422, "请选择有管理权限的维护人，或明确授予此资料的维护权限")
    elif req.maintenance_delegated:
        raise reject(422, "请先选择被授权的维护人")
    # updated_at remains the optimistic-concurrency token for all asset writes.
    # Carry a CURRENT verification across responsibility/schedule-only changes,
    # without inventing a new review or masking an earlier content change.
    verification_current = (
        asset.verified_at is not None
        and asset.verified_updated_at is not None
        and stamp(asset.verified_updated_at) == stamp(asset.updated_at)
    )
    if (asset.maintainer_user_id, asset.maintenance_delegated) != (
        req.maintainer_user_id,
        req.maintenance_delegated,
    ):
        from sqlalchemy import update

        from app.models.preview import PreviewCredential

        await session.execute(
            update(PreviewCredential)
            .where(
                PreviewCredential.target_asset_id == asset.id,
                PreviewCredential.credential_status == "active",
            )
            .values(credential_status="revoked", revoked_at=utc_now())
        )
    asset.maintainer_user_id = req.maintainer_user_id
    asset.maintenance_delegated = req.maintenance_delegated
    asset.review_interval_days = req.review_interval_days
    asset.review_due_at = req.review_due_at or (
        utc_now() + timedelta(days=req.review_interval_days) if req.review_interval_days else None
    )
    asset.updated_at = utc_now()
    if verification_current:
        asset.verified_updated_at = asset.updated_at
    await _audit(
        session,
        caller,
        asset,
        "review_policy_changed",
        trace_id,
        maintainer_user_id=str(req.maintainer_user_id),
        review_due_at=asset.review_due_at.isoformat() if asset.review_due_at else None,
        review_interval_days=req.review_interval_days,
        maintenance_delegated=req.maintenance_delegated,
    )
    await operation_events.publish_knowledge_trust(
        session,
        asset,
        [req.maintainer_user_id] if req.maintainer_user_id else [],
        "assigned",
        str(asset.updated_at),
    )
    from app.services.maintenance_reconcile import reconcile_asset

    await session.flush()
    await reconcile_asset(session, asset)
    await session.commit()
    await enqueue_outbox_delivery(session)
    return await get_state(session, caller, asset_id)


async def review(session, caller, asset_id, req, trace_id):
    asset = await _write_asset(session, caller, asset_id, req)
    if asset.asset_status not in {"active", "needs_update"} or asset.replacement_asset_id:
        raise reject(409, "归档、停用或已替代资料不可直接验证")
    now = utc_now()
    if req.outcome == "verified":
        if req.next_review_at is not None and stamp(req.next_review_at) <= now:
            raise reject(422, "指定的下次复核日期必须在未来")
        unresolved = await session.scalar(
            select(KnowledgeCorrection.id)
            .where(KnowledgeCorrection.asset_id == asset.id, KnowledgeCorrection.status == "open")
            .limit(1)
        )
        if unresolved:
            raise reject(409, "仍有未处理的纠错，请先处理后再复核")
        asset.asset_status = "active"
        asset.verified_at = now
        asset.verified_updated_at = now
        asset.verified_by_user_id = caller.user_id
        asset.review_due_at = req.next_review_at or (
            now + timedelta(days=asset.review_interval_days) if asset.review_interval_days else None
        )
    else:
        asset.asset_status = "needs_update"
        asset.verified_updated_at = None
    asset.updated_at = now
    await _audit(
        session, caller, asset, "review_completed", trace_id, outcome=req.outcome, reason=req.reason
    )
    from app.services.maintenance_reconcile import reconcile_asset

    await session.flush()
    await reconcile_asset(session, asset)
    await session.commit()
    await enqueue_outbox_delivery(session)
    return await get_state(session, caller, asset_id)


async def replacement_options(session, caller, asset_id, keyword):
    asset = await _load(session, caller, asset_id)
    if not can_manage(caller, asset):
        raise reject(404, "资料不存在或无治理权限")
    target = KnowledgeAsset
    open_issue = (
        select(KnowledgeCorrection.id)
        .where(KnowledgeCorrection.asset_id == target.id, KnowledgeCorrection.status == "open")
        .exists()
    )
    stmt = select(target).where(
        target.id != asset.id,
        target.scope == asset.scope,
        target.project_id == asset.project_id,
        target.confidentiality_level == asset.confidentiality_level,
        target.deleted_at.is_(None),
        target.asset_status == "active",
        target.replacement_asset_id.is_(None),
        target.current_version_id.is_not(None),
        ~open_issue,
    )
    if asset.scope == "personal":
        stmt = stmt.where(target.owner_user_id == asset.owner_user_id)
    if keyword.strip():
        stmt = stmt.where(target.title.icontains(keyword.strip(), autoescape=True))
    rows = (
        await session.scalars(stmt.order_by(target.verified_at.desc(), target.id).limit(20))
    ).all()
    return [ReplacementOption(asset_id=row.id, title=row.title) for row in rows]


async def replace(session, caller, asset_id, req, trace_id):
    # Acquire both assets in a globally stable order to prevent inverse replacement deadlocks.
    ids = {asset_id}
    if req.replacement_asset_id:
        ids.add(req.replacement_asset_id)
    await session.execute(
        select(KnowledgeAsset)
        .where(KnowledgeAsset.id.in_(ids))
        .order_by(KnowledgeAsset.id)
        .with_for_update()
    )
    asset = await _write_asset(session, caller, asset_id, req)
    if not knowledge_manager_allowed(caller, asset):
        raise reject(403, "新版发布与旧版归档须由知识库管理人确认")
    if req.replacement_asset_id is None:
        asset.replacement_asset_id = None
        asset.updated_at = utc_now()
        await _audit(session, caller, asset, "replacement_withdrawn", trace_id, reason=req.reason)
        await session.commit()
        await enqueue_outbox_delivery(session)
        return await get_state(session, caller, asset_id)
    if req.replacement_asset_id == asset.id or asset.asset_status not in {"active", "needs_update"}:
        raise reject(409, "不可关联自身或替代已归档资料")
    target = await _load(session, caller, req.replacement_asset_id, write=True)
    if not can_manage(caller, target):
        raise reject(404, "新版不存在或无管理权限")
    if req.expected_replacement_updated_at is None:
        raise reject(422, "请先读取新版状态并确认版本")
    check_stamp(target.updated_at, req.expected_replacement_updated_at)
    from app.services.knowledge_version_baseline import replacement_baseline_matches

    if not await replacement_baseline_matches(session, asset, target):
        raise reject(409, "新版基于其它资料或已过期版本，请基于当前版本重新发起更新")
    target_version = (
        await session.get(KnowledgeAssetVersion, target.current_version_id)
        if target.current_version_id
        else None
    )
    if (
        target_version is None
        or target_version.asset_id != target.id
        or target_version.version_status != "active"
    ):
        raise reject(409, "新版缺少已确认的有效版本，请先完成入库")
    if (
        asset.scope,
        asset.project_id,
        asset.owner_user_id if asset.scope == "personal" else None,
        asset.confidentiality_level,
    ) != (
        target.scope,
        target.project_id,
        target.owner_user_id if target.scope == "personal" else None,
        target.confidentiality_level,
    ):
        raise reject(422, "新版必须在同一知识库且保密等级一致，请先走正式调整流程")
    if target.asset_status != "active" or target.replacement_asset_id:
        raise reject(409, "新版必须是有效资料，且不能再次指向其它新版")
    pending = await session.scalar(
        select(KnowledgeCorrection.id)
        .where(KnowledgeCorrection.asset_id == target.id, KnowledgeCorrection.status == "open")
        .limit(1)
    )
    if pending:
        raise reject(409, "新版仍有未处理纠错，请先处理反馈")
    # Sequential historical chains are valid. Both endpoints are locked above;
    # source must be active and target must be terminal, preventing inverse cycles.
    if not req.confirm_archive:
        raise reject(409, "尚未明确确认旧版归档")
    asset.replacement_asset_id = target.id
    asset.updated_at = utc_now()
    # One explicit confirmation covers current content and adoption. Scheduling is optional.
    target.verified_at = target.verified_updated_at = target.updated_at = utc_now()
    target.verified_by_user_id = caller.user_id
    if target.review_interval_days:
        target.review_due_at = utc_now() + timedelta(days=target.review_interval_days)
    elif target.review_due_at and stamp(target.review_due_at) <= utc_now():
        target.review_due_at = None
    await _audit(
        session,
        caller,
        asset,
        "replacement_linked",
        trace_id,
        replacement_asset_id=str(target.id),
        reason=req.reason,
    )
    # Both endpoints are already locked. Persist the replacement link before the
    # lifecycle command refreshes its locked row; keep the same atomic transaction.
    await session.flush()
    # Existing lifecycle command keeps revocation/audit behavior and commits atomically.
    await lifecycle.archive_confirm(
        session, caller, asset.id, ArchiveConfirmBody(reason=req.reason), trace_id
    )
    return await get_state(session, caller, asset_id)


async def report(session, caller, asset_id, req, trace_id):
    asset = await _load(session, caller, asset_id, write=True)
    if asset.asset_status not in {"active", "needs_update"}:
        raise reject(409, "请针对当前有效资料提出纠错")
    check_stamp(asset.updated_at, req.expected_updated_at)
    existing = await session.scalar(
        select(KnowledgeCorrection.id)
        .where(
            KnowledgeCorrection.asset_id == asset.id,
            KnowledgeCorrection.reporter_user_id == caller.user_id,
            KnowledgeCorrection.status.in_(["open", "resolved"]),
        )
        .limit(1)
    )
    if existing:
        raise reject(409, "你已有待处理或待验证的纠错，请继续处理原记录")
    row = KnowledgeCorrection(
        asset_id=asset.id,
        reporter_user_id=caller.user_id,
        description=audit.sanitize_text(req.reason),
        reported_updated_at=asset.updated_at,
        reported_fingerprint=await fingerprint(session, asset),
    )
    session.add(row)
    await session.flush()
    await _audit(session, caller, asset, "correction_reported", trace_id, correction_id=str(row.id))
    await operation_events.publish_knowledge_trust(
        session, asset, await responsible_recipients(session, asset), "correction", str(row.id)
    )
    await session.commit()
    await enqueue_outbox_delivery(session)
    return await get_state(session, caller, asset_id)


async def transition(session, caller, asset_id, correction_id, req, trace_id):
    # Lock old/new assets globally before the correction row (same order as replacement).
    initial = await _load(session, caller, asset_id)
    initial_replacement = initial.replacement_asset_id
    initial_row = await session.get(KnowledgeCorrection, correction_id)
    ids = {asset_id}
    if initial_replacement:
        ids.add(initial_replacement)
    if initial_row and initial_row.asset_id == asset_id and initial_row.resolved_asset_id:
        ids.add(initial_row.resolved_asset_id)
    await session.execute(
        select(KnowledgeAsset)
        .where(KnowledgeAsset.id.in_(ids))
        .order_by(KnowledgeAsset.id)
        .with_for_update()
    )
    asset = await _load(session, caller, asset_id, write=True)
    if asset.replacement_asset_id != initial_replacement:
        raise reject(409, "新版关联已变化，请刷新后重试")
    row = await session.scalar(
        select(KnowledgeCorrection)
        .where(KnowledgeCorrection.id == correction_id, KnowledgeCorrection.asset_id == asset.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise reject(404, "纠错记录不存在")
    check_stamp(row.updated_at, req.expected_updated_at)
    now = utc_now()
    if req.action == "resolve":
        if not can_manage(caller, asset) or row.status != "open":
            raise reject(409, "当前记录不可处理或无处理权限")
        target = asset
        if asset.replacement_asset_id:
            target = await _load(session, caller, asset.replacement_asset_id, write=True)
        current_fingerprint = await fingerprint(session, target)
        if current_fingerprint == row.reported_fingerprint:
            raise reject(409, "资料内容尚未修改，维护安排变化不算纠错处理")
        if target.asset_status not in {"active", "needs_update"}:
            raise reject(409, "请先更新或关联有效新版")
        row.resolution = audit.sanitize_text(req.reason)
        row.resolved_updated_at = target.updated_at
        row.resolved_fingerprint = current_fingerprint
        row.resolved_asset_id = target.id
        row.resolved_by_user_id = caller.user_id
        row.status = "resolved"
        await operation_events.publish_knowledge_trust(
            session, asset, [row.reporter_user_id], "resolved", str(row.id) + str(now)
        )
    elif req.action in {"reject", "duplicate", "withdraw"}:
        if req.action == "withdraw":
            if row.reporter_user_id != caller.user_id or row.status not in {"open", "resolved"}:
                raise reject(409, "只能撤回自己尚未结束的反馈")
            row.status = "withdrawn"
        else:
            if not can_manage(caller, asset) or row.status != "open":
                raise reject(409, "只有维护人可处理尚未结束的反馈")
            row.status = "rejected" if req.action == "reject" else "duplicate"
        row.resolution = audit.sanitize_text(req.reason)
        row.resolved_by_user_id = caller.user_id
        await operation_events.publish_knowledge_trust(
            session, asset, [row.reporter_user_id], "closed", str(row.id) + str(now)
        )
    elif req.action == "reopen":
        if not (
            row.reporter_user_id == caller.user_id or can_manage(caller, asset)
        ) or row.status not in {"resolved", "verified", "rejected", "duplicate", "withdrawn"}:
            raise reject(409, "此条反馈不可重新打开")
        row.status = "open"
        target = (
            await session.get(KnowledgeAsset, row.resolved_asset_id)
            if row.resolved_asset_id
            else asset
        )
        row.reported_updated_at = (target or asset).updated_at
        row.reported_fingerprint = await fingerprint(session, target or asset)
        await operation_events.publish_knowledge_trust(
            session,
            asset,
            await responsible_recipients(session, asset),
            "correction",
            str(row.id) + str(now),
        )
    else:
        permitted = (
            row.reporter_user_id == caller.user_id
            if req.action == "verify"
            else knowledge_manager_allowed(caller, asset)
        )
        if not permitted or row.status != "resolved":
            raise reject(409, "只有提出者可验证待验证的纠错")
        if req.action in {"verify", "close"}:
            target = await _load(session, caller, row.resolved_asset_id, write=True)
            if (await fingerprint(session, target)) != row.resolved_fingerprint:
                raise reject(409, "处理后的资料又有修改，请重新打开纠错并核查")
            if target.asset_status not in {"active", "needs_update"}:
                raise reject(409, "处理后的资料已停用，请重新核查")
            if target.id != (asset.replacement_asset_id or asset.id):
                raise reject(409, "新版关联已变化，请重新打开纠错并核查")
            row.status = "verified"
            if req.action == "close":
                await operation_events.publish_knowledge_trust(
                    session, asset, [row.reporter_user_id], "closed", str(row.id) + str(now)
                )
    row.updated_at = now
    await _audit(
        session,
        caller,
        asset,
        f"correction_{req.action}",
        trace_id,
        correction_id=str(row.id),
        reason=req.reason,
    )
    from app.services.maintenance_reconcile import reconcile_asset

    await session.flush()
    await reconcile_asset(session, asset)
    await session.commit()
    await enqueue_outbox_delivery(session)
    return await get_state(session, caller, asset_id)


async def scan_due_reviews(session, *, resume_only=False):
    """Publish one batch of due reminders with the original permission policy."""
    started = time.monotonic()
    run = await governance_scan.begin_cycle(session, "review", resume_only=resume_only)
    if run is None:
        return 0
    try:
        from app.models.maintenance_agent import MaintenancePolicy

        agent_scheduled = (
            select(MaintenancePolicy.id)
            .where(
                MaintenancePolicy.enabled.is_(True),
                or_(
                    and_(KnowledgeAsset.scope == "company", MaintenancePolicy.project_id.is_(None)),
                    and_(
                        KnowledgeAsset.scope == "project",
                        MaintenancePolicy.project_id == KnowledgeAsset.project_id,
                    ),
                ),
            )
            .exists()
        )
        conditions = (
            KnowledgeAsset.review_due_at <= run.cutoff_at,
            KnowledgeAsset.asset_status.in_(["active", "needs_update"]),
            ~agent_scheduled,
        )
        assets = await governance_scan.claim_assets(session, run, *conditions)
        candidates = await maintainer_contexts(session) if assets else []
        processed = []
        for asset in assets:
            if governance_scan.budget_exhausted(started, processed):
                break
            await operation_events.publish_knowledge_trust(
                session,
                asset,
                responsible_for(asset, candidates),
                "due",
                str(asset.review_due_at),
            )
            processed.append(asset.id)
        await governance_scan.finish_batch(session, run, processed, *conditions)
    except BaseException:
        await session.rollback()
        raise
    if processed:
        await enqueue_outbox_delivery(session)
    return len(processed)


async def list_maintenance(session, caller, *, page=1, page_size=25):
    """SQL-filtered manager tasks + caller's own resolved reports; no global counts."""
    if not caller.is_active or not caller.is_business_user:
        raise reject(403, "请使用有效业务身份")
    manager_projects = [
        pid
        for pid, role in caller.active_project_roles.items()
        if role == "project_manager" and pid in caller.active_project_ids
    ]
    asset = KnowledgeAsset
    managed = or_(
        and_(asset.scope == "personal", asset.owner_user_id == caller.user_id),
        and_(
            asset.scope == "company",
            or_(
                caller.can_discover_l5,
                and_(
                    asset.maintenance_delegated.is_(True),
                    asset.maintainer_user_id == caller.user_id,
                    asset.confidentiality_level != "L5",
                ),
            ),
        ),
        and_(
            asset.scope == "project",
            asset.project_id.in_(manager_projects),
            or_(asset.confidentiality_level != "L5", caller.can_discover_l5),
        ),
    )
    open_issue = (
        select(KnowledgeCorrection.id)
        .where(KnowledgeCorrection.asset_id == asset.id, KnowledgeCorrection.status == "open")
        .exists()
    )
    own_resolved = (
        select(KnowledgeCorrection.id)
        .where(
            KnowledgeCorrection.asset_id == asset.id,
            KnowledgeCorrection.reporter_user_id == caller.user_id,
            KnowledgeCorrection.status == "resolved",
        )
        .exists()
    )
    # Reports do not preserve access after role/membership/classification changes.
    from app.services.permission import discovery_filter

    report_visible = and_(own_resolved, discovery_filter(caller, include_inactive=True))
    from app.models.maintenance_agent import MaintenanceIssue
    from app.services.maintenance_access import visible_issue_query
    from app.services.maintenance_rules import SUGGESTIONS

    visible_issues = (
        visible_issue_query(caller)
        .where(
            MaintenanceIssue.status.in_(["open", "in_progress", "awaiting_recheck"]),
            MaintenanceIssue.rule.notin_(SUGGESTIONS),
        )
        .subquery()
    )
    agent_count = (
        select(func.count())
        .select_from(visible_issues)
        .where(visible_issues.c.asset_id == asset.id)
        .correlate(asset)
        .scalar_subquery()
    )
    attention = or_(
        asset.review_due_at <= utc_now(),
        asset.asset_status == "needs_update",
        open_issue,
        agent_count > 0,
    )
    filters = [
        asset.deleted_at.is_(None),
        or_(
            and_(managed, asset.asset_status.in_(["active", "needs_update"]), attention),
            report_visible,
        ),
    ]
    total = await session.scalar(select(func.count()).select_from(asset).where(*filters))
    rows = (
        await session.execute(
            select(
                asset,
                open_issue.label("open_issue"),
                own_resolved.label("own_resolved"),
                agent_count.label("agent_count"),
            )
            .where(*filters)
            .order_by(asset.updated_at.desc(), asset.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return MaintenancePage(
        items=[
            MaintenanceItem(
                asset_id=row.id,
                title=row.title,
                scope=row.scope,
                review_due_at=row.review_due_at,
                freshness=freshness(row),
                needs_correction=bool(open_ and can_manage(caller, row)),
                awaiting_my_verification=bool(own),
                agent_issue_count=count,
                library_key=f"project:{row.project_id}"
                if row.scope == "project"
                else "company"
                if row.scope == "company"
                else None,
            )
            for row, open_, own, count in rows
        ],
        total=total or 0,
        page=page,
        page_size=page_size,
    )
