"""Read bounded windows of a whole document. Limits apply to work, not eligibility."""

from hashlib import sha256

from sqlalchemy import func, select

from app.core.personal_information import PERSONAL_LOOKAHEAD
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
    privacy_summaries = sorted(
        (
            r
            for r in summaries
            if r[1]
            in {
                "detailed_summary",
                "detailed",
                "summary",
                "one_liner",
                "key_points",
                "redacted_summary",
                "redacted_one_liner",
                "safe_summary",
            }
        ),
        key=lambda r: (r[1], str(r[0])),
    )
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
    privacy = None
    if not work.get("privacy_done"):
        size = BODY_BATCH
        privacy = {"size": size, "summary_ranges": []}
        summary_position = 0
        for _, summary_type, length in privacy_summaries:
            privacy["summary_ranges"].append(
                {"type": summary_type, "start": summary_position, "end": summary_position + length}
            )
            summary_position += length + 1
        for source, model, source_layout in (
            ("body", KnowledgeAssetChunk, layout),
            ("summary", KnowledgeAssetSummary, [(r[0], r[2]) for r in privacy_summaries]),
        ):
            total = max(0, sum(length for _, length in source_layout) + len(source_layout) - 1)
            offset = work.get("privacy_" + source + "_offset", 0)
            privacy[source] = await text_window(
                session, model, source_layout, offset, size + PERSONAL_LOOKAHEAD
            )
            privacy[source + "_offset"] = offset
            privacy[source + "_next"] = min(total, offset + size)
            privacy[source + "_last"] = offset + size >= total
    return {
        "privacy": privacy,
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
        "signature": digest(
            [
                signature.hexdigest(),
                [[str(i), n] for i, n in summary_layout],
                [[str(i), kind, n] for i, kind, n in privacy_summaries],
            ]
        ),
        "inactive": has_inactive,
    }
