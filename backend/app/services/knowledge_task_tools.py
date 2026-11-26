"""Read-only knowledge tools. The planner sees match statistics and tool outcomes only."""

import re
import uuid

from fastapi import HTTPException
from sqlalchemy import case, or_, select

from app.core.personal_information import redact_personal_information as redact
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.knowledge_correction import KnowledgeCorrection
from app.schemas.knowledge_task import SourceLink, TaskEvidence
from app.services import knowledge, knowledge_versions
from app.services.knowledge_catalog import keyword_filter
from app.services.maintenance_access import parse_key, scope_filter
from app.services.permission import discovery_filter

# Split conversational requests into catalogue phrases. Keep arbitrary client names,
# industries, English terms and quoted titles; don't restrict search to sample tasks.
_REQUEST_WORDS = re.compile(
    r"【[^】]*】|帮我|麻烦|请问|给我|找一下|找到|查找|搜索|找一份|找个|找份|找|一份|一套|一个|"
    r"适合|适用于|用于|关于|相关的?|客户|有没有|是否有|最新版?|新版|版本|"
    r"明天|今天|可以用|能用|可用|看看|看一下|帮忙|核对|对比|比较|推荐|的|，|。"
)


def phrases(instruction):
    pieces = re.findall(
        r"[a-z0-9][a-z0-9._+-]*|[\u3400-\u9fff]+", _REQUEST_WORDS.sub(" ", instruction.lower())
    )
    return list(
        dict.fromkeys(
            p[:50]
            for p in pieces
            if len(p) >= 2 and p not in {"资料", "知识库", "公司", "更新", "一下"}
        )
    )[:8]


def match_evidence(detail, terms):
    """Use the same live summary projection the caller may open in the library."""
    metadata = " ".join([detail.title, *detail.tags]).casefold()
    names = [t for t in terms if t in metadata]
    summary = (detail.summary.detailed or detail.summary.one_liner or "") if detail.summary else ""
    positions = [(t, summary.lower().find(t)) for t in terms if t not in names]
    from_summary = [t for t, pos in positions if pos >= 0]
    start = max(0, min((pos for _, pos in positions if pos >= 0), default=0) - 55)
    excerpt = ("…" if start else "") + summary[start : start + 400] if summary else None
    return names, from_summary, excerpt


async def search(session, caller, key, instruction):
    terms = phrases(instruction)
    if not terms:
        return []
    filters = [keyword_filter(term) for term in terms]
    document_terms = [
        f
        for t, f in zip(terms, filters, strict=True)
        if t.endswith(("提纲", "模板", "清单", "报告", "手册", "问卷", "指引", "方案", "流程图"))
    ]
    coverage = sum(case((predicate, 1), else_=0) for predicate in filters)
    # Rank across the whole scoped library before applying the per-task shortlist.
    query = (
        select(KnowledgeAsset.id)
        .where(
            scope_filter(parse_key(key)),
            discovery_filter(caller),
            or_(*(document_terms or filters)),
        )
        .order_by(coverage.desc(), KnowledgeAsset.updated_at.desc(), KnowledgeAsset.id)
        .limit(8)
    )
    ranked = []
    for asset_id in await session.scalars(query):
        try:
            item = await knowledge.get_detail(session, caller, asset_id)
        except HTTPException as exc:
            if exc.status_code in {403, 404}:
                continue
            raise
        names, from_summary, _ = match_evidence(item, terms)
        hits = [i for i, t in enumerate(terms) if t in names or t in from_summary]
        if not hits:
            continue
        ranked.append(
            (
                asset_id,
                {
                    "matched_slots": hits,
                    "requested_slots": len(terms),
                    "title_hits": sum(t in item.title.casefold() for t in names),
                    "summary_hits": len(from_summary),
                    "original": item.access_info.original,
                    "needs_update": item.asset_status == "needs_update",
                },
            )
        )
    ranked.sort(
        key=lambda x: (len(x[1]["matched_slots"]), x[1]["title_hits"], x[1]["original"]),
        reverse=True,
    )
    return ranked[:5]


async def inspect(session, caller, key, asset_id):
    """Follow only visible, adopted links within the delegated library."""
    project = parse_key(key)
    try:
        source = await session.get(KnowledgeAsset, asset_id)
        if (
            not source
            or source.scope != ("project" if project else "company")
            or source.project_id != project
        ):
            return None
        # History authorizes the source (including a visible adopted predecessor).
        state = await knowledge_versions.history(session, caller, asset_id)
        current = next(
            (v for v in state["items"] if v["is_current"] and v["version_status"] == "active"), None
        )
        if not current:
            return None
        detail = await knowledge.get_detail(session, caller, uuid.UUID(current["asset_id"]))
        if (
            detail.scope != source.scope
            or detail.project_id != project
            or not detail.current_version
        ):
            return None
        if str(detail.current_version.id) != current["version_id"] or detail.asset_status not in {
            "active",
            "needs_update",
        }:
            return None
        return detail, current, state
    except HTTPException as exc:
        if exc.status_code in {403, 404}:
            return None
        raise


async def evidence(session, caller, key, selected, instruction):
    checked = await inspect(session, caller, key, uuid.UUID(selected["asset_id"]))
    if not checked:
        return "unavailable", None
    detail, current, state = checked
    changed = current["version_id"] != selected["version_id"]
    terms = phrases(instruction)
    names, from_summary, summary = match_evidence(detail, terms)
    if changed and not (names or from_summary):
        return "changed", None
    version = await session.get(KnowledgeAssetVersion, detail.current_version.id)
    # Use the declared predecessor or a directly replaced asset. Creation order alone
    # cannot distinguish an adopted predecessor from an unapproved newer candidate.
    old_ids = set(
        await session.scalars(
            select(KnowledgeAsset.current_version_id).where(
                KnowledgeAsset.replacement_asset_id == detail.id,
                KnowledgeAsset.scope == detail.scope,
                KnowledgeAsset.project_id == detail.project_id,
            )
        )
    )
    previous = next(
        (
            v
            for v in state["items"]
            if v["asset_id"] == str(detail.id)
            and v["version_id"] == str(version.supersedes_version_id)
        ),
        None,
    )
    if not previous:
        previous = next((v for v in state["items"] if uuid.UUID(v["version_id"]) in old_ids), None)
    diff = (
        await knowledge_versions.compare(
            session, caller, detail.id, uuid.UUID(previous["version_id"]), version.id
        )
        if previous
        else None
    )
    # A source link is attributable to an old asset only for an adopted replacement.
    # Same-asset version upgrades do not record which version a copy used.
    old_sources = {
        uuid.UUID(v["asset_id"]) for v in state["items"] if uuid.UUID(v["version_id"]) in old_ids
    }
    links = []
    if old_sources:
        copies = await session.execute(
            select(KnowledgeAsset.id, KnowledgeAsset.title)
            .where(
                KnowledgeAsset.source_asset_id.in_(old_sources),
                KnowledgeAsset.id != detail.id,
                discovery_filter(caller),
                scope_filter(parse_key(key)),
            )
            .order_by(KnowledgeAsset.updated_at.desc(), KnowledgeAsset.id)
            .limit(10)
        )
        links = [SourceLink(asset_id=id_, title=redact(title)) for id_, title in copies]
    correction = await session.scalar(
        select(KnowledgeCorrection.status)
        .where(
            KnowledgeCorrection.asset_id.in_(
                [
                    uuid.UUID(v["asset_id"])
                    for v in state["items"]
                    if v["asset_id"] in {str(detail.id), selected["asset_id"]}
                ]
            ),
            KnowledgeCorrection.reporter_user_id == caller.user_id,
        )
        .order_by(KnowledgeCorrection.created_at.desc(), KnowledgeCorrection.id)
        .limit(1)
    )
    pending = any(
        u["can_replace"]
        or u["status"] in {"queued", "processing", "waiting_review", "awaiting_confirmation"}
        for u in state["updates"]
    )
    if not pending:
        for v in state["items"]:
            if (
                v["asset_id"] != str(detail.id)
                and v["status"] == "active"
                and v["version_status"] == "active"
                and await knowledge_versions.pending_adoption(session, uuid.UUID(v["asset_id"]))
            ):
                pending = True
                break
    return "changed" if changed else "available", TaskEvidence(
        asset_id=detail.id,
        version_id=version.id,
        version=redact(current["version"]),
        title=redact(detail.title),
        summary=redact(summary)[:400] if summary else None,
        original=detail.access_info.original,
        needs_update=detail.asset_status == "needs_update",
        matched=names,
        summary_matched=from_summary,
        unmatched=[t for t in terms if t not in names and t not in from_summary],
        old_source_links=links,
        pending_update=pending,
        parsed=detail.weknora_parse_status == "completed" or detail.index_status == "indexed",
        correction_status=correction,
        history_truncated=state["truncated"],
        compared_version=redact(previous["version"]) if previous else None,
        changed_fields=diff["changed_fields"] if diff else [],
        previous_summary=diff["left"]["summary"][:500]
        if diff and diff["left"]["summary"]
        else None,
        current_summary=diff["right"]["summary"][:500]
        if diff and diff["right"]["summary"]
        else None,
        updated_at=detail.updated_at,
    )
