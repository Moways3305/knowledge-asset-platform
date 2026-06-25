"""平台默认 WeKnora 模型配置读写服务（PBC-38）。

单例：整库一行。读返回该行（无则 None）；写 upsert（无则建）。
存储 server-only raw model_id；解析 model_ref→id 由调用方（weknora_model_selection）负责。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.weknora_defaults import WeknoraDefaultModels


async def get_defaults(session: AsyncSession) -> WeknoraDefaultModels | None:
    return (await session.execute(select(WeknoraDefaultModels))).scalars().first()


async def set_defaults(
    session: AsyncSession,
    *,
    embedding_model_id: str | None,
    rerank_model_id: str | None,
    chat_model_id: str | None,
    multimodal_id: str | None,
    updated_by: uuid.UUID | None,
) -> WeknoraDefaultModels:
    row = await get_defaults(session)
    if row is None:
        row = WeknoraDefaultModels()
        session.add(row)
    row.default_embedding_model_id = (embedding_model_id or None) or None
    row.default_rerank_model_id = (rerank_model_id or None) or None
    row.default_chat_model_id = (chat_model_id or None) or None
    row.default_multimodal_model_id = (multimodal_id or None) or None
    row.updated_by = updated_by
    await session.flush()
    return row
