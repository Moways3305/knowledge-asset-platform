"""Indexed literal identifier recall, independent of semantic ranking.

This is deliberately not an unbounded general full-text fallback. PostgreSQL's
GIN index narrows ASCII identifier components; the complete literal is still
checked, including punctuation and any adjacent Chinese text. Only callers
allowed to read the original may gain a candidate from its private body.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re

from sqlalchemy import and_, func, literal, literal_column, or_, select, tuple_, union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.core.text_safety import CANONICAL_MARKDOWN_MAX_CHARS
from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetChunk,
    KnowledgeAssetFileObject,
    KnowledgeAssetVersion,
)
from app.schemas.permission import AccessChannel, AccessLayer, CallerContext
from app.services import original_access
from app.services.permission import DefaultAccessPolicy, decide
from app.services.storage import LocalFileStorage, StorageError, get_storage

_logger = logging.getLogger(__name__)
_PAGE_SIZE = 100
_MAX_MATCHING_ASSETS = 2000
_MAX_RESULTS = 100
_MAX_SOURCE_BYTES = CANONICAL_MARKDOWN_MAX_CHARS * 4
_SOURCE_READ_BUDGET = 32 * 1024 * 1024
_IDENTIFIER = re.compile(r"[\w]+(?:-[\w]+)*", re.UNICODE)


def literal_identifier(query: str) -> str | None:
    """Keep the complete user identifier; never use model-generated expansions."""
    value = query.strip()
    if not 6 <= len(value) <= 128 or not _IDENTIFIER.fullmatch(value):
        return None
    # Ordinary words, dates and short numbers retain the existing semantic path.
    if not re.search(r"[A-Za-z]", value) or not re.search(r"[0-9]", value):
        return None
    if re.search(r"[^A-Za-z0-9_-]", value) and not re.search(r"[-_]", value):
        # Chinese prose such as “本月L3制度” is a semantic query, not an
        # identifier whose complete literal must be present in permitted text.
        return None
    return value


def identifier_terms(value: str) -> str:
    # Keep this equivalent to the regexp_replace in migration 0081 and the ORM
    # expression index. Separating Chinese and ASCII also handles "编号BONUS".
    return " ".join(re.findall(r"[A-Za-z0-9]+", value))


def literal_in_text(value: str, text: str | None) -> bool:
    return (
        re.search(identifier_pattern(value), text or "", flags=re.IGNORECASE | re.ASCII) is not None
    )


def identifier_pattern(value: str) -> str:
    # Adjacent Chinese prose is allowed; matching the prefix of another ASCII
    # identifier (BONUS-NEW-18070) or a larger hyphenated identifier is not.
    return rf"(^|[^A-Za-z0-9_-]){re.escape(value)}([^A-Za-z0-9_-]|$)"


def identifier_vector(content=None):
    return func.to_tsvector(
        literal_column("'simple'::regconfig"),
        func.regexp_replace(
            KnowledgeAssetChunk.content_text if content is None else content,
            literal_column("'[^A-Za-z0-9]+'"),
            literal_column("' '"),
            literal_column("'g'"),
        ),
    )


def boundary_identifier_query(value: str) -> str:
    """Indexed fragments for an identifier cut at any character boundary.

    At each possible cut, at least one side contains half the ASCII content.
    Query only that longer side's complete lexemes, never every single-character
    prefix. Adjacent blocks only propose candidates: controlled current-version
    source bytes must prove continuity after the caller passes original access.
    """
    choices: set[tuple[str, ...]] = set()
    for cut in range(1, len(value)):
        sides = [tuple(re.findall(r"[A-Za-z0-9]+", part)) for part in (value[:cut], value[cut:])]
        terms = max(sides, key=lambda side: sum(map(len, side)))
        if terms:
            choices.add(tuple(term.lower() for term in terms))
    return " | ".join("(" + " & ".join(terms) + ")" for terms in sorted(choices))


def _boundary_matches(value: str, *, postgresql: bool, anchor_is_left: bool):
    anchor = aliased(KnowledgeAssetChunk)
    neighbor = aliased(KnowledgeAssetChunk)
    left, right = (anchor, neighbor) if anchor_is_left else (neighbor, anchor)
    joined_text = left.content_text + right.content_text
    statement = (
        select(anchor.asset_id, anchor.version_id, literal(0).label("single_chunk"))
        .join(
            neighbor,
            and_(
                neighbor.asset_id == anchor.asset_id,
                neighbor.version_id == anchor.version_id,
                right.chunk_index == left.chunk_index + 1,
            ),
        )
        .where(
            left.chunk_status.in_(("active", "pending_review")),
            right.chunk_status.in_(("active", "pending_review")),
            left.chunk_type == "governance_text",
            right.chunk_type == "governance_text",
            # Stripped chunk text cannot prove whether a boundary was a hard
            # cut or a real source newline. Keep this a candidate-only join.
            left.source_page.is_not_distinct_from(right.source_page),
            left.source_section.is_not_distinct_from(right.source_section),
            joined_text.icontains(value, autoescape=True),
            joined_text.regexp_match(identifier_pattern(value), flags="i")
            if postgresql
            else joined_text.regexp_match("(?i)" + identifier_pattern(value)),
        )
    )
    if postgresql:
        statement = statement.where(
            identifier_vector(anchor.content_text).bool_op("@@")(
                func.to_tsquery(
                    literal_column("'simple'::regconfig"), boundary_identifier_query(value)
                )
            )
        )
    return statement


def literal_body_statement(value: str, kb_ids: list[str], knowledge_ids, *, postgresql: bool):
    matching = select(
        KnowledgeAssetChunk.asset_id,
        KnowledgeAssetChunk.version_id,
        literal(1).label("single_chunk"),
    ).where(
        KnowledgeAssetChunk.chunk_status.in_(("active", "pending_review")),
        KnowledgeAssetChunk.content_text.icontains(value, autoescape=True),
        KnowledgeAssetChunk.content_text.regexp_match(identifier_pattern(value), flags="i")
        if postgresql
        else KnowledgeAssetChunk.content_text.regexp_match("(?i)" + identifier_pattern(value)),
    )
    if postgresql:
        matching = matching.where(
            identifier_vector().bool_op("@@")(
                func.plainto_tsquery(literal_column("'simple'::regconfig"), identifier_terms(value))
            )
        )
    candidates = union(
        matching,
        _boundary_matches(value, postgresql=postgresql, anchor_is_left=True),
        _boundary_matches(value, postgresql=postgresql, anchor_is_left=False),
    ).subquery()
    matched = (
        select(
            candidates.c.asset_id,
            candidates.c.version_id,
            func.max(candidates.c.single_chunk).label("single_chunk"),
        )
        .group_by(candidates.c.asset_id, candidates.c.version_id)
        .subquery()
    )
    statement = (
        select(KnowledgeAsset, KnowledgeAssetVersion, matched.c.single_chunk)
        .join(KnowledgeAssetVersion, KnowledgeAssetVersion.asset_id == KnowledgeAsset.id)
        .join(
            matched,
            and_(
                matched.c.asset_id == KnowledgeAsset.id,
                matched.c.version_id == KnowledgeAssetVersion.id,
            ),
        )
        .where(
            KnowledgeAsset.current_version_id == KnowledgeAssetVersion.id,
            KnowledgeAsset.asset_status == "active",
            KnowledgeAssetVersion.version_status == "active",
            KnowledgeAssetVersion.index_status == "indexed",
            KnowledgeAssetVersion.weknora_kb_id.in_(kb_ids),
            KnowledgeAssetVersion.weknora_doc_id.is_not(None),
            or_(
                KnowledgeAssetVersion.directory_key.is_(None),
                KnowledgeAssetVersion.directory_key != "personal.pending",
            ),
        )
        .options(selectinload(KnowledgeAsset.summaries), selectinload(KnowledgeAsset.tags))
        .order_by(KnowledgeAsset.id, KnowledgeAssetVersion.id)
    )
    if knowledge_ids is not None:
        statement = statement.where(KnowledgeAssetVersion.weknora_doc_id.in_(knowledge_ids))
    return statement


def _source_read_size(storage: LocalFileStorage, source: KnowledgeAssetFileObject) -> int | None:
    """Existing canonical objects may have no recorded size; stat, never repair."""
    if not source.file_hash:
        return None
    if source.file_size is not None and not 0 < source.file_size <= _MAX_SOURCE_BYTES:
        return None
    try:
        size = storage.resolve_path(source.storage_ref).stat().st_size
    except (OSError, StorageError, ValueError):
        return None
    if not 0 < size <= _MAX_SOURCE_BYTES:
        return None
    if source.file_size is not None and size != source.file_size:
        return None
    return size


def _source_contains_literal(
    storage: LocalFileStorage, source: KnowledgeAssetFileObject, value: str, size: int
) -> bool:
    """Read an already selected, bounded canonical file without backfilling it."""
    try:
        with storage.resolve_path(source.storage_ref).open("rb") as stream:
            content = stream.read(size + 1)
        if len(content) != size:
            return False
        if hashlib.sha256(content).hexdigest() != source.file_hash:
            return False
        return literal_in_text(value, content.decode("utf-8"))
    except (OSError, StorageError, UnicodeDecodeError, ValueError):
        return False


async def recall_literal_body(
    session: AsyncSession,
    caller: CallerContext,
    *,
    query: str,
    kb_ids: list[str],
    knowledge_ids: list[str] | None,
    channel: AccessChannel,
    policy: DefaultAccessPolicy,
) -> list[tuple[KnowledgeAsset, KnowledgeAssetVersion]]:
    value = literal_identifier(query)
    if value is None or not kb_ids or knowledge_ids == []:
        return []
    dialect = session.get_bind().dialect.name
    # SQLite is the isolated test database; PostgreSQL always uses the GIN path.
    if dialect not in {"postgresql", "sqlite"}:
        return []
    statement = literal_body_statement(
        value, kb_ids, knowledge_ids, postgresql=dialect == "postgresql"
    )
    matches: list[tuple[KnowledgeAsset, KnowledgeAssetVersion]] = []
    seen = set()
    scanned = 0
    source_budget = _SOURCE_READ_BUDGET
    source_budget_exhausted = False
    while len(matches) < _MAX_RESULTS and scanned < _MAX_MATCHING_ASSETS:
        rows = (await session.execute(statement.limit(_PAGE_SIZE).offset(scanned))).all()
        if not rows:
            break
        scanned += len(rows)
        grants = await original_access.active_grant_asset_ids(
            session, caller, (asset.id for asset, _, _ in rows)
        )
        allowed = []
        for asset, version, single_chunk in rows:
            if asset.id in seen:
                continue
            seen.add(asset.id)
            if not decide(
                caller, asset, AccessLayer.discovery, channel=channel, policy=policy
            ).allowed:
                continue
            if not decide(
                caller,
                asset,
                AccessLayer.original,
                channel=channel,
                has_original_grant=asset.id in grants,
                policy=policy,
            ).allowed:
                continue
            allowed.append((asset, version, single_chunk))
        boundary_pairs = [
            (asset.id, version.id) for asset, version, single in allowed if not single
        ]
        # One bounded batch per candidate page; never look up or read sources
        # for callers with only discovery/summary permission.
        sources = {}
        if boundary_pairs:
            sources = {
                (source.asset_id, source.version_id): source
                for source in (
                    await session.scalars(
                        select(KnowledgeAssetFileObject).where(
                            KnowledgeAssetFileObject.file_variant == "canonical_markdown",
                            tuple_(
                                KnowledgeAssetFileObject.asset_id,
                                KnowledgeAssetFileObject.version_id,
                            ).in_(boundary_pairs),
                        )
                    )
                ).all()
            }
        storage = get_storage() if sources else None
        for asset, version, single_chunk in allowed:
            if not single_chunk:
                source = sources.get((asset.id, version.id))
                if source is None or storage is None:
                    continue
                size = await asyncio.to_thread(_source_read_size, storage, source)
                if size is None:
                    continue
                # Reserve the maximum read, including one byte for size drift.
                # Failed/missing/corrupt files cannot evade the total IO bound.
                read_limit = size + 1
                if read_limit > source_budget:
                    source_budget_exhausted = True
                    continue
                source_budget -= read_limit
                if not await asyncio.to_thread(
                    _source_contains_literal, storage, source, value, size
                ):
                    continue
            matches.append((asset, version))
            if len(matches) == _MAX_RESULTS:
                break
        if len(rows) < _PAGE_SIZE:
            break
    if scanned >= _MAX_MATCHING_ASSETS and len(matches) < _MAX_RESULTS:
        # The bound applies to actual literal matches, not arbitrary catalogue
        # rows. Never log the identifier, matching body, user or document IDs.
        _logger.warning("retrieval_literal_match_budget_exhausted", extra={"scanned_rows": scanned})
    if source_budget_exhausted:
        _logger.warning("retrieval_literal_source_budget_exhausted")
    return matches
