"""Application configuration via environment variables.

Uses pydantic-settings. No secrets are hardcoded; values come from the
environment or a local `.env` file (see `.env.example`).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "knowledge-asset-platform"
    app_env: str = "local"
    log_level: str = "INFO"

    # PostgreSQL async connection string, e.g.
    # postgresql+asyncpg://dev:devpassword@localhost:5432/knowledge_platform
    database_url: str = (
        "postgresql+asyncpg://dev:devpassword@localhost:5432/knowledge_platform"
    )

    # Redis URL for Celery broker / result backend.
    redis_url: str = "redis://localhost:6379/0"

    # Celery 异步治理作业（R5）。broker / backend 缺省回退到 redis_url。
    # celery_task_always_eager：默认 True——无 worker 也能跑（入库处理内联同步执行，
    # API 开箱即用）；生产接 worker 时设为 false 启用真正异步（work 排队到 broker，
    # 无 worker 时任务保持 processing/pending）。
    celery_broker_url: str = ""
    celery_result_backend: str = ""
    celery_task_always_eager: bool = True

    # 受控本地文件存储根目录（IMPLEMENT-13，仅 dev/test）。上传的文件字节写入此处；
    # 内部存储引用（server-only）不进入任何 API 响应。生产应替换为对象存储后端。
    storage_root: str = "./_local_storage"

    # WeKnora 知识底座（R1）。base_url + api_key 都配置时启用真实集成；否则降级跳过
    # 索引（dev 无 WeKnora 仍可起 app / confirm）。api_key（sk- 前缀）绝不外泄。
    weknora_base_url: str = ""
    weknora_api_key: str = ""
    weknora_embedding_model_id: str = ""
    weknora_summary_model_id: str = ""
    weknora_tenant_id: str = ""
    weknora_timeout: float = 30.0

    # 外部 LLM 内容处理（R2）。统一方案：选一个 active provider（`LLM_PROVIDER`）+ 其
    # `LLM_API_KEY`；base_url / model 缺省走 provider 注册表默认值，可由 env 覆盖。
    # provider + api_key 都配置才启用，否则内容处理降级到确定性草稿。api_key 绝不外泄。
    llm_provider: str = ""  # deepseek / kimi / qwen / glm / minimax / openai / custom
    llm_api_key: str = ""
    llm_base_url: str = ""  # 覆盖 provider 默认 base_url（custom 必填）
    llm_model: str = ""  # 覆盖 provider 默认 model
    llm_timeout: float = 30.0
    # MiniMax OpenAI 兼容通道的 GroupId（仅 minimax 需要，其余忽略）。
    llm_minimax_group_id: str = ""

    # 企业微信 OAuth 真身份 + 微盘扫描（R6）。corp_id + app_secret 配齐才启用真实集成；
    # 否则降级（OAuth 端点返回未配置，扫描走注入的 fake/Null）。**secret 绝不外泄**。
    wecom_corp_id: str = ""
    wecom_agent_id: str = ""
    wecom_app_secret: str = ""
    wecom_redirect_uri: str = ""
    wecom_drive_base_url: str = "https://qyapi.weixin.qq.com"
    wecom_scan_page_size: int = 100
    wecom_timeout: float = 30.0
    # R7：开启后生命周期/复用通知按 wecom 渠道落库并由 worker 真实下发；默认关（仅 in_app）。
    wecom_notify_enabled: bool = False

    # ONLYOFFICE 真预览（R7）。enabled + document_server_url 配齐才出真实预览配置；
    # 否则预览入口返回 onlyoffice_not_configured（绝不回退泄露原文 URL）。jwt_secret 绝不外泄。
    onlyoffice_enabled: bool = False
    onlyoffice_document_server_url: str = ""
    # 平台对外基址（拼受控取件 URL 供 Document Server 回取）；空则用相对路径。
    onlyoffice_internal_base_url: str = ""
    onlyoffice_jwt_secret: str = ""
    # ONLYOFFICE 受控取件 token 的有效期（分钟）。
    onlyoffice_fetch_ttl_minutes: int = 30


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
