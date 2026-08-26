# 生产部署 Runbook

> 适用范围：把本仓库的 AI 知识资产平台从「代码 + 镜像」安全部署到一个**已具备真实域名 / TLS / 密钥注入**的运行环境，并完成上线前最小验证。
>
> **本文是仓库内的可执行部署手册；公网上线本身仍需运维执行。** 真实域名、TLS 证书申请、DNS、云密钥注入、对象存储开通、镜像推送、云监控接入是实际运维动作，需在你的目标环境按本手册执行。
>
> 配套文档：
> - 安全配置清单 → [`PRODUCTION_SECRET_CHECKLIST.md`](./PRODUCTION_SECRET_CHECKLIST.md)（只列项名，不列值）
> - Live smoke 清单 → [`LIVE_SMOKE_CHECKLIST.md`](./LIVE_SMOKE_CHECKLIST.md)
> - 安全与运维背景 → `backend/README.md`、根 `README.md`

---

## 0. 安全红线（每一步都适用）

- **绝不**在聊天 / 完成报告 / CI log / 截图中打印完整 `.env` 内容或 `docker compose config` 的完整输出（后者会展开 `env_file` 把真实密钥明文展开）。
- 验证配置时只允许出现：配置项名、provider 名、布尔 / 枚举状态、安全 endpoint 路径、占位符（如 `<prod-url>`、`<image-tag>`）。
- **绝不**输出：真实 secret / token / cookie / session token / OAuth state / CSRF token、`DATABASE_URL` / `REDIS_URL` / broker URL、对象存储签名 URL、WeKnora kb/doc/model id、原文 / chunk / 业务文件名。
- 需要看 compose 结构时，用 `docker compose config --services` / `--volumes`（只列名）或对 `docker-compose.yml` 做定向 `Select-String`，**不要**跑会展开 env 的完整 `docker compose config`。

---

## 1. 上线前准备（Pre-flight）

### 1.1 版本一致性

- [ ] 确认要部署的 **git commit**：`git rev-parse HEAD`（记录到发布单）。
- [ ] 确认镜像 **tag** 与该 commit 对应；`backend` / `worker` / `beat` / `migrate` / `frontend` 五个角色**必须来自同一代码版本**。
  - 本仓库 `backend` / `worker` / `beat` / `migrate` 共用 `./backend` 镜像（compose 中同一 `build: ./backend`，仅 `command` 不同）；`frontend` 用 `Dockerfile.frontend` 多阶段构建。
  - 因此「同版本」= 用同一次 `docker compose build`（或同一 commit 的 CI 构建）产出的镜像，不要混用旧镜像。
- [ ] 确认 **migration head** 与该 commit 一致：迁移文件在 `backend/alembic/versions/`，最新 head 应是该 commit 的最后一个迁移（部署时由 `migrate` 服务执行 `alembic upgrade head`）。

### 1.2 运行模式

- [ ] `CELERY_TASK_ALWAYS_EAGER=false`（生产必须接真实 worker；eager 会让长作业阻塞请求、丢异步语义）。`APP_ENV=prod` 下若仍为 `true`，`/health/config.production_blockers` 会报 `CELERY_TASK_ALWAYS_EAGER`。
- [ ] **worker 与 beat 必须真实运行**（不是只起 backend）：
  - `worker`：入库处理 / 解析对账 / 归档扫描 / 升格推荐 / 通知下发；
  - `beat`：上述作业的定时调度。
- [ ] `APP_ENV=prod`（启用 prod 守卫：cookie 强制 Secure、blockers 仅在 prod 评估）。

### 1.3 共享存储

- [ ] 确认 backend 与 worker 共享同一份上传字节存储。本仓库 compose 用命名卷 `upload_storage:/data/uploads` 同时挂到 backend 与 worker，并经 `&backend-env` 锚点统一 `STORAGE_ROOT=/data/uploads`。
  - 安全验证（不展开 env）：
    ```powershell
    Select-String -Path docker-compose.yml -Pattern 'upload_storage:/data/uploads'   # 应命中 backend + worker 两行
    Select-String -Path docker-compose.yml -Pattern 'STORAGE_ROOT:\s*/data/uploads'
    ```
- [ ] 生产可把存储平替为对象存储 / 共享持久卷（S3 / OSS / MinIO），但 `StorageBackend` 边界保持 server-only（存储引用 / 路径绝不进 API 响应）。
- [ ] WorkBuddy Connector 生产制品使用
  [`docker-compose.prod.yml`](../../docker-compose.prod.yml) 将宿主机
  `/data/kap/workbuddy-connectors` 只读挂载到 `backend`；`worker`、`beat`、`frontend`、
  `postgres`、`redis` 不得访问。下载、校验、原子切换、回滚和双身份烟测见
  [`WORKBUDDY_CONNECTOR_RELEASE.md`](./WORKBUDDY_CONNECTOR_RELEASE.md)。

### 1.4 外部依赖连通性（按启用情况）

逐项确认网络可达 + 凭证已注入（**只确认连通与项名，不打印值**）：

- [ ] 数据库（PostgreSQL，async 驱动）
- [ ] Redis（Celery broker / result backend）
- [ ] WeKnora 知识底座（启用时）
- [ ] 外部 LLM provider（启用时）
- [ ] 企业微信 OAuth / 微盘扫描 / 通知（启用时）
- [ ] ONLYOFFICE Document Server（启用时）
- [ ] 反向代理 / TLS 终止层

详细项名与「缺失症状」见 [`PRODUCTION_SECRET_CHECKLIST.md`](./PRODUCTION_SECRET_CHECKLIST.md)。

---

## 2. 部署顺序（Deploy）

> 顺序要点：**先迁移、再起服务、最后放流量并验证**。迁移只在一处执行，避免多副本并发迁移。

1. **拉取 / 构建镜像**
   - CI 推送：`docker pull <registry>/<image>:<image-tag>`（五角色同 tag）。
   - 单机自建：`docker compose build`。
2. **备份数据库**（迁移前必做）
   - 执行你环境的 PG 备份（如 `pg_dump`）。**备份产物含业务数据，按密级存放，不入仓库 / 不贴日志。**
   - 记录备份位置与时间到发布单。
3. **运行 migration**
   - 本仓库由一次性 `migrate` 服务执行 `python -m alembic upgrade head`；`backend` / `worker` / `beat` 依赖其 `service_completed_successfully` 才启动。
   - 不要手动在多个副本各自 `alembic upgrade`。
4. **本版本首次上线时回填 L3/L4 完整授权摘要**
   - 先 dry-run；输出只有计数与前后长度，不含资产 ID、普通摘要或脱敏摘要正文：
     ```powershell
     docker compose run --rm backend python -m app.commands.backfill_authorized_summaries
     ```
   - 核对 `pending`（缺少普通详细摘要、不能伪造）与 `regenerated` 后显式应用：
     ```powershell
     docker compose run --rm backend python -m app.commands.backfill_authorized_summaries --apply
     ```
   - 再执行一次 `--apply` 验证幂等；`regenerated`、`created_rows`、`updated_rows`、
     `cleared_pending_markers` 应全部为 `0`。`pending` 可非零，需后续补齐源摘要再重跑。
   - 本回填只更新当前版本摘要行/安全待处理标记，不删除资产，不触发重索引、重新入库或
     WeKnora 调用。异常时停止放流量并从 §2.2 数据库备份恢复相关摘要数据。
5. **启动服务**：`backend` → `worker` → `beat` → `frontend`（compose `depends_on` 已编排：postgres/redis healthy → migrate 完成 → backend/worker/beat → frontend）。
   ```powershell
   docker compose up -d
   ```
6. **执行 health / ready / config**（见 §4.1）。
7. **执行 live smoke**（见 [`LIVE_SMOKE_CHECKLIST.md`](./LIVE_SMOKE_CHECKLIST.md)）。
8. **观察日志与关键审计事件**：
   - worker / beat 是否在消费任务（无堆积、无反复重启）；
   - 关键审计 action 是否正常落库：`login.success` / `login.failed`、`ingest.ai_extracted` / `ingest.failed`、`access.original_*`、`auth.*`（系统安全事件）；
   - 审计与日志**不应**出现 raw email / password / token / cookie / 原始 IP / WeKnora id / 原文。

---

## 3. 域名与 TLS

- **入口拓扑**：生产用户入口 = `frontend` 服务（nginx 静态托管 `dist/` + **同源反代**后端）。前端 bundle 用同源相对路径，不烙后端内网 URL。
  - nginx 反代（server 块 `deploy/nginx.conf.template`，http 级配置 `deploy/nginx-main.conf`）：`/api/v1/`、`/health`（覆盖 `/health/ready`、`/health/config`）、`/admin/ops/` → `backend:8000`（Docker DNS）；其余路径 SPA fallback 到 `index.html`。`nginx.conf.template` 在容器启动时由 nginx 镜像 envsubst 机制渲染（替换 `${ONLYOFFICE_ORIGIN}`）。
  - backend 宿主端口（compose 本地映射 `127.0.0.1:8001`）**仅供调试**，生产正式访问不走它，可在生产移除该映射。本地 compose 前端入口为 `http://<host>:18080/`。
- **TLS 终止位置**：在 `frontend` nginx 之前（或之上）放置真实 HTTPS/TLS 终止（云 LB / 反代 / Ingress）。本仓库前端 nginx 以**非 root** 用户监听 `8080`（compose 映射 `18080:8080`），TLS 由前置层负责。
- **宿主机 Nginx 只由仓库管理上传端点 snippet，绝不接管完整站点**：现有 server block 继续负责 TLS/Certbot、企业微信校验文件、ONLYOFFICE（生产实际转发 `127.0.0.1:8443`）和 KAP 默认入口（`location /` 转发 `127.0.0.1:18080`）。[`deploy/nginx-host-upload-rules.conf`](../../deploy/nginx-host-upload-rules.conf) 仅包含两个上传 location 的 `32m / 120s` 覆盖；[`deploy/install-host-nginx.sh`](../../deploy/install-host-nginx.sh) 只允许显式模式：
  ```sh
  # 1. 只读识别现有 KAP server_name、唯一 location / 和 include 状态
  sudo env KAP_SERVER_NAME=kap.example.com \
    KAP_NGINX_SITE_PATH=/etc/nginx/sites-available/kap \
    sh ./deploy/install-host-nginx.sh --check

  # 2. 经变更审批后，安装/更新 snippet 并仅向目标 server 插入一行 include
  sudo env KAP_SERVER_NAME=kap.example.com \
    KAP_NGINX_SITE_PATH=/etc/nginx/sites-available/kap \
    sh ./deploy/install-host-nginx.sh --install

  # 3. 只读运行 nginx -t 并展示实际受管片段
  sudo env KAP_SERVER_NAME=kap.example.com \
    KAP_NGINX_SITE_PATH=/etc/nginx/sites-available/kap \
    sh ./deploy/install-host-nginx.sh --verify
  ```
  默认 snippet 位置为 `/etc/nginx/snippets/kap-upload-rules.conf`。脚本只接受能唯一定位目标 `server_name` 且其中恰有一个 `location /` 的现有站点；歧义时会退出并打印人工插入 include 的准确步骤。`--check` 和 `--verify` 不写文件；没有明确 `--install` 时不会改变宿主机。安装重复执行不会重复 location；`nginx -t` 或 reload 失败会同时恢复旧站点文本与旧 snippet。站点其余路径应继续保持既有 `1m` 默认边界，ONLYOFFICE、TLS 和校验规则必须在安装前后逐项 diff 确认未变。
- **`APP_ENV=prod` 下 cookie `Secure=True` 的依赖（关键）**：
  - prod 时会话 cookie 与 OAuth state cookie 被**强制** `Secure`（`session_cookie_secure()`），即使显式注入 `SESSION_COOKIE_SECURE=false` 运行时也不退让（且会在 `/health/config` 报 blocker）。
  - **后果**：纯 HTTP 入口下浏览器不会回送 Secure cookie → 登录后会话不生效。**生产必须经真实 HTTPS 访问。**
- **反代需保留转发头**：前置反代与 `frontend` nginx 都要透传 `X-Forwarded-For` / `X-Forwarded-Proto` / `Host`（`deploy/nginx.conf.template` 已设 server 级 `proxy_set_header`）。`X-Forwarded-Proto` 对「识别请求为 HTTPS」很重要；trace header `X-Trace-Id` 也应透传以保链路可观测。
- **企微可信回调域名 / OAuth callback URL**：
  - 在企业微信后台把生产域名加入应用的**可信回调域名**；
  - `WECOM_REDIRECT_URI` 必须指向生产 callback（后端 `GET /api/v1/auth/wecom/callback`，经反代同源），与企微后台登记一致；
  - callback 为 GET（安全方法），不受 CSRF 中间件拦截，但 OAuth state 校验语义不变。

---

## 4. 上线验证

### 4.1 健康 / 就绪 / 配置探针

```powershell
# 活性
Invoke-WebRequest <prod-url>/health
# 就绪（DB；async 模式下 Redis）
Invoke-WebRequest <prod-url>/health/ready
# 安全配置诊断（只回布尔 / provider 名 / 缺失项名 / production_ready/blockers/warnings，无值）
Invoke-WebRequest <prod-url>/health/config
```

- `/health/ready` 非 200（503）→ DB 或 Redis 未就绪，先排依赖，不要放流量。
- `/health/config` 的 `production_ready=true` 仅表示「`APP_ENV=prod` 且无代码级硬阻断项」；它**不**代表业务 smoke 已通过。

### 4.2 安全烟测脚本

```powershell
python scripts/production_smoke.py --base-url <prod-url> --expect-prod-ready --json
```

- 纯标准库、只读探活：`/health`、`/health/ready`、`/health/config`（白名单字段）、前端入口 `/`、未登录 `/admin/ops/summary`（期望 401/403）。
- 输出只含端点名 / HTTP status / 安全摘要，**不打印**响应正文 / cookie / 密钥 / 连接串。
- exit code：health 或 ready 不通过 → 非 0；`--expect-prod-ready`（= `--fail-on-production-blockers`）且存在 blockers → 非 0。
- 完整 live smoke（鉴权 / CSRF / 上传 / 索引 / 搜索 / 权限边界 / WeCom / ONLYOFFICE）→ 见 [`LIVE_SMOKE_CHECKLIST.md`](./LIVE_SMOKE_CHECKLIST.md)。

---

## 5. 回滚与排障（Rollback & Troubleshooting）

> 通用回滚：保留上一个可用 `<image-tag>` 与数据库备份；新版本验证失败时，先停止放流量，按需回退镜像 tag，必要时从备份恢复 DB（迁移不可逆时尤其重要）。

| 症状 | 首查 | 处置 / 回滚 |
|---|---|---|
| **migration 失败** | `migrate` 服务日志（不贴含连接串的整段，截关键错误行）；确认 DB 可达、目标 head 正确 | 修复后重跑 `migrate`；若已部分应用且不可逆，从 §2.2 备份恢复后再上新版本；backend/worker/beat 因依赖 migrate 不会带半迁移库启动 |
| **backend 起不来** | backend 日志、`/health` 是否 200、`depends_on`（postgres/redis healthy、migrate 完成） | 修依赖或配置；确认 `DATABASE_URL` / `REDIS_URL` 项已注入（**不打印值**）；必要时回退镜像 tag |
| **worker / beat 不处理任务** | worker/beat 是否运行、是否连到 broker、`CELERY_TASK_ALWAYS_EAGER` 是否误为 true、`/admin/ops/indexing` 是否堆积 | 确保 `false` 且 worker+beat 在跑；确认与 backend 同一 Redis、同一共享存储卷；重启 worker/beat |
| **`/health/config` 有 blocker** | 读 `production_blockers` 项名 | 按 [`PRODUCTION_SECRET_CHECKLIST.md`](./PRODUCTION_SECRET_CHECKLIST.md) 补对应项（只注入值、不打印值）后重启相关服务 |
| **CSRF 403** | 是否 cookie 会话下的 unsafe 请求缺 `X-CSRF-Token`；前端是否先取 `GET /api/v1/auth/csrf`；prod 是否配 `CSRF_TOKEN_SECRET` | 确认前端自动取/附带 token；确认反代未吞掉 `X-CSRF-Token` 头；补 `CSRF_TOKEN_SECRET` |
| **Secure cookie 在 HTTP 环境无法登录** | 入口是否真 HTTPS、`X-Forwarded-Proto` 是否透传 | 走真实 HTTPS 入口；prod 下不要试图关 Secure（运行时强制）；修反代转发头 |
| **WeCom OAuth callback 失败** | 企微可信回调域名、`WECOM_REDIRECT_URI` 是否与登记一致、state 是否有效、成员有效性（失效成员 fail-closed） | 对齐回调域名 / redirect uri；成员被禁用/删除/未激活时是设计内 fail-closed（不建会话）；上游故障 fail-closed 不误改状态 |
| **WeKnora indexing / parse 失败** | `/admin/ops/indexing`（安全状态）、confirm 后 `index_status`、worker 日志 | WeKnora 未配 → `production_warnings: WEKNORA_NOT_CONFIGURED`，检索降级；启用但未在模型配置中心配置平台默认 embedding（blocker `WEKNORA_DEFAULT_EMBEDDING_MODEL`）/ 缺 `WEKNORA_MODEL_REF_SECRET` → blocker，补项（PBC-38：`WEKNORA_EMBEDDING_MODEL_ID` 已 deprecated，不再是 blocker）；解析失败资产可在 ops 面板发起 retry-index / reparse |
| **ONLYOFFICE 打不开** | `ONLYOFFICE_ENABLED`、`ONLYOFFICE_DOCUMENT_SERVER_URL`、`ONLYOFFICE_JWT_SECRET`、Document Server 可达 | 启用则三项齐全（缺 URL/JWT 为 prod blocker）；Document Server 通常强制 JWT，未签名 config 会被拒；未配置时安全降级、不泄露原文 URL |
| **frontend 反代 404/502** | nginx 是否解析到 `backend`、backend 是否 healthy、`location` 是否覆盖目标路径 | 502 多为 backend 未就绪（nginx 用变量 `proxy_pass` + resolver 容忍启动期）；404 多为路径未走 `/api/v1//health//admin/ops` 而落到 SPA fallback；确认前置反代把 `/api/v1/` 等转给 frontend |

---

## 6. 仍需真实运维执行

本仓库提供部署 runbook + 安全配置清单 + live smoke 清单 + 无密钥 smoke 脚本。以下仍是真实运维动作，需在目标环境执行：

- 真实公网域名、DNS 记录；
- TLS 证书申请 / 续期、HTTPS 终止层；
- 云密钥注入（WeKnora / LLM / 企微 / ONLYOFFICE / DB / Redis）；
- 对象存储开通与 `StorageBackend` 平替；
- 镜像推送到生产 registry；
- 云监控 / 告警 / 日志后端接入。

**明确不在本任务范围**：K8s / Helm / Terraform / 云密钥平台接入、OCR、MFA / OTP / 短信、找回密码 / 邮件重置、密码轮换、完整多设备会话管理 UI、结构保持式文件重写、Ollama/LLM 脱敏、历史资产全量重索引。
