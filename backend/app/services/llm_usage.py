"""Persist and aggregate safe LLM usage counters."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_usage import LLMUsageEvent
from app.services.llm_client import PROVIDER_REGISTRY

if TYPE_CHECKING:
    from app.services.llm_client import LLMUsage

SCENARIOS = {"content_generation", "category_classification"}
CACHE_STATUSES = {"hit", "miss", "not_applicable"}
OUTCOMES = {"success", "failure", "degraded", "cache_hit"}


def safe_provider(provider: str | None) -> str:
    value = (provider or "").strip().lower()
    return value if value in PROVIDER_REGISTRY else "custom"


def safe_model_ref(provider: str | None, model: str | None) -> str:
    material = f"{safe_provider(provider)}:{(model or '').strip()}".encode()
    return hashlib.sha256(material).hexdigest()[:24]


def cache_fingerprint(
    *,
    content_hash: str,
    scope: str,
    project_id: str | None,
    rule_revision: int,
    provider: str,
    model: str,
) -> str:
    material = "\n".join(
        [content_hash, scope, project_id or "", str(rule_revision), safe_provider(provider), model]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def candidate_fingerprint(category_ids: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(category_ids)).encode()).hexdigest()


def _counter(value: int | None) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


async def record(
    session: AsyncSession,
    *,
    scenario: str,
    provider: str | None,
    model: str | None,
    batch_size: int,
    cache_status: str,
    outcome: str,
    usage: LLMUsage | dict | None = None,
) -> None:
    if scenario not in SCENARIOS or cache_status not in CACHE_STATUSES or outcome not in OUTCOMES:
        raise ValueError("invalid llm usage enum")
    values = usage if isinstance(usage, dict) else vars(usage) if usage is not None else {}
    session.add(
        LLMUsageEvent(
            scenario=scenario,
            provider=safe_provider(provider),
            model_ref=safe_model_ref(provider, model),
            batch_size=max(1, int(batch_size)),
            cache_status=cache_status,
            prompt_tokens=_counter(values.get("prompt_tokens")),
            completion_tokens=_counter(values.get("completion_tokens")),
            total_tokens=_counter(values.get("total_tokens")),
            outcome=outcome,
        )
    )


async def aggregate(session: AsyncSession, *, days: int) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 90)) - 1)
    day = func.date(LLMUsageEvent.created_at)
    rows = (
        await session.execute(
            select(
                day.label("day"),
                LLMUsageEvent.scenario,
                func.sum(case((LLMUsageEvent.cache_status == "miss", 1), else_=0)).label(
                    "request_count"
                ),
                func.sum(LLMUsageEvent.batch_size).label("item_count"),
                func.coalesce(func.sum(LLMUsageEvent.prompt_tokens), 0).label("prompt_tokens"),
                func.coalesce(func.sum(LLMUsageEvent.completion_tokens), 0).label(
                    "completion_tokens"
                ),
                func.coalesce(func.sum(LLMUsageEvent.total_tokens), 0).label("total_tokens"),
                func.sum(case((LLMUsageEvent.cache_status == "hit", 1), else_=0)).label("hits"),
                func.sum(case((LLMUsageEvent.cache_status == "miss", 1), else_=0)).label("misses"),
            )
            .where(LLMUsageEvent.created_at >= since)
            .group_by(day, LLMUsageEvent.scenario)
            .order_by(day, LLMUsageEvent.scenario)
        )
    ).all()
    return [
        {
            "day": str(row.day),
            "scenario": row.scenario,
            "request_count": int(row.request_count or 0),
            "item_count": int(row.item_count or 0),
            "prompt_tokens": int(row.prompt_tokens or 0),
            "completion_tokens": int(row.completion_tokens or 0),
            "total_tokens": int(row.total_tokens or 0),
            "cache_hits": int(row.hits or 0),
            "cache_misses": int(row.misses or 0),
            "cache_hit_rate": (
                int(row.hits or 0) / (int(row.hits or 0) + int(row.misses or 0))
                if int(row.hits or 0) + int(row.misses or 0)
                else 0.0
            ),
        }
        for row in rows
    ]
