# 生产 Secret / Config Checklist

> 本清单**只出现配置项名**，不出现任何值、示例真实 key、或 URL 中带 token 的内容。所有项的真实值经部署密钥注入，**绝不入仓库、绝不打印**。
>
> 配套：部署步骤 → [`PRODUCTION_DEPLOYMENT_RUNBOOK.md`](./PRODUCTION_DEPLOYMENT_RUNBOOK.md)；上线验证 → [`LIVE_SMOKE_CHECKLIST.md`](./LIVE_SMOKE_CHECKLIST.md)。项名权威来源：`backend/.env.example`、`backend/app/api/ops.py`（`/health/config`）、`backend/app/core/config.py`。

## 如何安全使用本清单

- 注入：在部署平台 / `backend/.env`（不入仓库）里**填值**，但**不要回显**到聊天 / 报告 / CI log / 截图。
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
| `APP_ENV` | required (prod) | 驱动 `app_env` + 是否评估 blockers | 非 `prod` 则不强制 Secure cookie、不评估 blockers，安全守卫不生效 |
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
| `REDIS_PASSWORD` | required (compose) | — | compose 变量（根 `./.env`）：给 Redis 加 `--requirepass` 并拼进 `REDIS_URL`。**缺失即 compose fail-fast 拒绝启动**（`${REDIS_PASSWORD:?...}`），不会静默起无密码 Redis。上线务必改强随机值 |
| `CELERY_BROKER_URL` | optional | — | 缺省回退 `REDIS_URL` |
| `CELERY_RESULT_BACKEND` | optional | — | 缺省回退 `REDIS_URL` |
| `CELERY_TASK_ALWAYS_EAGER` | required (prod = false) | blocker `CELERY_TASK_ALWAYS_EAGER`（prod 下为 true 时）；`integrations.celery_eager` | true 则作业内联同步、阻塞请求、丢异步语义；prod 报 blocker |
| `STORAGE_ROOT` | required | — | backend/worker 须指向同一份共享存储；不一致 → 异步处理读不到上传字节、摘要为空 |

## 3. WeKnora 知识底座

| 配置项名 | 状态 | /health/config | 缺失 / 误配症状 |
|---|---|---|---|
| `WEKNORA_BASE_URL` | conditional | `integrations.weknora_enabled` | 与 api_key 任一缺失 → 未启用 → warning `WEKNORA_NOT_CONFIGURED`，检索/索引降级 |
| `WEKNORA_API_KEY` | conditional | `integrations.weknora_enabled` | 同上；**绝不外泄** |
| `WEKNORA_EMBEDDING_MODEL_ID` | conditional (启用则 required) | blocker + missing_config `WEKNORA_EMBEDDING_MODEL_ID` | 启用 WeKnora 但缺 → KB 建库不完整、索引失败 |
| `WEKNORA_MODEL_REF_SECRET` | conditional (启用则 required) | blocker + missing_config `WEKNORA_MODEL_REF_SECRET` | 启用但缺 → model_ref HMAC 回退常量、不稳定；prod 报 blocker |
| `WEKNORA_CHAT_MODEL_ID` | optional | — | 配则随 KB 初始化 |
| `WEKNORA_RERANK_MODEL_ID` | optional | — | 同上 |
| `WEKNORA_MULTIMODAL_MODEL_ID` | optional | — | 同上 |
| `WEKNORA_SUMMARY_MODEL_ID` | optional | — | 当前不参与建库，仅兼容保留 |
| `WEKNORA_TENANT_ID` | optional | — | 按底座需要 |
| `WEKNORA_TIMEOUT` | optional | — | 缺省 30s |

## 4. External LLM

| 配置项名 | 状态 | /health/config | 缺失 / 误配症状 |
|---|---|---|---|
| `LLM_PROVIDER` | conditional | `integrations.llm_provider`（provider 名安全，非密钥） | 与 api_key 任一缺失 → warning `LLM_NOT_CONFIGURED`，内容处理降级为确定性草稿 |
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
| `ONLYOFFICE_INTERNAL_BASE_URL` | conditional | — | 用于拼受控取件 URL 供 Document Server 回取 |
| `ONLYOFFICE_FETCH_TTL_MINUTES` | optional | — | 缺省 30 分钟 |

## 7. Storage / Object Storage

| 配置项名 | 状态 | /health/config | 缺失 / 误配症状 |
|---|---|---|---|
| `STORAGE_ROOT` | required | — | 见 §2；生产平替对象存储时，存储引用 / 路径保持 server-only，不进 API 响应 |

> 对象存储（S3/OSS/MinIO）平替经可插拔 `StorageBackend`；其凭证项名取决于所选后端，注入规则同上（不入仓库、不打印）。本仓库默认本地共享卷。

## 8. Frontend / Reverse Proxy

| 项 | 状态 | 说明 |
|---|---|---|
| TLS 终止层 | required (prod) | HTTPS 终止于 `frontend` nginx 之前；prod cookie 强制 Secure，纯 HTTP 入口无法登录 |
| `X-Forwarded-For` / `X-Forwarded-Proto` / `Host` 透传 | required (prod) | 前置反代与 `deploy/nginx.conf.template`（server 块；http 级见 `deploy/nginx-main.conf`）都须透传；`X-Forwarded-Proto` 影响 HTTPS 识别 |
| `X-Trace-Id` 透传 | recommended | 保链路可观测；trace_id 仅作关联，非鉴权凭证 |
| 企微可信回调域名 | conditional | 启用企微 OAuth 时须在企微后台登记生产域名，与 `WECOM_REDIRECT_URI` 一致 |

---

## 生产 blocker / warning 速查（与 `/health/config` 一致）

- **blockers（prod 必须清零）**：`CELERY_TASK_ALWAYS_EAGER`、`SESSION_COOKIE_SECURE`（显式 false 时）、`AUTH_ATTEMPT_HASH_SECRET`、`CSRF_TOKEN_SECRET`、`WEKNORA_EMBEDDING_MODEL_ID`、`WEKNORA_MODEL_REF_SECRET`（WeKnora 启用时）、`ONLYOFFICE_DOCUMENT_SERVER_URL`、`ONLYOFFICE_JWT_SECRET`（ONLYOFFICE 启用时）、`WECOM_CORP_ID/WECOM_APP_SECRET`（企微通知启用时）。
- **warnings（不阻断，建议确认）**：`LLM_NOT_CONFIGURED`、`WEKNORA_NOT_CONFIGURED`。
- **missing_config（启用但缺关键值的项名）**：`WEKNORA_EMBEDDING_MODEL_ID`、`WEKNORA_MODEL_REF_SECRET`、`ONLYOFFICE_DOCUMENT_SERVER_URL`、`WECOM_CORP_ID/WECOM_APP_SECRET`。
