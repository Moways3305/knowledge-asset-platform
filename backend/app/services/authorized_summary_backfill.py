"""Idempotent backfill for complete L3/L4 authorized summaries."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeAsset, KnowledgeAssetSummary
from app.services.authorized_summary import build_authorized_summary_variants
from app.services.desensitization import DesensitizationEngine, RuleBasedDesensitizer

_REDACTED_LEVELS = {"L3", "L4"}
_PENDING_TYPE = "redacted_summary_pending"
_PENDING_SOURCE_MISSING = "source_summary_missing"
_PENDING_REDACTION_FAILED = "redaction_failed"


@dataclass(frozen=True)
class BackfillEvidence:
    """Content-free length evidence for one representative asset."""

    outcome: str
    confidentiality_level: str
    before_one_liner_length: int | None
    after_one_liner_length: int | None
    before_detailed_length: int | None
    after_detailed_length: int | None


@dataclass(frozen=True)
class AuthorizedSummaryBackfillReport:
    dry_run: bool
    scanned: int = 0
    regenerated: int = 0
    unchanged: int = 0
    pending: int = 0
    created_rows: int = 0
    updated_rows: int = 0
    cleared_pending_markers: int = 0
    evidence: list[BackfillEvidence] = field(default_factory=list)


def _length(value: str | None) -> int | None:
    return len(value) if value is not None else None


async def backfill_authorized_summaries(
    session: AsyncSession,
    *,
    dry_run: bool = True,
    desensitizer: DesensitizationEngine | None = None,
) -> AuthorizedSummaryBackfillReport:
    """Regenerate current L3/L4 safe summaries without exposing source content.

    Missing ordinary detailed summaries are not fabricated. They receive a persistent, non-content
    pending marker when applying the backfill, so a later repair can be retried safely.
    """
    engine = desensitizer or RuleBasedDesensitizer()
    rows = (
        await session.execute(
            select(
                KnowledgeAsset.id,
                KnowledgeAsset.confidentiality_level,
                KnowledgeAsset.current_version_id,
                KnowledgeAssetSummary,
            )
            .outerjoin(
                KnowledgeAssetSummary,
                and_(
                    KnowledgeAssetSummary.asset_id == KnowledgeAsset.id,
                    KnowledgeAssetSummary.version_id == KnowledgeAsset.current_version_id,
                ),
            )
            .where(KnowledgeAsset.confidentiality_level.in_(_REDACTED_LEVELS))
            .order_by(KnowledgeAsset.id, KnowledgeAssetSummary.summary_type)
        )
    ).all()

    grouped: dict[
        uuid.UUID,
        tuple[uuid.UUID, str, uuid.UUID | None, dict[str, KnowledgeAssetSummary]],
    ] = {}
    for asset_id, level, version_id, summary in rows:
        if asset_id not in grouped:
            grouped[asset_id] = (asset_id, level, version_id, {})
        if summary is not None:
            grouped[asset_id][3][summary.summary_type] = summary

    regenerated = unchanged = pending = created_rows = updated_rows = cleared = 0
    evidence: list[BackfillEvidence] = []

    for asset_id, level, version_id, summaries in grouped.values():
        ordinary_detailed = summaries.get("detailed")
        ordinary_one_liner = summaries.get("one_liner")
        current_short = summaries.get("redacted_one_liner")
        current_detailed = summaries.get("redacted_summary")
        pending_marker = summaries.get(_PENDING_TYPE)

        if ordinary_detailed is None or not (ordinary_detailed.content or "").strip():
            pending += 1
            if version_id is not None and pending_marker is None:
                created_rows += 1
                if not dry_run:
                    session.add(
                        KnowledgeAssetSummary(
                            asset_id=asset_id,
                            version_id=version_id,
                            summary_type=_PENDING_TYPE,
                            content=_PENDING_SOURCE_MISSING,
                        )
                    )
            if not evidence:
                evidence.append(
                    BackfillEvidence(
                        outcome="pending_source_summary",
                        confidentiality_level=level,
                        before_one_liner_length=_length(
                            current_short.content if current_short else None
                        ),
                        after_one_liner_length=None,
                        before_detailed_length=_length(
                            current_detailed.content if current_detailed else None
                        ),
                        after_detailed_length=None,
                    )
                )
            continue

        desired_short, desired_detailed = build_authorized_summary_variants(
            one_liner=ordinary_one_liner.content if ordinary_one_liner else None,
            detailed=ordinary_detailed.content or "",
            desensitizer=engine,
        )
        if desired_short is None or desired_detailed is None:
            pending += 1
            marker_changed = (
                pending_marker is None or pending_marker.content != _PENDING_REDACTION_FAILED
            )
            if marker_changed:
                if pending_marker is None:
                    created_rows += 1
                    if not dry_run:
                        session.add(
                            KnowledgeAssetSummary(
                                asset_id=ordinary_detailed.asset_id,
                                version_id=version_id,
                                summary_type=_PENDING_TYPE,
                                content=_PENDING_REDACTION_FAILED,
                            )
                        )
                else:
                    updated_rows += 1
                    if not dry_run:
                        pending_marker.content = _PENDING_REDACTION_FAILED
            continue

        before_short_length = _length(current_short.content if current_short else None)
        before_detailed_length = _length(current_detailed.content if current_detailed else None)
        asset_changed = False
        for existing, summary_type, desired in (
            (current_short, "redacted_one_liner", desired_short),
            (current_detailed, "redacted_summary", desired_detailed),
        ):
            if existing is None:
                asset_changed = True
                created_rows += 1
                if not dry_run:
                    session.add(
                        KnowledgeAssetSummary(
                            asset_id=ordinary_detailed.asset_id,
                            version_id=version_id,
                            summary_type=summary_type,
                            content=desired,
                        )
                    )
            elif existing.content != desired:
                asset_changed = True
                updated_rows += 1
                if not dry_run:
                    existing.content = desired

        if pending_marker is not None:
            asset_changed = True
            cleared += 1
            if not dry_run:
                await session.delete(pending_marker)

        if asset_changed:
            regenerated += 1
        else:
            unchanged += 1
        if not evidence:
            evidence.append(
                BackfillEvidence(
                    outcome="regenerated" if asset_changed else "unchanged",
                    confidentiality_level=level,
                    before_one_liner_length=before_short_length,
                    after_one_liner_length=len(desired_short),
                    before_detailed_length=before_detailed_length,
                    after_detailed_length=len(desired_detailed),
                )
            )

    if not dry_run:
        await session.commit()

    return AuthorizedSummaryBackfillReport(
        dry_run=dry_run,
        scanned=len(grouped),
        regenerated=regenerated,
        unchanged=unchanged,
        pending=pending,
        created_rows=created_rows,
        updated_rows=updated_rows,
        cleared_pending_markers=cleared,
        evidence=evidence,
    )
