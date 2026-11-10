"""scope→KB 映射服务（含初始化）。

把业务 scope 实体映射到 WeKnora 知识库 id；懒创建幂等（同 scope 实体只建一个 KB，
并发由独立连接持有的作用域锁串行化）。映射行**独立提交**（不随后续 asset 上传失败回滚——KB 可复用，
不应因单次入库失败而丢弃）。

建 KB 后**立即初始化模型配置**（chat/embedding/rerank/multimodal），确保 KB
一建即可用，而非只有空 embedding。初始化失败不写成 `active` 假成功：映射置 `init_failed`
并 raise，调用方据此进入可诊断的 index_failed；下次 resolve 命中 init_failed 映射会**重试
初始化**（ensure-initialized），成功则翻 `active`，避免孤儿 KB 累积。

安全：返回的 `weknora_kb_id` 是 server-only 内部标识，调用方只用于 scope 路由与
upload，**绝不**写进响应 / 审计 / 日志。模型 id 同为 server-only。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import safe_log_exception
from app.models.weknora import WeknoraKbMapping
from app.schemas.enums import KnowledgeScope
from app.services.job_execution import try_execution_lock
from app.services.weknora_client import NullWeKnoraClient, WeKnoraClient, WeKnoraError
from app.services.weknora_model_selection import ResolvedModels
from app.services.weknora_models import _kb_update_config

# 映射 status 取值：active（已建 + 已初始化，可用）/ init_failed（已建但初始化失败，待重试）。
_STATUS_ACTIVE = "active"
_STATUS_INIT_FAILED = "init_failed"

# 个人 KB 的用户可读默认名（个人知识库能力）。懒创建路径（用户先上传、未显式建库）也用它，
# 与迁移 0029 对既有 personal 映射的回填一致，保证个人 KB 始终有可读名称。
DEFAULT_PERSONAL_KB_NAME = "我的知识库"

_logger = logging.getLogger(__name__)


def _kb_name(scope: str, owner_user_id: uuid.UUID | None, project_id: uuid.UUID | None) -> str:
    if scope == KnowledgeScope.personal.value:
        return f"personal_{owner_user_id}_kb"
    if scope == KnowledgeScope.project.value:
        return f"project_{project_id}_kb"
    return "company_kb"


def _locked(existing: WeknoraKbMapping, models: ResolvedModels) -> bool:
    """KB 嵌入模型需要切换：显式指定了不同嵌入模型时返回 True（触发自动切换）。
    默认驱动（explicit_embedding=False）或既有映射无绑定模型时永不触发。
    """
    return bool(
        models.explicit_embedding
        and existing.embedding_model_id
        and models.embedding_model_id != existing.embedding_model_id
    )


async def _switch_embedding_model(
    client: WeKnoraClient | NullWeKnoraClient,
    kb_id: str,
    models: ResolvedModels,
    *,
    trace_id: str | None,
) -> None:
    """把既有 KB 的 embedding 配置切换到显式指定的新模型（取代旧的锁定拒绝）。

    按当前底座契约 PUT 完整配置（从现有 KB 资源读取合并，避免零值覆盖），由调用方重新
    核对映射后提交绑定。调用方负责对存量文档重新解析（重新向量化），新旧向量空间才不会
    混用。失败抛 WeKnoraError，由调用方进入可诊断的 index_failed（资产保留、可重试）。
    """
    current_kb = await client.get_kb(kb_id, trace_id=trace_id)
    config = _kb_update_config(current_kb)
    if not str(config.get("llmModelId") or "").strip():
        raise WeKnoraError(
            "weknora_kb_chat_model_missing",
            "知识库当前未配置问答模型，无法切换嵌入模型",
        )
    config["embeddingModelId"] = models.embedding_model_id
    await client.update_initialization_config(kb_id, config=config, trace_id=trace_id)


async def _write_kb_config_by_ids(
    client: WeKnoraClient | NullWeKnoraClient,
    kb_id: str,
    *,
    models: ResolvedModels,
    embedding_model_id: str,
    trace_id: str | None,
) -> None:
    """按 server-only 模型 id 写 KB 模型配置（PUT /initialization/config/:kb_id）。

    刻意**不**走 `initialize_kb`（source/modelName 契约）：WeKnora v0.7.1 会按名称
    自动创建/改写模型记录——实测会把已配置模型的 base_url/api_key 清空并生成一个
    tenant=0、base_url 为空的坏模型。建库/初始化只应**引用**模型，绝不应**修改**模型
    本身；因此这里从现有 KB 读取配置合并后，仅把 chat/embedding 槽位替换为目标模型
    id 写回，完全不触碰模型记录。
    """
    current_kb = await client.get_kb(kb_id, trace_id=trace_id)
    config = _kb_update_config(current_kb)
    chat_id = models.chat.model_id if models.chat is not None else models.chat_model_id
    if not chat_id:
        raise WeKnoraError(
            "weknora_init_contract_incomplete",
            "WeKnora 知识库初始化缺少问答模型配置",
        )
    config["llmModelId"] = chat_id
    config["embeddingModelId"] = embedding_model_id
    await client.update_initialization_config(kb_id, config=config, trace_id=trace_id)


async def _find(
    session: AsyncSession,
    scope: str,
    owner_user_id: uuid.UUID | None,
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
    return (
        await session.execute(stmt.execution_options(populate_existing=True))
    ).scalar_one_or_none()


@asynccontextmanager
async def _provisioning_lock(session, scope, owner_user_id, project_id):
    """Serialize first use/configuration without extending a business transaction.

    The composite unique constraint contains NULLs and cannot prevent duplicate
    first-use mappings on PostgreSQL. All creation entry points use this lock.
    Other scopes proceed independently; a disconnected owner releases it.
    """
    if session.get_bind().dialect.name != "postgresql":
        yield
        return
    identifier = uuid.uuid5(uuid.NAMESPACE_URL, f"kap:kb:{scope}:{owner_user_id}:{project_id}")
    async with AsyncSession(bind=session.bind) as owner:

        async def acquire():
            while not await try_execution_lock(owner, "kb-provision", identifier):
                # Waiters must not exhaust the pool needed by the current owner
                # to journal/finish initialization. Only the winner keeps a lease.
                await owner.rollback()
                await asyncio.sleep(0.1)

        try:
            try:
                await asyncio.wait_for(
                    acquire(), timeout=min(30, max(0.1, get_settings().weknora_timeout))
                )
            except asyncio.TimeoutError as exc:
                raise WeKnoraError("weknora_kb_busy", "知识库正在初始化，请稍后重试") from exc
            yield
        finally:
            await owner.rollback()


async def _initialize_mapping(session, client, mapping, models, *, trace_id):
    # Capture scalar state before network I/O and refresh under a short row lock
    # afterwards. Never restore a mapping replaced or migrated during the call.
    mapping_id = mapping.id
    kb_id, previous_embedding, status = (
        mapping.weknora_kb_id,
        mapping.embedding_model_id,
        mapping.status,
    )
    bound = (
        models.embedding_model_id
        if _locked(mapping, models)
        else (previous_embedding or models.embedding_model_id)
    )
    await session.commit()
    if status == _STATUS_ACTIVE:
        await _switch_embedding_model(client, kb_id, models, trace_id=trace_id)
    else:
        await _write_kb_config_by_ids(
            client, kb_id, models=models, embedding_model_id=bound, trace_id=trace_id
        )
    current = await session.scalar(
        select(WeknoraKbMapping)
        .where(WeknoraKbMapping.id == mapping_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if current is None or (current.weknora_kb_id, current.embedding_model_id, current.status) != (
        kb_id,
        previous_embedding,
        status,
    ):
        await session.rollback()
        raise WeKnoraError("weknora_configuration_changed", "知识库配置已变化，请重试")
    current.embedding_model_id = bound
    current.status = _STATUS_ACTIVE
    await session.commit()
    return kb_id


async def resolve_or_create_kb(
    session: AsyncSession,
    client: WeKnoraClient | NullWeKnoraClient,
    *,
    scope: str,
    owner_user_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    models: ResolvedModels,
    trace_id: str | None,
    display_name: str | None = None,
) -> str:
    """取得（或懒创建 + 初始化）该 scope 实体的 weknora_kb_id。幂等；映射行独立提交。

    `display_name`（个人知识库能力）：建库时作为 WeKnora `name`（让底座端也可读）并存入映射
    `display_name` 列。为空时：personal scope 回退默认「我的知识库」；project / company
    回退 slug（display_name 列留空，可读名另有来源）。命中既有映射不改名（改名走显式 API）。

    - 命中 active 映射：直接返回（不重复初始化）。explicit_embedding + 模型不匹配 →
      自动切换底座 embedding 配置并回写绑定（存量文档需重新解析以重新向量化）。
    - 命中 init_failed 映射：重试初始化（ensure-initialized），成功翻 active 后返回；失败 raise。
    - 无映射：create_kb → 记录 init_failed 映射 → 初始化 → 成功后翻 active。

    初始化失败抛 `WeKnoraError`（已持久化 init_failed 映射供重试），由调用方标 index_failed。

    **fail-closed**：底座已启用但 models.embedding_model_id 为空（极端防御情形）时，
    **不建 KB、不写 active 映射**，直接抛 `weknora_embedding_model_missing`，由调用方标
    index_failed（资产保留、可在补配置后重试）。正常情况下 resolve_models_for_kb 已在上游
    raise weknora_default_model_not_configured，本守卫仅为绝对防御兜底。
    """
    if not (models.embedding_model_id or "").strip():
        # 不创建 KB、不写映射：避免产生"平台 active、底座未初始化"的假成功。
        raise WeKnoraError(
            "weknora_embedding_model_missing",
            "WeKnora 已启用但未配置 embedding 模型，无法初始化知识库",
        )

    # Active mappings also wait for an in-flight initialization/model switch.
    # Release the caller's business transaction before acquiring scope ownership.
    await session.commit()
    async with _provisioning_lock(session, scope, owner_user_id, project_id):
        existing = await _find(session, scope, owner_user_id, project_id)
        if existing is not None:
            if existing.status == "migrating":
                await session.commit()
                raise WeKnoraError("weknora_kb_migrating", "知识库正在重建迁移，暂不接受新入库")
            if existing.status == _STATUS_ACTIVE and not _locked(existing, models):
                kb_id = existing.weknora_kb_id
                await session.commit()
                return kb_id
            return await _initialize_mapping(session, client, existing, models, trace_id=trace_id)

        slug = _kb_name(scope, owner_user_id, project_id)
        effective_display = (display_name or "").strip() or None
        if effective_display is None and scope == KnowledgeScope.personal.value:
            effective_display = DEFAULT_PERSONAL_KB_NAME
        await session.commit()
        kb_id = await client.create_kb(
            name=effective_display or slug,
            embedding_model_id=models.embedding_model_id,
            trace_id=trace_id,
        )
        # Journal the returned remote identity before initialization. Cancellation
        # or a timeout during initialization must retry this KB, not create another.
        mapping = WeknoraKbMapping(
            scope=scope,
            owner_user_id=owner_user_id,
            project_id=project_id,
            weknora_kb_id=kb_id,
            embedding_model_id=models.embedding_model_id,
            kb_name=slug,
            display_name=effective_display,
            status=_STATUS_INIT_FAILED,
        )
        session.add(mapping)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            winner = await _find(session, scope, owner_user_id, project_id)
            if winner is not None and winner.status == _STATUS_ACTIVE:
                winner_id = winner.weknora_kb_id
                await session.commit()
                return winner_id
            raise
        return await _initialize_mapping(session, client, mapping, models, trace_id=trace_id)


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
    from app.services.weknora_model_selection import resolve_models_for_kb

    if not weknora_enabled():
        return "skipped"
    try:
        models = await resolve_models_for_kb(
            session, client, embedding_model_ref=None, rerank_model_ref=None, trace_id=trace_id
        )
        await resolve_or_create_kb(
            session,
            client,
            scope=KnowledgeScope.project.value,
            owner_user_id=None,
            project_id=project_id,
            models=models,
            trace_id=trace_id,
        )
        return "indexed"
    except Exception as exc:  # noqa: BLE001  # 任意底座异常都不阻断项目创建
        safe_log_exception(_logger, "project_kb_provision_failed", exc, include_summary=False)
        await session.rollback()
        return "index_failed"
