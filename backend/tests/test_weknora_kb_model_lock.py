# backend/tests/test_weknora_kb_model_lock.py
"""KB 嵌入模型切换 + ResolvedModels 集成测试（PBC-38 Task 3，requirement 7）。

覆盖五个必须场景：
1. 新 KB 用默认模型建库 → mapping.embedding_model_id == 默认真实 id。
2. 新 KB 用显式模型（explicit_embedding=True）建库 → mapping 记录该 id；create_kb 收到该 id。
3. 已有 KB + 默认驱动（explicit_embedding=False）+ 不同 id → 不触发锁，复用既有 kb_id。
4. 已有 KB + 显式（explicit_embedding=True）不同嵌入 → 自动切换底座配置并回写绑定。
5. Fail-closed：无平台默认配置时 resolve_models_for_kb raise weknora_default_model_not_configured。
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.models.weknora import WeknoraKbMapping
from app.schemas.enums import KnowledgeScope
from app.services import weknora_kb
from app.services.weknora_client import WeKnoraError
from app.services.weknora_model_selection import ResolvedModels, resolve_models_for_kb

pytestmark = pytest.mark.asyncio


def _models(embedding_model_id: str, explicit_embedding: bool) -> ResolvedModels:
    return ResolvedModels(
        embedding_model_id=embedding_model_id,
        explicit_embedding=explicit_embedding,
        chat_model_id="chat-default",
    )


class _FakeKbClient:
    """最简 fake：记录 create_kb 收到的 embedding_model_id，初始化/配置更新直接成功。"""

    def __init__(self):
        self.created: list[str] = []  # create_kb 时记录 embedding_model_id
        self.updated_configs: list[dict[str, Any]] = []

    async def create_kb(self, *, name, embedding_model_id, trace_id=None):
        self.created.append(embedding_model_id)
        return "kb-internal-1"

    async def initialize_kb(self, kb_id, *, trace_id=None, **kw):
        return None

    async def get_kb(self, kb_id, *, trace_id=None):
        return {
            "summary_model_id": "chat-default",
            "embedding_model_id": "emb-A",
            "chunking_config": {},
            "vlm_config": {},
            "asr_config": {},
            "storage_provider_config": {},
            "extract_config": {},
            "question_generation_config": {},
        }

    async def update_initialization_config(self, kb_id, *, config, trace_id=None):
        self.updated_configs.append(config)
        return {"success": True}


class _FakeClientNoModels:
    """list_models 返回空（模拟无可用模型/底座断连），用于 fail-closed 测试。"""

    async def list_models(self, *, trace_id=None):
        return []


# ---------------------------------------------------------------------------
# 场景 1：新 KB + 默认模型
# ---------------------------------------------------------------------------
async def test_new_kb_with_default_model(db_session):
    """新 KB 用默认模型建库；mapping.embedding_model_id 应等于 ResolvedModels 携带的默认 id。"""
    owner = uuid.uuid4()
    models = _models("emb-default-real", False)
    fake = _FakeKbClient()

    kb_id = await weknora_kb.resolve_or_create_kb(
        db_session,
        fake,
        scope=KnowledgeScope.personal.value,
        owner_user_id=owner,
        project_id=None,
        models=models,
        trace_id=None,
    )

    # create_kb 被调用且收到正确 id。
    assert fake.created == ["emb-default-real"]
    # mapping 持久化了 embedding_model_id。
    mapping = (
        await db_session.execute(
            select(WeknoraKbMapping).where(WeknoraKbMapping.owner_user_id == owner)
        )
    ).scalar_one()
    assert mapping.embedding_model_id == "emb-default-real"
    assert mapping.weknora_kb_id == kb_id


# ---------------------------------------------------------------------------
# 场景 2：新 KB + 显式模型
# ---------------------------------------------------------------------------
async def test_new_kb_with_explicit_model(db_session):
    """新 KB 用显式模型（explicit_embedding=True）建库；create_kb 收到显式 id，mapping 记录它。"""
    owner = uuid.uuid4()
    models = _models("emb-chosen-by-user", True)
    fake = _FakeKbClient()

    kb_id = await weknora_kb.resolve_or_create_kb(
        db_session,
        fake,
        scope=KnowledgeScope.personal.value,
        owner_user_id=owner,
        project_id=None,
        models=models,
        trace_id=None,
    )

    assert fake.created == ["emb-chosen-by-user"]
    mapping = (
        await db_session.execute(
            select(WeknoraKbMapping).where(WeknoraKbMapping.owner_user_id == owner)
        )
    ).scalar_one()
    assert mapping.embedding_model_id == "emb-chosen-by-user"
    assert mapping.weknora_kb_id == kb_id


# ---------------------------------------------------------------------------
# 场景 3：已有 KB + 默认驱动 + 不同 id → 不触发锁
# ---------------------------------------------------------------------------
async def test_existing_kb_ignores_default_model_mismatch(db_session):
    """既有 active KB 绑定 emb-A；默认驱动（explicit_embedding=False）传入 emb-B
    → 不触发 lock，复用既有 kb_id，不重建。"""
    owner = uuid.uuid4()
    db_session.add(
        WeknoraKbMapping(
            scope=KnowledgeScope.personal.value,
            owner_user_id=owner,
            project_id=None,
            weknora_kb_id="kb-existing",
            embedding_model_id="emb-A",
            kb_name="personal_x_kb",
            status="active",
        )
    )
    await db_session.commit()

    fake = _FakeKbClient()
    kb = await weknora_kb.resolve_or_create_kb(
        db_session,
        fake,
        scope=KnowledgeScope.personal.value,
        owner_user_id=owner,
        project_id=None,
        models=_models("emb-B", False),
        trace_id=None,
    )
    assert kb == "kb-existing"  # 复用既有；未新建
    assert fake.created == []  # create_kb 从未被调用


# ---------------------------------------------------------------------------
# 场景 4：已有 KB + 显式不同嵌入 → 自动切换
# ---------------------------------------------------------------------------
async def test_existing_kb_switches_conflicting_explicit_model(db_session):
    """既有 active KB 绑定 emb-A；显式传入 emb-B（explicit_embedding=True）→
    自动切换底座配置并回写绑定，不再锁定拒绝。"""
    owner = uuid.uuid4()
    db_session.add(
        WeknoraKbMapping(
            scope=KnowledgeScope.personal.value,
            owner_user_id=owner,
            project_id=None,
            weknora_kb_id="kb-existing",
            embedding_model_id="emb-A",
            kb_name="personal_x_kb",
            status="active",
        )
    )
    await db_session.commit()

    fake = _FakeKbClient()
    kb = await weknora_kb.resolve_or_create_kb(
        db_session,
        fake,
        scope=KnowledgeScope.personal.value,
        owner_user_id=owner,
        project_id=None,
        models=_models("emb-B", True),
        trace_id=None,
    )
    assert kb == "kb-existing"  # 复用既有 KB，不重建
    assert fake.created == []
    assert fake.updated_configs[-1]["embeddingModelId"] == "emb-B"
    mapping = (
        await db_session.execute(
            select(WeknoraKbMapping).where(WeknoraKbMapping.owner_user_id == owner)
        )
    ).scalar_one()
    assert mapping.embedding_model_id == "emb-B"
    assert mapping.status == "active"


# ---------------------------------------------------------------------------
# 场景 6：init_failed 映射 + 显式不同嵌入 → 切换后恢复初始化
# ---------------------------------------------------------------------------
async def test_init_failed_kb_switches_conflicting_explicit_model(db_session):
    """既有 init_failed KB 绑定 emb-A；显式传入 emb-B（explicit_embedding=True）→
    先切换绑定到 emb-B，再按新绑定初始化并恢复 active。"""
    owner = uuid.uuid4()
    db_session.add(
        WeknoraKbMapping(
            scope=KnowledgeScope.personal.value,
            owner_user_id=owner,
            project_id=None,
            weknora_kb_id="kb-init-failed-1",
            embedding_model_id="emb-A",
            kb_name="personal_x_kb",
            status="init_failed",
        )
    )
    await db_session.commit()

    fake = _FakeKbClient()
    kb = await weknora_kb.resolve_or_create_kb(
        db_session,
        fake,
        scope=KnowledgeScope.personal.value,
        owner_user_id=owner,
        project_id=None,
        models=_models("emb-B", True),
        trace_id=None,
    )
    assert kb == "kb-init-failed-1"
    assert fake.updated_configs[-1]["embeddingModelId"] == "emb-B"
    mapping = (
        await db_session.execute(
            select(WeknoraKbMapping).where(WeknoraKbMapping.owner_user_id == owner)
        )
    ).scalar_one()
    assert mapping.embedding_model_id == "emb-B"
    assert mapping.status == "active"


# ---------------------------------------------------------------------------
# 场景 7：init_failed 映射 + 默认驱动 → 正常恢复（不触发锁）
# ---------------------------------------------------------------------------
async def test_init_failed_kb_recovers_with_default_model(db_session):
    """既有 init_failed KB 绑定 emb-A；默认驱动（explicit_embedding=False）传入任意 id →
    不触发锁；initialize_kb 成功后状态翻 active，返回既有 kb_id。"""
    owner = uuid.uuid4()
    db_session.add(
        WeknoraKbMapping(
            scope=KnowledgeScope.personal.value,
            owner_user_id=owner,
            project_id=None,
            weknora_kb_id="kb-init-failed-2",
            embedding_model_id="emb-A",
            kb_name="personal_y_kb",
            status="init_failed",
        )
    )
    await db_session.commit()

    fake = _FakeKbClient()
    kb = await weknora_kb.resolve_or_create_kb(
        db_session,
        fake,
        scope=KnowledgeScope.personal.value,
        owner_user_id=owner,
        project_id=None,
        models=_models("emb-B", False),
        trace_id=None,
    )
    assert kb == "kb-init-failed-2"  # 复用既有 kb_id
    assert fake.created == []  # create_kb 从未被调用（KB 已存在）
    # 映射状态已翻为 active。
    mapping = (
        await db_session.execute(
            select(WeknoraKbMapping).where(WeknoraKbMapping.owner_user_id == owner)
        )
    ).scalar_one()
    assert mapping.status == "active"


# ---------------------------------------------------------------------------
# 场景 5：Fail-closed — 平台默认模型未配置
# ---------------------------------------------------------------------------
async def test_no_default_configured_raises_fail_closed(db_session):
    """无 WeknoraDefaultModels 行且无显式 ref → resolve_models_for_kb 应 raise
    weknora_default_model_not_configured（不回退 .env / settings）。"""
    # db_session 是干净内存库：平台默认模型未配置（DB 无 WeknoraDefaultModels 行）。
    with pytest.raises(WeKnoraError) as ei:
        await resolve_models_for_kb(
            db_session,
            _FakeClientNoModels(),
            embedding_model_ref=None,
            rerank_model_ref=None,
            trace_id=None,
        )
    assert ei.value.code == "weknora_default_model_not_configured"
