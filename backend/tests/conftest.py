"""测试夹具（fixtures）。

测试数据库：使用内存 SQLite（sqlite+aiosqlite，StaticPool 单连接），在每个测试内
建表并写入 seed。本阶段模型简单（仅 String/Uuid/DateTime + 唯一约束），SQLite 与
PostgreSQL 语义一致，可放心用于快速测试；正式运行仍以 PostgreSQL 为准。

测试不依赖任何真实外部系统。异步测试由 pytest-asyncio（auto 模式）驱动。
"""

from __future__ import annotations

import os
import sys

# 让本目录可被 `from conftest import patch_default_model` 直接导入：
# 默认 prepend 模式下 pytest 不保证把 tests/ 放进 sys.path，显式补一笔。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 测试隔离：**在导入 app（首次实例化 Settings）之前** 强制清空外部集成配置，
# 让测试不受本机 `backend/.env`（含真实 WeKnora / LLM / 企微 / ONLYOFFICE 值，供 Docker
# 联调用）污染。环境变量优先级高于 .env 文件，故此处置空即可覆盖。
# 整数/布尔字段给确定测试值（eager 同步、外部集成关闭）。
_TEST_ENV = {
    "APP_ENV": "test",
    "CELERY_TASK_ALWAYS_EAGER": "true",
    "WEKNORA_BASE_URL": "",
    "WEKNORA_API_KEY": "",
    "WEKNORA_EMBEDDING_MODEL_ID": "",
    "LLM_PROVIDER": "",
    "LLM_API_KEY": "",
    "GENERATION_MODEL_ENCRYPTION_KEY": "120-AdD5cTy_h5BsXpX0yMJbn4ff95Ca9jx66G9e0ck=",
    "GENERATION_MODEL_REF_SECRET": "test-generation-model-ref-secret",
    "WECOM_CORP_ID": "",
    "WECOM_APP_SECRET": "",
    "WECOM_NOTIFY_ENABLED": "false",
    "ONLYOFFICE_ENABLED": "false",
    "ONLYOFFICE_DOCUMENT_SERVER_URL": "",
}
for _k, _v in _TEST_ENV.items():
    os.environ[_k] = _v

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.models  # noqa: F401,E402  # 确保模型注册到 Base.metadata
from app.core.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.seed.dev_seed import (  # noqa: E402
    seed_dev_identities,
    seed_dev_knowledge,
    seed_dev_reviews,
)
from app.services.storage import LocalFileStorage, get_storage  # noqa: E402

# 若 Settings 已被其它早期 import 缓存，清缓存确保读到上面的测试环境。
get_settings.cache_clear()


def patch_default_model(monkeypatch, *, embedding="test-embed", explicit=False):
    """PBC-38 测试助手：让真实模型 resolver 返回固定 ResolvedModels（绕过 DB 默认模型配置）。

    建库链路现经 `resolve_models_for_kb`（explicit ref > 平台默认 > fail closed）取模型；
    旧测试用 `settings.weknora_embedding_model_id` 启用底座已失效。覆盖三处绑定：
    indexing（confirm/retry/index/reparse）、personal_kb（个人建库）、weknora_model_selection
    源（ensure_project_kb 的函数内 import）。模型选择本身另有专测覆盖。
    """
    from app.services.weknora_model_selection import ModelInitMeta, ResolvedModels

    emb = ModelInitMeta(embedding, "remote", embedding, "embedding")
    chat = ModelInitMeta("test-chat", "remote", "test-chat", "chat")
    resolved = ResolvedModels(
        embedding_model_id=embedding,
        explicit_embedding=explicit,
        chat_model_id=chat.model_id,
        embedding=emb,
        chat=chat,
        models_by_id={embedding: emb, chat.model_id: chat},
    )

    async def _resolve(*_a, **_k):
        return resolved

    for target in (
        "app.services.indexing.resolve_models_for_kb",
        "app.services.personal_kb.resolve_models_for_kb",
        "app.services.weknora_model_selection.resolve_models_for_kb",
    ):
        monkeypatch.setattr(target, _resolve)


@pytest_asyncio.fixture
async def sessionmaker_fixture():
    """创建内存 SQLite 引擎、建表、写入 seed，并返回 session 工厂。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        await seed_dev_identities(session)
        await seed_dev_knowledge(session)
        await seed_dev_reviews(session)

    yield maker
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(sessionmaker_fixture):
    """提供一个绑定到测试库（已建表 + 已写入 seed）的异步 session。"""
    async with sessionmaker_fixture() as session:
        yield session


@pytest_asyncio.fixture
async def client(sessionmaker_fixture, tmp_path):
    """提供绑定到测试库的 AsyncClient，并覆盖 get_db / get_storage 依赖。

    文件存储指向 pytest 临时目录（tmp_path），保持 hermetic：上传写入的真实字节
    随测试目录自动清理，不污染仓库。
    """

    async def override_get_db():
        async with sessionmaker_fixture() as session:
            yield session

    storage = LocalFileStorage(tmp_path / "storage")
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_storage] = lambda: storage
    transport = ASGITransport(app=app)
    # base_url 用 https，使 prod 守卫下发的 Secure cookie 能在测试 cookie jar 中正常回送
    # （prod 会话 cookie 强制 Secure；httpx 不会把 Secure cookie 回送到 http://）。
    async with AsyncClient(transport=transport, base_url="https://test") as ac:
        ac._kap_storage = storage  # 供测试断言文件确实落盘
        yield ac
    app.dependency_overrides.clear()
