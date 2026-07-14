"""部署 / 可观测端点测试。

覆盖：
- /health 活性；/health/ready 就绪（测试 DB 模式下 healthy）且不含密钥。
- /health/config 只回布尔 / provider 名 / 缺失项名，不含任何值/密钥/URL。
- /admin/ops/summary 仅 admin 可见，返回安全计数，不含业务正文/内部标识。
- 设置布尔解析（CELERY_TASK_ALWAYS_EAGER / WECOM_NOTIFY_ENABLED / ONLYOFFICE_ENABLED）。
- 运行时依赖 import 冒烟（httpx / celery / redis / pypdf / docx 等不缺失）。
"""

from __future__ import annotations

from app.seed.dev_seed import USER_ADMIN_ONLY, USER_CONSULTANT
from app.services import generation_models

# 任何 ops 响应都不得出现的敏感子串。
_SECRET_TOKENS = [
    "devpassword",
    "postgresql+asyncpg",
    "redis://",
    "sk-",
    "Bearer",
    "api_key",
    "app_secret",
    "jwt_secret",
    "token_hash",
    "storage_ref",
    "weknora_kb_id",
    "weknora_doc_id",
    "dataset_id",
    "workflow_id",
]


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


def _assert_no_secret(text: str):
    for t in _SECRET_TOKENS:
        assert t not in text, f"ops 响应不应泄露 {t}"


async def test_health_liveness(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_ready_healthy_in_test_db(client):
    r = await client.get("/health/ready")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] is True
    # 测试默认 eager 模式 → 不检查 redis。
    assert body["checks"]["redis"] is None
    _assert_no_secret(r.text)


async def test_config_diagnostics_safe(client):
    r = await client.get("/health/config")
    assert r.status_code == 200
    body = r.json()
    integ = body["integrations"]
    # 只回布尔 / provider 名；默认全为关/降级。
    for key in ("weknora_enabled", "llm_enabled", "wecom_enabled", "onlyoffice_enabled"):
        assert integ[key] is False
    assert integ["celery_eager"] is True  # 测试默认 eager
    assert integ["external_llm_configured"] is False
    assert integ["weknora_foundation_defaults_configured"] is False
    assert "missing_config" in body
    _assert_no_secret(r.text)


async def test_health_reports_external_llm_and_weknora_foundation_independently(client, db_session):
    await generation_models.create_model(
        db_session,
        display_name="外部业务 LLM",
        provider="openai_compatible",
        model_name="business-chat",
        base_url="https://external.example.test/v1",
        api_key="SECRET-LIKE-health-key",
        enabled=True,
        make_default=True,
        actor_id=USER_ADMIN_ONLY,
    )
    await db_session.commit()

    response = await client.get("/health/config")
    assert response.status_code == 200
    integrations = response.json()["integrations"]
    assert integrations["external_llm_configured"] is True
    assert integrations["weknora_foundation_defaults_configured"] is False
    _assert_no_secret(response.text)


async def test_config_missing_embedding_when_weknora_enabled(client, monkeypatch):
    """PBC-38：底座启用但未配置平台默认 embedding（DB 无行）→ missing_config 列名（不回值）。"""
    monkeypatch.setattr("app.api.ops.weknora_enabled", lambda: True)
    r = await client.get("/health/config")
    assert r.status_code == 200
    body = r.json()
    assert "WEKNORA_DEFAULT_EMBEDDING_MODEL" in body["missing_config"]
    assert "WEKNORA_DEFAULT_KNOWLEDGE_QA_MODEL" in body["missing_config"]
    assert "WEKNORA_EMBEDDING_MODEL_ID" not in body["missing_config"]
    _assert_no_secret(r.text)


async def test_ops_summary_admin_only(client):
    # 非 admin → 403。
    forbidden = await client.get("/admin/ops/summary", headers=_hdr(USER_CONSULTANT))
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"]["denied_reason"] == "ops_admin_required"
    # admin → 200，安全计数。
    ok = await client.get("/admin/ops/summary", headers=_hdr(USER_ADMIN_ONLY))
    assert ok.status_code == 200
    body = ok.json()
    assert body["db_ready"] is True
    assert "ingest" in body and "pending_confirmation" in body["ingest"]
    assert "pending_wecom" in body["notifications"]
    assert "unprocessed_exceptions" in body["audit"]
    _assert_no_secret(ok.text)


def test_settings_boolean_parsing(monkeypatch):
    # 关键布尔标志按字符串环境变量正确解析（"false"/"true" → bool）。
    from app.core.config import Settings

    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "false")
    monkeypatch.setenv("WECOM_NOTIFY_ENABLED", "true")
    monkeypatch.setenv("ONLYOFFICE_ENABLED", "true")
    s = Settings()
    assert s.celery_task_always_eager is False
    assert s.wecom_notify_enabled is True
    assert s.onlyoffice_enabled is True


def test_runtime_dependency_import_smoke():
    # 运行时关键依赖必须可导入（防 httpx 等被误降级为 dev-only 而镜像缺包回归）。
    import importlib

    for mod in (
        "httpx",
        "celery",
        "redis",
        "redis.asyncio",
        "pypdf",
        "docx",
        "fastapi",
        "sqlalchemy",
        "cryptography",
    ):
        assert importlib.import_module(mod) is not None
