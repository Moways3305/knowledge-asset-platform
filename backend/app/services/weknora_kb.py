"""scope→KB 映射服务（R1）。

把业务 scope 实体映射到 WeKnora 知识库 id；懒创建幂等（同 scope 实体只建一个 KB，
并发靠唯一约束冲突重查）。映射行**独立提交**（不随后续 asset 上传失败回滚——KB 可复用，
不应因单次入库失败而丢弃）。

安全：返回的 `weknora_kb_id` 是 server-only 内部标识，调用方只用于 scope 路由与
upload，**绝不**写进响应 / 审计 / 日志。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.weknora import WeknoraKbMapping
from app.schemas.enums import KnowledgeScope
from app.services.weknora_client import NullWeKnoraClient, WeKnoraClient


def _kb_name(scope: str, owner_user_id: uuid.UUID | None, project_id: uuid.UUID | None) -> str:
    if scope == KnowledgeScope.personal.value:
        return f"personal_{owner_user_id}_kb"
    if scope == KnowledgeScope.project.value:
        return f"project_{project_id}_kb"
    return "company_kb"


async def _find(
    session: AsyncSession, scope: str, owner_user_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
) -> WeknoraKbMapping | None:
    stmt = select(WeknoraKbMapping).where(WeknoraKbMapping.scope == scope)
    # NULL 比较：personal 用 owner、project 用 project_id，company 两者皆 NULL。
    if owner_user_id is None:
        stmt = stmt.where(WeknoraKbMapping.owner_user_id.is_(None))
    else:
        stmt = stmt.where(WeknoraKbMapping.owner_user_id == owner_user_id)
    if project_id is None:
        stmt = stmt.where(WeknoraKbMapping.project_id.is_(None))
    else:
        stmt = stmt.where(WeknoraKbMapping.project_id == project_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def resolve_or_create_kb(
    session: AsyncSession,
    client: WeKnoraClient | NullWeKnoraClient,
    *,
    scope: str,
    owner_user_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    embedding_model_id: str,
    trace_id: str | None,
) -> str:
    """取得（或懒创建）该 scope 实体的 weknora_kb_id。幂等；映射行独立提交。"""
    existing = await _find(session, scope, owner_user_id, project_id)
    if existing is not None:
        return existing.weknora_kb_id

    name = _kb_name(scope, owner_user_id, project_id)
    kb_id = await client.create_kb(
        name=name, embedding_model_id=embedding_model_id, trace_id=trace_id
    )
    mapping = WeknoraKbMapping(
        scope=scope, owner_user_id=owner_user_id, project_id=project_id,
        weknora_kb_id=kb_id, embedding_model_id=embedding_model_id, kb_name=name,
        status="active",
    )
    session.add(mapping)
    try:
        await session.commit()
    except IntegrityError:
        # 并发：另一请求已建映射。回滚本插入，重查取既有 kb_id。
        await session.rollback()
        winner = await _find(session, scope, owner_user_id, project_id)
        if winner is not None:
            return winner.weknora_kb_id
        raise
    return kb_id
