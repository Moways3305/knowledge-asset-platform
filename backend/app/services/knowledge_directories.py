"""Create scoped directories without granting access to global policy publishing."""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Project
from app.models.knowledge_directory import KnowledgeDirectory
from app.models.naming import NamingRuleRevision
from app.schemas.enums import AuditAction, AuditLogType
from app.schemas.knowledge_directory import DirectoryCreateRequest
from app.schemas.permission import CallerContext
from app.services.audit import record_event
from app.services.directories import STANDARD_BY_KEY, published_directories


def _denied(status: int, reason: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"denied_reason": reason, "message": message})


async def create_directory(
    session: AsyncSession, caller: CallerContext, body: DirectoryCreateRequest, trace_id: str | None
) -> dict:
    allowed = (
        caller.is_active
        and caller.is_business_user
        and (
            bool(caller.active_company_roles & {"boss", "consulting_director"})
            if body.scope == "company"
            else body.project_id in caller.active_project_ids
            and caller.active_project_roles.get(body.project_id) == "project_manager"
        )
    )
    if not allowed:
        raise _denied(403, "directory_create_denied", "没有当前知识库的新建目录权限")
    if body.project_id is not None:
        project = await session.get(Project, body.project_id)
        if project is None or project.status != "active":
            raise _denied(403, "directory_project_unavailable", "目标项目不可用")
    # Serialize using the first immutable published revision: a category cannot be disabled while
    # its child is being created against an older published snapshot.
    await session.execute(
        select(NamingRuleRevision)
        .where(NamingRuleRevision.status == "published")
        .order_by(NamingRuleRevision.version.asc())
        .limit(1)
        .with_for_update()
    )
    _, rows = await published_directories(session)
    parent = next((row for row in rows if row["directory_key"] == body.parent_key), None)
    standard = STANDARD_BY_KEY.get(body.parent_key)
    if (
        standard is None
        or standard.scope != body.scope
        or parent is None
        or not parent.get("enabled", True)
        or parent.get("parent_key")
    ):
        raise _denied(
            422, "directory_parent_invalid", "只能在当前知识库启用的标准分类下新建三级目录"
        )
    normalized = body.display_name.casefold()
    if any(
        row.get("scope") == body.scope
        and row.get("parent_key") == body.parent_key
        and (not row.get("project_id") or row["project_id"] == str(body.project_id))
        and str(row.get("display_name", "")).casefold() == normalized
        for row in rows
    ):
        raise _denied(409, "directory_duplicate", "当前分类下已存在同名目录")
    item = KnowledgeDirectory(
        directory_key=f"{body.scope}.custom_{uuid.uuid4().hex}",
        library_key=str(body.project_id) if body.project_id else "company",
        scope=body.scope,
        project_id=body.project_id,
        parent_key=body.parent_key,
        display_name=body.display_name,
        normalized_name=normalized,
        default_confidentiality=parent.get("default_confidentiality", "L2"),
        created_by=caller.user_id,
    )
    session.add(item)
    try:
        await session.flush()
        await record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.knowledge_directory_created.value,
            trace_id=trace_id,
            target_type="knowledge_directory",
            target_id=item.id,
            project_id=body.project_id,
            after={
                "directory_key": item.directory_key,
                "parent_key": item.parent_key,
                "display_name": item.display_name,
                "scope": item.scope,
            },
        )
        result = {"directory_key": item.directory_key, "name": item.display_name}
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise _denied(409, "directory_duplicate", "当前分类下已存在同名目录") from None
    return result
