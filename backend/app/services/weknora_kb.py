"""scope→KB 映射服务（含初始化）。

把业务 scope 实体映射到 WeKnora 知识库 id；懒创建幂等（同 scope 实体只建一个 KB，
并发靠唯一约束冲突重查）。映射行**独立提交**（不随后续 asset 上传失败回滚——KB 可复用，
不应因单次入库失败而丢弃）。

建 KB 后**立即初始化模型配置**（chat/embedding/rerank/multimodal），确保 KB
一建即可用，而非只有空 embedding。初始化失败不写成 `active` 假成功：映射置 `init_failed`
并 raise，调用方据此进入可诊断的 index_failed；下次 resolve 命中 init_failed 映射会**重试
初始化**（ensure-initialized），成功则翻 `active`，避免孤儿 KB 累积。

安全：返回的 `weknora_kb_id` 是 server-only 内部标识，调用方只用于 scope 路由与
upload，**绝不**写进响应 / 审计 / 日志。模型 id 同为 server-only。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.weknora import WeknoraKbMapping
from app.schemas.enums import KnowledgeScope
from app.services.weknora_client import NullWeKnoraClient, WeKnoraClient, WeKnoraError

# 映射 status 取值：active（已建 + 已初始化，可用）/ init_failed（已建但初始化失败，待重试）。
_STATUS_ACTIVE = "active"
_STATUS_INIT_FAILED = "init_failed"


def _kb_name(scope: str, owner_user_id: uuid.UUID | None, project_id: uuid.UUID | None) -> str:
    if scope == KnowledgeScope.personal.value:
        return f"personal_{owner_user_id}_kb"
    if scope == KnowledgeScope.project.value:
        return f"project_{project_id}_kb"
    return "company_kb"


def _init_kwargs() -> dict[str, str | None]:
    """从 settings 取 KB 初始化模型 id（仅非空才会被 client 发送）。

    embedding 必需；chat/rerank/multimodal 可选。summary 模型**不参与**（摘要走平台
    外部 LLM）。模型 id 是 WeKnora 已注册模型的引用，非密钥，但仍 server-only。
    """
    s = get_settings()
    return {
        "embedding_model_id": s.weknora_embedding_model_id or None,
        "chat_model_id": s.weknora_chat_model_id or None,
        "rerank_model_id": s.weknora_rerank_model_id or None,
        "multimodal_id": s.weknora_multimodal_model_id or None,
    }


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
    """取得（或懒创建 + 初始化）该 scope 实体的 weknora_kb_id。幂等；映射行独立提交。

    - 命中 active 映射：直接返回（不重复初始化）。
    - 命中 init_failed 映射：重试初始化（ensure-initialized），成功翻 active 后返回；失败 raise。
    - 无映射：create_kb → initialize_kb → 写映射（成功 active / 失败 init_failed 后 raise）。

    初始化失败抛 `WeKnoraError`（已持久化 init_failed 映射供重试），由调用方标 index_failed。

    **fail-closed**：底座已启用但缺 `embedding_model_id`（`WEKNORA_EMBEDDING_MODEL_ID` 未配）
    时，KB 初始化不完整——**不建 KB、不写 active 映射**，直接抛
    `weknora_embedding_model_missing`，由调用方标 index_failed（资产保留、可在补配置后重试）。
    """
    if not (embedding_model_id or "").strip():
        # 不创建 KB、不写映射：避免产生"平台 active、底座未初始化"的假成功。补配置后重试即可。
        raise WeKnoraError(
            "weknora_embedding_model_missing",
            "WeKnora 已启用但未配置 embedding 模型，无法初始化知识库",
        )

    existing = await _find(session, scope, owner_user_id, project_id)
    if existing is not None:
        if existing.status == _STATUS_ACTIVE:
            return existing.weknora_kb_id
        # init_failed：重试初始化（KB 已存在，只补模型配置）。成功翻 active，失败 raise。
        await client.initialize_kb(existing.weknora_kb_id, trace_id=trace_id, **_init_kwargs())
        existing.status = _STATUS_ACTIVE
        await session.commit()
        return existing.weknora_kb_id

    name = _kb_name(scope, owner_user_id, project_id)
    kb_id = await client.create_kb(
        name=name, embedding_model_id=embedding_model_id, trace_id=trace_id
    )
    # 建库后初始化模型配置；失败时不写成 active 假成功，而是持久化 init_failed 供重试。
    init_error: WeKnoraError | None = None
    try:
        await client.initialize_kb(kb_id, trace_id=trace_id, **_init_kwargs())
    except WeKnoraError as exc:
        init_error = exc

    mapping = WeknoraKbMapping(
        scope=scope, owner_user_id=owner_user_id, project_id=project_id,
        weknora_kb_id=kb_id, embedding_model_id=embedding_model_id, kb_name=name,
        status=_STATUS_ACTIVE if init_error is None else _STATUS_INIT_FAILED,
    )
    session.add(mapping)
    try:
        await session.commit()
    except IntegrityError:
        # 并发：另一请求已建映射。回滚本插入，重查取既有 kb_id。
        await session.rollback()
        winner = await _find(session, scope, owner_user_id, project_id)
        if winner is not None:
            if winner.status == _STATUS_ACTIVE:
                return winner.weknora_kb_id
            # 既有映射仍 init_failed：让本次按失败处理（调用方可重试 ensure-initialized）。
            raise WeKnoraError("weknora_init_failed", "知识库模型初始化未完成") from init_error
        raise
    if init_error is not None:
        # 映射已落库为 init_failed，抛出让调用方标 index_failed（资产不回滚）。
        raise init_error
    return kb_id


async def ensure_project_kb(
    session: AsyncSession,
    client: WeKnoraClient | NullWeKnoraClient,
    *,
    project_id: uuid.UUID,
    trace_id: str | None,
) -> str:
    """项目创建后**预创建并初始化** project KB。best-effort，返回安全状态串。

    绝不让底座问题导致项目创建失败：未配置 WeKnora → "skipped"；建库/初始化失败 →
    "index_failed"（映射可能已落 init_failed，首次入库会重试）。**绝不**外泄 kb_id /
    api_key / 原始 payload —— 只返回安全状态枚举串供调用方记安全运营信号。
    """
    from app.services.weknora_client import weknora_enabled

    if not weknora_enabled():
        return "skipped"
    try:
        await resolve_or_create_kb(
            session, client,
            scope=KnowledgeScope.project.value,
            owner_user_id=None, project_id=project_id,
            embedding_model_id=get_settings().weknora_embedding_model_id,
            trace_id=trace_id,
        )
        return "indexed"
    except Exception:  # noqa: BLE001  # 任意底座异常都不阻断项目创建
        await session.rollback()
        return "index_failed"

