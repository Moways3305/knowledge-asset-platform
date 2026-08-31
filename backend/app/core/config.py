"""Application configuration via environment variables.

Uses pydantic-settings. No secrets are hardcoded; values come from the
environment or a local `.env` file (see `.env.example`).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
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

    # 会话 / OAuth state cookie 的 Secure 标志。
    # None = 按环境推断：prod 强制 Secure=True（HTTPS-only），非 prod 默认 False（便于
    # http://localhost 调试）。prod 即使显式置 False 也不在运行时退让（见
    # `session_cookie_secure()`）；但显式 false 会被 `/health/config` 标记为生产 blocker，
    # 提示运维改回安全值。
    session_cookie_secure: bool | None = None

    # 登录失败风控。`auth_attempt_hash_secret` 仅用于对登录标识 / IP 做 HMAC
    # 不可逆 hash（绝不进响应/审计/前端）；prod 必须配置（缺失 → /health/config blocker），
    # 非 prod 空值回退稳定常量。阈值/窗口允许 env 调整，服务层对 <1 的非法值钳制。
    auth_attempt_hash_secret: str = ""
    auth_failed_window_minutes: int = 15
    auth_max_failed_attempts: int = 5
    auth_lockout_minutes: int = 15
    auth_ip_failed_window_minutes: int = 15
    auth_ip_max_failed_attempts: int = 30

    # CSRF 防护。`csrf_token_secret` 仅用于对无状态 CSRF token 做 HMAC 签名
    # （绝不进响应/审计/前端/日志）；prod 必须配置（缺失 → /health/config blocker），
    # 非 prod 空值回退稳定常量。csrf_token_ttl_minutes 控制签发 token 有效期。
    csrf_token_secret: str = ""
    csrf_token_ttl_minutes: int = 720

    # PostgreSQL async connection string, e.g.
    # postgresql+asyncpg://dev:devpassword@localhost:5432/knowledge_platform
    # 若 DATABASE_URL 的密码含 URL 特殊字符（如 % @ / # 等），可改用独立的
    # POSTGRES_PASSWORD 环境变量提供原始密码——后端会用 sqlalchemy.engine.URL.create
    # 正确编码后注入 DATABASE_URL，避免 URL 解析错乱。二者同时配置时后者优先。
    database_url: str = "postgresql+asyncpg://dev:devpassword@localhost:5432/knowledge_platform"
    # 独立数据库密码（可选）。非空时覆盖 database_url 中的密码部分。
    # 用于密码含 URL 特殊字符（如 %）的场景，避免在 DATABASE_URL 中拼接。
    postgres_password: str = ""

    @model_validator(mode="after")
    def _inject_postgres_password(self) -> Settings:
        """POSTGRES_PASSWORD 非空时，对其做 URL 编码后替换 DATABASE_URL 中的占位符。

        密码里的特殊字符（% @ / # 等）必须经过 URL 编码才能安全放入 URL，
        否则 asyncpg 解析 URL 时会误解（如 %40 -> @）。quote() 只做一次编码，
        asyncpg 解码后还原为原始密码值。
        """
        if self.postgres_password:
            from urllib.parse import quote

            self.database_url = self.database_url.replace(
                "__PG_PASSWORD__", quote(self.postgres_password, safe="")
            )
        return self

    # 连接池（生产 PostgreSQL engine）：常驻连接数 / 峰值溢出 / 回收周期（秒，防陈旧连接）。
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle: int = 3600

    # 会话有效期（小时）。决定 user_sessions.expires_at 与会话 cookie max-age。
    session_ttl_hours: int = 12

    # Redis URL for Celery broker / result backend.
    redis_url: str = "redis://localhost:6379/0"

    # Celery 异步治理作业。broker / backend 缺省回退到 redis_url。
    # celery_task_always_eager：默认 True——无 worker 也能跑（入库处理内联同步执行，
    # API 开箱即用）；生产接 worker 时设为 false 启用真正异步（work 排队到 broker，
    # 无 worker 时任务保持 processing/pending）。
    celery_broker_url: str = ""
    celery_result_backend: str = ""
    celery_task_always_eager: bool = True
    celery_default_queue: str = "default"
    celery_ocr_queue: str = "ocr"

    # 入库业务租约。worker 进程被 OOM/SIGKILL 时 Python finally 不会执行，因此由
    # default 队列上的扫描任务按 heartbeat 判定孤儿，并做有限指数退避恢复。
    ingest_lease_timeout_seconds: int = 900
    ingest_recovery_scan_seconds: int = 60
    ingest_recovery_base_delay_seconds: int = 60
    ingest_recovery_max_attempts: int = 3

    # 受控本地文件存储根目录。上传的文件字节写入此处；
    # 内部存储引用（server-only）不进入任何 API 响应。生产应替换为对象存储后端。
    storage_root: str = "./_local_storage"

    # WeKnora 知识底座。base_url + api_key 都配置时启用真实集成；否则降级跳过
    # 索引（dev 无 WeKnora 仍可起 app / confirm）。api_key（sk- 前缀）绝不外泄。
    weknora_base_url: str = ""
    weknora_api_key: str = ""
    # 建库 + 初始化。embedding 必需（全平台统一、建库后不可改）；chat / rerank /
    # multimodal 可选，配置则随 KB 初始化（POST /initialization/initialize/:kb_id）写入，
    # 确保 KB 一建即可用，而非只有空 embedding。模型 id 是 WeKnora 已注册模型的引用，
    # 非密钥；平台只引用、不在此创建模型（模型 CRUD 由 WeKnora 侧管理）。
    weknora_embedding_model_id: str = ""
    weknora_chat_model_id: str = ""
    weknora_rerank_model_id: str = ""
    weknora_multimodal_model_id: str = ""
    # 注意：summary 模型当前**不参与**建库 / 初始化（摘要走平台外部 LLM 内容处理链，
    # 不用 WeKnora summary 模型）。保留 env 仅为兼容，建库时不传。
    weknora_summary_model_id: str = ""
    weknora_tenant_id: str = ""
    weknora_timeout: float = 30.0
    # 索引中断判定必须同时满足最小时长与连续对账失败次数，避免把底座仍在正常
    # pending/processing 的长文档误判为失败。运维可通过环境变量集中调整。
    index_interrupted_min_age_minutes: int = 30
    index_interrupted_reconcile_failures: int = 2
    # 模型配置中心把 WeKnora server-only model_id 经单向 HMAC 映射成对前端不可逆的
    # model_ref。该 secret 仅后端可读、用于 HMAC key；未配置时回退到稳定常量（仍单向，
    # 因 model_id 本身是 server-only 高熵标识）。不入响应 / 审计 / 前端。
    weknora_model_ref_secret: str = ""

    # 外部 LLM 内容处理。统一方案：选一个 active provider（`LLM_PROVIDER`）+ 其
    # `LLM_API_KEY`；base_url / model 缺省走 provider 注册表默认值，可由 env 覆盖。
    # provider + api_key 都配置才启用，否则内容处理降级到确定性草稿。api_key 绝不外泄。
    llm_provider: str = ""  # deepseek / kimi / qwen / glm / minimax / openai / custom
    llm_api_key: str = ""
    llm_base_url: str = ""  # 覆盖 provider 默认 base_url（custom 必填）
    llm_model: str = ""  # 覆盖 provider 默认 model
    llm_timeout: float = 30.0
    # MiniMax OpenAI 兼容通道的 GroupId（仅 minimax 需要，其余忽略）。
    llm_minimax_group_id: str = ""
    # KAP 内容生成模型（标题 / 摘要 / 标签建议）对前端暴露的安全 model_ref HMAC key。
    # 不用于 WeKnora 知识库模型；缺省仅本地/测试使用稳定回退。
    generation_model_ref_secret: str = ""
    # Fernet key（urlsafe base64 编码的 32-byte key），只用于内容生成模型敏感配置加密。
    # 生产必须显式配置；不入库、不进响应/日志。
    generation_model_encryption_key: str = ""

    # 入库 OCR：只调用容器内 Tesseract，不把原文发往外部视觉模型。
    ocr_enabled: bool = True
    ocr_command: str = "tesseract"
    ocr_languages: str = "chi_sim+eng"
    ocr_min_confidence: float = 45.0
    ocr_render_timeout_seconds: int = 45
    ocr_page_timeout_seconds: int = 60
    ocr_document_timeout_seconds: int = 600
    ocr_max_pages: int = 100
    ocr_max_image_bytes: int = 25 * 1024 * 1024
    ocr_max_rendered_pixels: int = 20_000_000
    ocr_max_total_pixels: int = 100_000_000

    # 企业微信 OAuth 真身份 + 微盘扫描。corp_id + app_secret 配齐才启用真实集成；
    # 否则降级（OAuth 端点返回未配置，扫描走注入的 fake/Null）。**secret 绝不外泄**。
    wecom_corp_id: str = ""
    wecom_agent_id: str = ""
    wecom_app_secret: str = ""
    wecom_redirect_uri: str = ""
    wecom_drive_base_url: str = "https://qyapi.weixin.qq.com"
    wecom_scan_page_size: int = 100
    wecom_timeout: float = 30.0
    # 开启后生命周期/复用通知按 wecom 渠道落库并由 worker 真实下发；默认关（仅 in_app）。
    wecom_notify_enabled: bool = False

    # ONLYOFFICE 真预览。enabled + document_server_url 配齐才出真实预览配置；
    # 否则预览入口返回 onlyoffice_not_configured（绝不回退泄露原文 URL）。jwt_secret 绝不外泄。
    onlyoffice_enabled: bool = False
    onlyoffice_document_server_url: str = ""
    # 前端 CSP 使用的浏览器可达 origin；仅供安全配置一致性诊断，不进入业务响应。
    onlyoffice_origin: str = ""
    # 平台对外基址（拼受控取件 URL 供 Document Server 回取）；空则用相对路径。
    onlyoffice_internal_base_url: str = ""
    onlyoffice_jwt_secret: str = ""
    # ONLYOFFICE 受控取件 token 的有效期（分钟）。
    onlyoffice_fetch_ttl_minutes: int = 30

    # WorkBuddy Connector 共享安装产物目录。目录内 manifest.json 只描述版本、平台、
    # 架构、签名状态和 sha256；绝不含用户 token、身份或私有下载地址。
    # WorkBuddy 配置使用的服务器受控公网 origin。生产必须显式配置为无 path/query/
    # fragment 的 HTTPS origin；不从 Host / Forwarded / request.base_url 推导。
    kap_public_base_url: str = "http://localhost:8000"
    workbuddy_connector_artifact_root: str = "./_connector_artifacts"
    workbuddy_connector_manifest: str = "manifest.json"
    # 是否允许分发未签名的企业内部版。所有环境默认关闭，只有显式 true 才允许。
    workbuddy_connector_allow_internal: bool = False

    # D1 阶段4（Small-to-Big）：子块召回后按父文件聚合，取治理文本全文给 Agent。
    # agent_parent_doc_limit：最多取几篇父文件全文（≤N，默认 3，可配）。
    # agent_parent_doc_char_limit：单篇字符上限（截头），防止大文件撑爆 Agent 上下文。
    agent_parent_doc_limit: int = 3
    agent_parent_doc_char_limit: int = 16000


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()


def session_cookie_secure(settings: Settings | None = None) -> bool:
    """会话 / OAuth state cookie 的**有效** Secure 标志。

    - `app_env == "prod"`：强制返回 True（HTTPS-only），即使 `SESSION_COOKIE_SECURE=false`
      被显式注入也不退让——生产 cookie 永远只走 HTTPS。
    - 非 prod：读 `session_cookie_secure`，未配置（None）默认 False，便于本地 http://localhost。
    """
    s = settings or get_settings()
    if s.app_env == "prod":
        return True
    return bool(s.session_cookie_secure) if s.session_cookie_secure is not None else False


def session_cookie_secure_misconfigured(settings: Settings | None = None) -> bool:
    """prod 下运维显式把 `SESSION_COOKIE_SECURE=false` → 生产 blocker 信号。

    运行时 cookie 仍被 `session_cookie_secure()` 强制为安全；此函数仅用于 `/health/config`
    向运维诚实暴露「你的显式配置不安全、已被强制覆盖」，提示改回 true / 删除该项。
    """
    s = settings or get_settings()
    return s.app_env == "prod" and s.session_cookie_secure is False
