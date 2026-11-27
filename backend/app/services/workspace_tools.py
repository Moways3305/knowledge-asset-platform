"""Permission-aware, read-only knowledge adapter for the generic workspace.

Only the caller's live summary projection reaches a model. Originals, maintenance
rules and mutation tools are intentionally outside this adapter's authority.
"""

import hashlib
import uuid

from fastapi import HTTPException
from sqlalchemy import select

from app.core.personal_information import redact_personal_information as redact
from app.models.identity import Project
from app.services import knowledge_task_tools
from app.services.knowledge_tasks import scope


async def check_context(session, caller, key):
    await scope(session, caller, key)


async def available_contexts(session, caller):
    await check_context(session, caller, "company")
    projects = await session.scalars(
        select(Project)
        .where(Project.id.in_(caller.active_project_ids), Project.status != "archived")
        .order_by(Project.name, Project.id)
    )
    return [{"key": "company", "label": "公司知识库"}] + [
        {"key": f"project:{project.id}", "label": redact(project.name)} for project in projects
    ]


def _projection(detail):
    summary = detail.summary
    text = (summary.detailed or summary.one_liner or "") if summary else ""
    title, text = redact(detail.title), redact(text)
    digest = hashlib.sha256((title + "\n" + text).encode()).hexdigest()
    return title, text, digest


async def search_context(session, caller, key, query):
    await check_context(session, caller, key)
    found = await knowledge_task_tools.search(session, caller, key, redact(query)[:2000])
    rows = []
    seen = set()
    for asset_id, _ in found:
        checked = await knowledge_task_tools.inspect(session, caller, key, asset_id)
        if not checked:
            continue
        detail, current, _ = checked
        if detail.id in seen:
            continue
        seen.add(detail.id)
        title, summary, digest = _projection(detail)
        rows.append(
            {
                "asset_id": str(detail.id),
                "version_id": current["version_id"],
                "context_key": key,
                "title": title,
                "summary": summary[:4000],
                "summary_truncated": len(summary) > 4000,
                "source_type": "summary",
                "projection_digest": digest,
                "url": f"/knowledge/{detail.id}",
            }
        )
    return rows


async def sources_available(session, caller, refs):
    """Recheck provenance before replay/export: withdrawn knowledge stays withdrawn.

    Compare the summary projection as well as version identity. A policy change
    can redact a summary without changing its version, and stored model output
    derived from the previous projection must then be withheld.
    """
    for ref in refs:
        try:
            key = ref["context_key"]
            await check_context(session, caller, key)
            checked = await knowledge_task_tools.inspect(
                session, caller, key, uuid.UUID(ref["asset_id"])
            )
            if not checked:
                return False
            detail, current, _ = checked
            if (
                str(detail.id) != ref["asset_id"]
                or current["version_id"] != ref["version_id"]
                or _projection(detail)[2] != ref["projection_digest"]
            ):
                return False
        except (KeyError, TypeError, ValueError):
            return False
        except HTTPException as exc:
            if exc.status_code in {403, 404}:
                return False
            raise
    return True
