"""Read bounded windows of a whole document. Limits apply to work, not eligibility."""

from hashlib import sha256

from sqlalchemy import func, select

from app.models.knowledge import KnowledgeAssetChunk, KnowledgeAssetSummary
from app.services.maintenance_rules import digest

BODY_BATCH = 6000
SUMMARY_BATCH = 2500
OVERLAP = 250


async def text_window(session, model, layout, start, size):
    """Virtual newline-joined text; SQL substr never loads an oversized chunk."""
    parts, position = [], 0
    stop = start + size
    for identity, length in layout:
        if position and start <= position - 1 < stop:
            parts.append("\n")
        begin, end = max(start, position), min(stop, position + length)
        if begin < end:
            column = model.content_text if model is KnowledgeAssetChunk else model.content
            parts.append(
                await session.scalar(
                    select(func.substr(column, begin - position + 1, end - begin)).where(
                        model.id == identity
                    )
                )
                or ""
            )
        position += length + 1
        if position - 1 >= stop:
            break
    return "".join(parts)


async def capture_windows(session, asset, version, settings, work):
    chunk_query = (
        select(
            KnowledgeAssetChunk.id,
            KnowledgeAssetChunk.chunk_index,
            func.length(KnowledgeAssetChunk.content_text),
            KnowledgeAssetChunk.chunk_hash,
            KnowledgeAssetChunk.chunk_status,
        )
        .where(
            KnowledgeAssetChunk.asset_id == asset.id,
            KnowledgeAssetChunk.version_id == version.id,
        )
        .order_by(KnowledgeAssetChunk.chunk_index)
    )
    layout, cursor, has_inactive = [], None, False
    signature = sha256()
    while True:
        query = (
            chunk_query.where(KnowledgeAssetChunk.chunk_index > cursor)
            if cursor is not None
            else chunk_query
        )
        rows = (await session.execute(query.limit(500))).all()
        if not rows:
            break
        for identity, index, length, chunk_hash, status in rows:
            signature.update(digest([str(identity), index, length, chunk_hash, status]).encode())
            if status == "active":
                layout.append((identity, length or 0))
            else:
                has_inactive = True
        cursor = rows[-1][1]
    # Prefer one authoritative summary instead of concatenating original and redacted copies.
    summaries = (
        await session.execute(
            select(
                KnowledgeAssetSummary.id,
                KnowledgeAssetSummary.summary_type,
                func.length(KnowledgeAssetSummary.content),
            ).where(
                KnowledgeAssetSummary.asset_id == asset.id,
                KnowledgeAssetSummary.version_id == version.id,
                func.length(KnowledgeAssetSummary.content) > 0,
            )
        )
    ).all()
    priority = [
        "detailed_summary",
        "detailed",
        "summary",
        "one_liner",
        "redacted_summary",
        "safe_summary",
    ]
    summaries = sorted(
        (r for r in summaries if r[1] in priority), key=lambda r: priority.index(r[1])
    )[:1]
    summary_layout = [(r[0], r[2]) for r in summaries]
    body_total = max(0, sum(length for _, length in layout) + len(layout) - 1)
    summary_total = sum(length for _, length in summary_layout)
    start, summary_start = work.get("body_offset", 0), work.get("summary_offset", 0)
    body = await text_window(
        session, KnowledgeAssetChunk, layout, start, min(BODY_BATCH, settings.max_body_chars)
    )
    summary = await text_window(
        session, KnowledgeAssetSummary, summary_layout, summary_start, SUMMARY_BATCH
    )
    body_end, summary_end = start + len(body), summary_start + len(summary)
    body_last, summary_last = body_end >= body_total, summary_end >= summary_total
    partial = start > 0 or not body_last or summary_start > 0 or not summary_last
    return {
        "body": body,
        "summary": summary,
        "body_total": body_total,
        "summary_total": summary_total,
        "body_offset": start,
        "body_end": body_end,
        "summary_end": summary_end,
        "body_last": body_last,
        "summary_last": summary_last,
        "partial": partial,
        "next_body": body_end if body_last else max(start + 1, body_end - OVERLAP),
        "next_summary": summary_end
        if summary_last
        else max(summary_start + 1, summary_end - OVERLAP),
        "signature": digest([signature.hexdigest(), [[str(i), n] for i, n in summary_layout]]),
        "inactive": has_inactive,
    }
