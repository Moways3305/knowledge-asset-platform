"""Governance projections deliberately separate from ordinary discovery/RAG.

Archived material stays invisible to ordinary readers. Company governance roles
can inspect safe summaries here and restore through the existing audited commands.
Candidate signals are heuristics, never automatic deletion instructions.
"""

import re
from collections import Counter
from datetime import timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.utils import utc_now
from app.models.knowledge import KnowledgeAsset
from app.schemas.governance import (
    GovernanceBatchResult,
    GovernanceItem,
    GovernanceOutcome,
    GovernancePage,
)
from app.schemas.lifecycle import ArchiveConfirmBody, ReenableConfirmBody
from app.services import audit, lifecycle
from app.services.knowledge_projection import _select_summary_text, _summary_map
from app.services.permission import lifecycle_actor_allowed, lifecycle_visibility

STATUSES = {"active", "needs_update", "deprecated", "archived"}
REASONS = {
    "historical": "历史参考",
    "superseded": "新版替代",
    "duplicate": "重复资料",
    "low_value": "低价值内容",
    "other": "其他",
}


def require_governor(caller):
    if not caller.is_active or not caller.is_business_user or not caller.can_discover_l5:
        raise HTTPException(403, detail={"message": "仅总经理或咨询总监可管理公司知识生命周期"})


def normalized_title(title):
    return re.sub(r"[\s_（）()【】\[\]，,。.-]+", "", title).casefold()


def candidate_signals(asset, summary, title_counts):
    text = asset.title + " " + (summary or "")
    result = []
    if title_counts[normalized_title(asset.title)] > 1:
        result.append("same_title")
    if re.search(r"草稿|讨论稿|未经讨论|初稿|修改稿|征求意见", asset.title):
        result.append("draft")
    years = [int(y) for y in re.findall(r"(?:19|20)\d{2}", text)]
    if any(y <= utc_now().year - 5 for y in years):
        if re.search(r"法律|法规|条例|办法|监管|政策|准则|指引", text):
            result.append("policy_age")
        elif re.search(r"年报|月报|周报|研究|市场|预测|展望|数据", text):
            result.append("research_age")
    if re.search(r"正文.{0,5}(缺失|为空)|仅含标题|仅包含标题|课件封面|推广介绍页", text):
        result.append("content_check")
    if asset.asset_status == "needs_update":
        result.append("needs_update")
    return result


async def list_company(
    session, caller, *, view="candidates", signal=None, keyword="", page=1, page_size=25
):
    require_governor(caller)
    assets = list(
        (
            await session.scalars(
                select(KnowledgeAsset)
                .where(KnowledgeAsset.scope == "company", KnowledgeAsset.asset_status.in_(STATUSES))
                .options(selectinload(KnowledgeAsset.summaries))
                .order_by(KnowledgeAsset.updated_at.desc(), KnowledgeAsset.id)
            )
        ).all()
    )
    assets = [
        a
        for a in assets
        if lifecycle_visibility(caller, a) is None and lifecycle_actor_allowed(caller, a)
    ]
    title_counts = Counter(
        normalized_title(a.title) for a in assets if a.asset_status != "archived"
    )
    rows = []
    counts = {"all": 0, "candidates": 0, "archived": 0}
    for a in assets:
        summary = _select_summary_text(a.confidentiality_level, _summary_map(a))
        signals = candidate_signals(a, summary, title_counts)
        archived = a.asset_status == "archived"
        counts["archived" if archived else "all"] += 1
        if signals and not archived:
            counts["candidates"] += 1
        if view == "archived" and not archived or view != "archived" and archived:
            continue
        if view == "candidates" and not signals:
            continue
        if signal and signal not in signals:
            continue
        if (
            keyword
            and keyword.casefold()
            not in (a.title + " " + str(a.id) + " " + (summary or "")).casefold()
        ):
            continue
        rows.append(
            GovernanceItem(
                asset_id=a.id,
                title=a.title,
                asset_status=a.asset_status,
                confidentiality_level=a.confidentiality_level,
                summary=summary,
                updated_at=a.updated_at,
                archived_at=a.archived_at,
                archive_reason=audit.sanitize_text(a.archive_reason) if a.archive_reason else None,
                signals=signals,
            )
        )
    return GovernancePage(
        items=rows[(page - 1) * page_size : page * page_size],
        total=len(rows),
        page=page,
        page_size=page_size,
        counts=counts,
    )


def _stamp(value):
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


async def _company_asset(session, caller, asset_id):
    asset = await session.scalar(
        select(KnowledgeAsset)
        .where(KnowledgeAsset.id == asset_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        asset is None
        or asset.scope != "company"
        or asset.asset_status not in STATUSES
        or lifecycle_visibility(caller, asset) is not None
        or not lifecycle_actor_allowed(caller, asset)
    ):
        raise HTTPException(404, detail={"message": "公司知识不存在或不可管理"})
    return asset


async def apply_batch(session, caller, body, trace_id):
    require_governor(caller)
    if (
        body.action == "archive"
        and body.reason_code == "superseded"
        and body.replacement_asset_id is None
    ):
        raise HTTPException(422, detail={"message": "新版替代须填写替代资产ID"})
    if body.replacement_asset_id in {i.asset_id for i in body.items}:
        raise HTTPException(422, detail={"message": "替代资料不能包含在本批归档清单中"})
    results = []
    # Per-item transactions intentionally report partial success. A stale selection
    # is never overwritten, including an ABA status change (updated_at checked).
    for item in body.items:
        try:
            asset = await _company_asset(session, caller, item.asset_id)
            if asset.asset_status != item.expected_status or _stamp(asset.updated_at) != _stamp(
                item.expected_updated_at
            ):
                raise HTTPException(409, detail={"message": "资料已变更，请刷新后重新核验"})
            reason = f"[{REASONS[body.reason_code]}] {body.reason}"
            if body.action == "archive":
                if body.replacement_asset_id:
                    replacement = await _company_asset(session, caller, body.replacement_asset_id)
                    if replacement.asset_status != "active":
                        raise HTTPException(409, detail={"message": "替代资料须为有效的公司知识"})
                    reason += f"\n替代资产ID: {replacement.id}"
                await lifecycle.archive_confirm(
                    session, caller, item.asset_id, ArchiveConfirmBody(reason=reason), trace_id
                )
            else:
                await lifecycle.reenable_confirm(
                    session,
                    caller,
                    item.asset_id,
                    ReenableConfirmBody(reason=reason, target_status="active"),
                    trace_id,
                )
            results.append(
                GovernanceOutcome(
                    asset_id=item.asset_id,
                    success=True,
                    message="已归档" if body.action == "archive" else "已恢复",
                )
            )
        except HTTPException as exc:
            await session.rollback()
            message = (
                exc.detail.get("message", "操作未完成")
                if isinstance(exc.detail, dict)
                else "操作未完成"
            )
            results.append(
                GovernanceOutcome(asset_id=item.asset_id, success=False, message=message)
            )
    return GovernanceBatchResult(items=results)
