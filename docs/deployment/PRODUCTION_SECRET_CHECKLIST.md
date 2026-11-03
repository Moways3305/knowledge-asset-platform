# 生产 Secret / Config Checklist

> 本清单**只出现配置项名**，不出现任何值、示例真实 key、或 URL 中带 token 的内容。所有项的真实值经部署密钥注入，**绝不入仓库、绝不打印**。
>
> 配套：部署步骤 → [`PRODUCTION_DEPLOYMENT_RUNBOOK.md`](./PRODUCTION_DEPLOYMENT_RUNBOOK.md)；上线验证 → [`LIVE_SMOKE_CHECKLIST.md`](./LIVE_SMOKE_CHECKLIST.md)。项名权威来源：`backend/.env.example`、`backend/app/api/ops.py`（`/health/config`）、`backend/app/core/config.py`。

## 如何安全使用本清单

- 注入：Compose 插值项（如 `APP_ENV`、数据库/Redis 密码、worker 资源）放根 `.env`，服务集成项放 `backend/.env` 或部署平台；两者均不入仓库。Compose 显式 `environment` 优先于 `env_file`，只在后者改值不一定生效。配置时**填值**，但**不要回显**到聊天 / 报告 / CI log / 截图。
- 验证：只用「项名 + 布尔/状态」核对，例如：
  ```powershell
  # /health/config 只回布尔 / provider 名 / 缺失项名 / production_ready/blockers/warnings —— 安全可贴
  Invoke-WebRequest <prod-url>/health/config
  ```
- **不要**运行或粘贴完整 `docker compose config`：它会展开 `env_file`，把 `*_API_KEY` / `*_SECRET` / 连接串明文展开。只用 `docker compose config --services` / `--volumes`（只列名）或对 `docker-compose.yml` 定向 `Select-String`。

## 状态标记说明

- **required (prod)**：生产必须正确配置；多数缺失会触发 `/health/config.production_blockers`。
- **conditional**：仅当对应集成启用时才必须（启用但缺关键项 → 可能 blocker / missing_config）。
- **optional**：不配走安全默认 / 降级；可能触发 `production_warnings`。
- **blocker / warning / missing_config** 列：对应 `/health/config` 中该项归类（**仅 `APP_ENV=prod` 评估 blocker**；非 prod 恒空，避免误判本地开发）。

---

## 1. App / Session / CSRF / Auth Guard

| 配置项名 | 状态 | /health/config | 缺失 / 误配症状 |
|---|---|---|---|
| `APP_ENV` | required (prod) | 驱动 `app_env` + 是否评估 blockers | Compose 从根配置取值；示例为 dev，仅供本地。生产必须设 prod，启用生产 Secure cookie 与配置阻断检查 |
| `APP_NAME` | optional | — | 仅展示用 |
| `LOG_LEVEL` | optional | — | 默认 INFO |
| `SESSION_COOKIE_SECURE` | required (prod，建议留空) | blocker `SESSION_COOKIE_SECURE`（prod 下显式 `false` 时） | prod 运行时强制 Secure；显式置 `false` 会被诚实标记为 blocker（运行时仍安全），建议删除该项让其按环境推断 |
| `AUTH_ATTEMPT_HASH_SECRET` | required (prod) | blocker `AUTH_ATTEMPT_HASH_SECRET` | 缺失则登录失败风控 HMAC 回退可预测常量；prod 报 blocker |
| `CSRF_TOKEN_SECRET` | required (prod) | blocker `CSRF_TOKEN_SECRET` | 缺失则 CSRF 签名 key 可预测；prod 报 blocker |
| `AUTH_FAILED_WINDOW_MINUTES` | optional | — | 缺省安全默认；`<1` 由服务层钳制 |
| `AUTH_MAX_FAILED_ATTEMPTS` | optional | — | 同上 |
| `AUTH_LOCKOUT_MINUTES` | optional | — | 同上 |
| `AUTH_IP_FAILED_WINDOW_MINUTES` | optional | — | 同上 |
| `AUTH_IP_MAX_FAILED_ATTEMPTS` | optional | — | 同上 |
| `CSRF_TOKEN_TTL_MINUTES` | optional | — | `<1` 回退默认 |

## 2. Database / Redis / Celery

| 配置项名 | 状态 | /health/config | 缺失 / 误配症状 |
|---|---|---|---|
| `DATABASE_URL` | required | 经 `/health/ready` 的 `checks.database` 间接反映 | 缺失 / 不可达 → `/health/ready` 503、backend 起不来 |
| `REDIS_URL` | required (async) | `/health/ready` 的 `checks.redis` | async 模式缺失 → 就绪失败、worker/beat 无 broker |
| `POSTGRES_PASSWORD` | required (compose) | — | 根配置必填；创建 PostgreSQL 时使用，后端连接会正确编码。已有数据卷不能仅改变量而不同步数据库角色密码 |
| `REDIS_PASSWORD` | required (compose) | — | compose 变量（根 `./.env`）：给 Redis 加 `--requirepass` 并拼进 `REDIS_URL`。**缺失即 compose fail-fast 拒绝启动**（`${REDIS_PASSWORD:?...}`），不会静默起无密码 Redis。上线务必改强随机值 |
| `CELERY_BROKER_URL` | optional | — | 缺省回退 `REDIS_URL` |
| `CELERY_RESULT_BACKEND` | optional | — | 缺省回退 `REDIS_URL` |
| `CELERY_TASK_ALWAYS_EAGER` | required (prod = false) | blocker `CELERY_TASK_ALWAYS_EAGER`（prod 下为 true 时）；`integrations.celery_eager` | true 则作业内联同步、阻塞请求、丢异步语义；prod 报 blocker |
| `STORAGE_ROOT` | required | — | backend/worker/ocr_worker 须指向同一份共享存储；不一致 → 异步处理读不到上传字节、摘要为空 |

## 3. WeKnora 知识底座

| 配置项名 | 状态 | /health/config | 缺失 / 误配症状 |
|---|---|---|---|
| `WEKNORA_BASE_URL` | conditional | `integrations.weknora_enabled` | 与 api_key 任一缺失 → 未启用 → warning `WEKNORA_NOT_CONFIGURED`，检索/索引降级 |
| `WEKNORA_API_KEY` | conditional | `integrations.weknora_enabled` | 同上；**绝不外泄** |
| 平台默认 embedding 模型（DB，非 env） | conditional (启用则 required) | blocker + missing_config `WEKNORA_DEFAULT_EMBEDDING_MODEL` | PBC-38：启用 WeKnora 但未在「模型配置中心」配置平台默认 embedding → 建库 fail-closed |
| `WEKNORA_DEFAULT_KNOWLEDGE_QA_MODEL` | required when WeKnora enabled (DB) | blocker + missing_config | 模型配置中心的底座兼容 LLM 默认槽位未设置；它不代替 KAP 内容生成/业务问答模型 |
| `WEKNORA_MODEL_REF_SECRET` | conditional (启用则 required) | blocker + missing_config `WEKNORA_MODEL_REF_SECRET` | 启用但缺 → model_ref HMAC 回退常量、不稳定；prod 报 blocker |
| `WEKNORA_EMBEDDING_MODEL_ID` | **DEPRECATED legacy** | — (不再作为 blocker) | PBC-38：仅历史兼容 / 测试隔离；生产改用模型配置中心，留空即可 |
| `WEKNORA_CHAT_MODEL_ID` | DEPRECATED legacy | — | 同上，不再推荐生产配置 |
| `WEKNORA_RERANK_MODEL_ID` | DEPRECATED legacy | — | 同上，不再推荐生产配置 |
| `WEKNORA_MULTIMODAL_MODEL_ID` | optional | — | 同上 |
| `WEKNORA_SUMMARY_MODEL_ID` | optional | — | 当前不参与建库，仅兼容保留 |
| `WEKNORA_TENANT_ID` | optional | — | 按底座需要 |
| `WEKNORA_TIMEOUT` | optional | — | 缺省 30s |

## 4. KAP 内容生成与业务问答模型

优先使用模型管理页面保存的产品配置，API 地址与 API key 加密落库。产品配置存在后不回退旧 `LLM_*` 环境默认；只有尚未建立产品配置的部署兼容环境方式。判断是否配置成功看 `integrations.external_llm_configured`（兼容别名 `kap_generation_model_configured`），不能只看旧 `llm_enabled`。

| 配置项名 | 状态 | /health/config | 缺失 / 误配症状 |
|---|---|---|---|
| `GENERATION_MODEL_ENCRYPTION_KEY` | conditional (产品模型配置) | 产品配置存在但缺少时 blocker + missing_config | 保存/解密模型连接所需的独立稳定 Fernet 密钥，必须随配置备份，不能每次部署重新生成 |
| `LLM_PROVIDER` | legacy fallback | `integrations.llm_provider`（provider 名安全，非密钥） | 仅无产品配置时使用；整体无可用生成模型时 warning `EXTERNAL_LLM_NOT_CONFIGURED` |
| `LLM_API_KEY` | conditional | `integrations.llm_enabled` | 同上；**绝不外泄** |
| `LLM_BASE_URL` | optional | — | 缺省走 provider 注册表默认 |
| `LLM_MODEL` | optional | — | 缺省走默认 |
| `LLM_TIMEOUT` | optional | — | 缺省 30s |
| `LLM_MINIMAX_GROUP_ID` | conditional | — | 仅 MiniMax provider 需要 |

## 5. WeCom OAuth / Scan / Notify

| 配置项名 | 状态 | /health/config | 缺失 / 误配症状 |
|---|---|---|---|
| `WECOM_CORP_ID` | conditional | `integrations.wecom_enabled`；notify 启用缺则 blocker/missing `WECOM_CORP_ID/WECOM_APP_SECRET` | 缺失 → OAuth/扫描未启用、企微登录不可用 |
| `WECOM_APP_SECRET` | conditional | 同上 | 同上；**绝不外泄** |
| `WECOM_AGENT_ID` | conditional | — | 按企微应用需要 |
| `WECOM_REDIRECT_URI` | conditional | — | OAuth callback 与企微登记 / 可信回调域名须一致，否则 callback 失败 |
| `WECOM_DRIVE_BASE_URL` | optional | — | 缺省企微 API 域 |
| `WECOM_SCAN_PAGE_SIZE` | optional | — | 缺省 100 |
| `WECOM_TIMEOUT` | optional | — | 缺省 30s |
| `WECOM_NOTIFY_ENABLED` | optional (默认 false) | `integrations.wecom_notify_enabled`；启用缺 corp/secret → blocker | 关 → 仅本地 in_app 通知；开但缺 corp/secret → 通知无法下发 |

## 6. ONLYOFFICE

| 配置项名 | 状态 | /health/config | 缺失 / 误配症状 |
|---|---|---|---|
| `ONLYOFFICE_ENABLED` | optional (默认 false) | `integrations.onlyoffice_enabled` | 关 → 预览安全降级，不泄露原文 URL |
| `ONLYOFFICE_DOCUMENT_SERVER_URL` | conditional (启用则 required) | blocker + missing_config | 启用但缺 → 预览不可用 |
| `ONLYOFFICE_JWT_SECRET` | conditional (启用则 required) | blocker | 启用但缺 → Document Server 通常强制 JWT，未签名 config 被拒；**绝不外泄** |
| `ONLYOFFICE_INTERNAL_BASE_URL` | conditional | 缺失/非法时 blocker | 用于 Document Server 回取字节；地址须有效且服务可达 |
| `ONLYOFFICE_ORIGIN` | conditional (根配置) | 缺失、非法或与 Document Server origin 不一致时 blocker | 浏览器 CSP 允许的文档服务器 origin，由 Compose 同时注入前后端 |
| `ONLYOFFICE_FETCH_TTL_MINUTES` | optional | — | 缺省 30 分钟 |

## 7. 上传字节存储

| 配置项名 | 状态 | /health/config | 缺失 / 误配症状 |
|---|---|---|---|
| `STORAGE_ROOT` | required | — | 见 §2；生产使用共享持久卷，存储引用 / 路径保持 server-only，不进 API 响应 |

> 当前仅实现 `LocalFileStorage`，没有可配置即用的 S3/OSS/MinIO 适配。须备份共享卷及数据库；替换存储需另行开发与验证。

## 8. Frontend / Reverse Proxy

| 项 | 状态 | 说明 |
|---|---|---|
| TLS 终止层 | required (prod) | HTTPS 终止于 `frontend` nginx 之前；prod cookie 强制 Secure，纯 HTTP 入口无法登录 |
| `X-Forwarded-For` / `X-Forwarded-Proto` / `Host` 透传 | required (prod) | 前置反代与 `deploy/nginx.conf.template`（server 块；http 级见 `deploy/nginx-main.conf`）都须透传；`X-Forwarded-Proto` 影响 HTTPS 识别 |
| `X-Trace-Id` 透传 | recommended | 保链路可观测；trace_id 仅作关联，非鉴权凭证 |
| 企微可信回调域名 | conditional | 启用企微 OAuth 时须在企微后台登记生产域名，与 `WECOM_REDIRECT_URI` 一致 |

---

## 9. MCP OAuth（可选）

`MCP_OAUTH_ENABLED` 默认关闭。开启时必须配置独立、稳定的
`MCP_OAUTH_CLIENT_ENCRYPTION_KEY`，缺失或无效会在启动阶段拒绝启用，不能仅依赖
`/health/config` 的 blockers 判断。公开 origin、代理路径和密钥备份见
[MCP OAuth 部署](../api/mcp-oauth.md)；凭证只读/操作权限见 [MCP 操作接口](../mcp-operations.md)。

## 生产 blocker / warning 速查

以下按 `backend/app/api/ops.py` 的 `/health/config` 分类；这不是所有启动校验和外部连通性检查的替代。

- 通用 blockers：`CELERY_TASK_ALWAYS_EAGER`、`SESSION_COOKIE_SECURE`、`AUTH_ATTEMPT_HASH_SECRET`、`CSRF_TOKEN_SECRET`。
- WeKnora 启用时：`WEKNORA_DEFAULT_EMBEDDING_MODEL`、`WEKNORA_DEFAULT_KNOWLEDGE_QA_MODEL`、`WEKNORA_MODEL_REF_SECRET`。
- ONLYOFFICE 启用时：`ONLYOFFICE_DOCUMENT_SERVER_URL`、`ONLYOFFICE_DOCUMENT_SERVER_URL_ORIGIN`、`ONLYOFFICE_INTERNAL_BASE_URL`、`ONLYOFFICE_INTERNAL_BASE_URL_INVALID`、`ONLYOFFICE_ORIGIN`、`ONLYOFFICE_ORIGIN_INVALID`、`ONLYOFFICE_ORIGIN_MISMATCH`、`ONLYOFFICE_JWT_SECRET`。
- 企微通知启用且缺凭证：`WECOM_CORP_ID/WECOM_APP_SECRET`。
- 存在产品模型配置但缺加密密钥：`GENERATION_MODEL_ENCRYPTION_KEY`。
- warnings：`EXTERNAL_LLM_NOT_CONFIGURED`、`WEKNORA_NOT_CONFIGURED`。旧 `llm_enabled=false` 不表示产品模型未配置，应结合 `external_llm_configured`。
- `missing_config` 是启用但缺关键配置的子集，不含全部格式/一致性错误；不能代替 `production_blockers`。`production_ready=true` 也不代替业务验收。
