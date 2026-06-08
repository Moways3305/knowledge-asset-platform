# Backend — 知识资产平台

知识资产平台的后端服务：FastAPI + SQLAlchemy（async）+ PostgreSQL + Redis + Celery。负责身份与权限、知识资产数据模型、入库流水线、两阶段检索与问答、审核与生命周期治理、原文访问授权、运维与审计，以及对 WeKnora / 外部 LLM / 企业微信 / ONLYOFFICE 的集成。

外部集成均经环境变量启用；未配置时安全降级（fail-closed），不伪装成功。真实密钥经部署注入，不入仓库。

---

## 1. 架构概览

- **入口**：`app/main.py` 装配 FastAPI 应用、中间件（trace_id、CSRF）、路由与健康探针。
- **分层**：
  - `app/api/`：HTTP 路由与请求/响应契约（薄层，仅编排）。
  - `app/services/`：业务逻辑与权限判断（核心）。
  - `app/models/`：SQLAlchemy ORM 模型；`app/schemas/`：Pydantic DTO 与枚举。
  - `app/worker/`：Celery 应用、任务与运行时（异步治理作业）。
  - `app/core/`：配置、trace、CSRF 等基础设施。
  - `app/seed/`：开发种子数据（仅 dev/test）。
- **集中权限网关**：所有知识发现 / 摘要 / 原文 / 检索 / 外部 Agent 调用都经 `app/services/permission.py` 统一判定，业务路由不自行放行。
- **trace_id 贯穿**：HTTP 请求生成 `X-Trace-Id`，经入队传递到 worker、WeKnora 调用与审计事件，用于跨链路排障；trace_id 仅作关联，不是鉴权凭证。

## 2. 数据模型与权限模型

- **知识资产**（`models/knowledge.py`）：`knowledge_assets` 聚合根 + 版本 / 分块 / 文件对象 / 摘要 / 标签。`scope = personal | project | company`，`zone = material | asset` 表示资产化状态（同库内状态标签，不拆物理库）。保密级 L1–L5。
- **身份与项目**：`users`、`user_company_roles`、`projects`、`project_members`、`user_sessions`。公司角色与项目内角色分离；同一人可在不同项目担任不同项目角色。
- **审核与生命周期**：`review_tasks`、`validation_evidences`、`personal_knowledge_submissions`、`asset_lifecycle_events`、`alert_rules`、`notification_records`。
- **原文访问**：`original_access_requests` + `access_grants`，承载申请 / 审批 / 授权 / 撤销与运行时放行。
- **权限规则**：`permission_rules` 为治理配置中心（阈值 / 开关 / 固定路径）；部分项（如原文申请超时自动通过、L1/L2 默认放行开关、授权有效期）已接入运行时判定。
- **三层访问模型**：发现层（标题/类型/标签/脱敏简述）、摘要层（安全摘要）、原文层（原文 / 客户数据 / 预览）。管控集中在原文层；L3/L4 对外摘要必须脱敏；L5 仅 Boss / 咨询总监可发现；管理员（`admin`）为系统身份，不获得业务知识可见性。

## 3. 主要 API 模块（`app/api/`）

- `auth`：登录 / 登出 / 当前身份 / 企业微信 OAuth / CSRF token 发放。
- `knowledge`、`search`：知识读 API 与语义检索（`POST /api/v1/knowledge/search`）。
- `ingest`：入库任务、AI 抽取结果、确认入库；`lifecycle`：归档 / 重新启用。
- `people`、`projects`、`permissions`：人员与项目成员、项目设置、权限规则与外部 Agent 接入注册。
- `ops`：健康探针与运维端点（索引运维、审计、登录风控、会话撤销、企业微信身份对账等，挂在 `/admin/ops` 与 `/health`）。
- `wecom_scan`、`weknora_admin`：微盘扫描配置 / 触发 / 记录、WeKnora 模型与建库配置中心。
- `dify`：provider 中立外部 Agent / 工作流网关的兼容适配器（Dify 只是其中一个适配面，核心逻辑 provider 无关）。

健康探针：
- `GET /health`（活性）、`GET /health/ready`（DB；async 模式下 Redis）。
- `GET /health/config`：安全配置诊断，只回布尔 / provider 名 / 缺失项名 / `production_ready` / `production_blockers` / `production_warnings`，绝不回值、密钥、URL、连接串或内部 id。

## 4. 异步任务与索引运维

- **Celery**（`app/worker/`）：入库处理、解析对账、归档扫描、复用推荐、通知下发、索引批量运维。`CELERY_TASK_ALWAYS_EAGER=true` 时内联同步执行（无需 worker）；接入 worker 时设为 `false` 启用真正异步。生产必须运行 worker 与 beat。
- **两阶段入库**：人工确认即落库（阶段 1）；推进 WeKnora 索引为阶段 2，建库 / 初始化 / 上传失败不回滚资产，而是标记索引失败并可重试。
- **索引状态**：`not_indexed | indexing | indexed | index_failed | skipped`，对外为安全业务状态。`/admin/ops/indexing` 提供安全计数与最近失败列表；支持单条 retry-index、批量重试与显式 reparse，批量动作进入后台作业（`indexing_operation_jobs`）。响应 / 审计绝不含 WeKnora kb·doc id / 存储引用 / 原文。
- **检索可见性**：检索只映射并使用活动版本 `index_status=indexed` 的底座文档；失败 / 跳过的资产不被召回。

## 5. 外部集成

均经环境变量启用，未配置则降级（不阻断启动），真实密钥不入仓库。项名见 `.env.example`。

- **WeKnora**（向量检索 / 索引底座）：`base_url + api_key` 配齐启用；建库随模型配置初始化；embedding 模型全平台统一、建库后不可改。kb_id / doc_id 视同内部存储引用，绝不进任何响应 / 审计 / 日志。
- **外部 LLM**（内容处理）：选一个 provider + api_key 即启用；用于分类 / 三层摘要 / 标签 / 关键知识点；缺失则回退确定性草稿，上传不失败。
- **企业微信**：OAuth 登录（按 `users.wecom_user_id` 解析，不自动建用户）、微盘扫描（平台后端下载字节落受控存储 → 建入库任务）、通知下发（受总开关控制，默认仅站内）、成员身份生命周期同步。
- **ONLYOFFICE**：只读预览，返回受控取件 URL（Document Server 凭短时 token 经平台回取字节），不暴露存储地址 / 完整 token / JWT 密钥。
- **文件存储**：受控服务端存储，存储引用为 server-only、绝不进响应；本地后端用于 dev/test，生产可经可插拔 `StorageBackend` 平替为对象存储（S3/OSS/MinIO）。

## 6. 认证、安全与审计

- **登录方式**：密码登录（所有环境真实校验 PBKDF2，`login_method=password`）、企业微信 OAuth（`login_method=wecom_oauth`）；`local/dev/test` 额外保留邮箱免密的开发适配器（`login_method=dev_local`），生产拒绝免密。明文会话 token 只经 httpOnly cookie 下发，服务端只存 sha256 哈希。
- **登录风控**：失败尝试按不可逆 `identifier_hash` / `ip_hash` 记录，短时账号锁定 + IP 限流；统一非枚举 401；安全审计 `login.locked` / `login.rate_limited`。
- **CSRF**：cookie 会话下的有副作用请求需带签名 + 过期 + 绑定会话的 CSRF token（`GET /api/v1/auth/csrf` 获取）；dev header、Bearer（外部 Agent）、OAuth 回调豁免。
- **会话撤销与身份同步**：账号停用 / 改密 / 管理员强制下线可撤销会话；企业微信成员失效时停用平台用户并撤销会话。
- **生产安全守卫**：`APP_ENV=prod` 时会话 / OAuth cookie 强制 `Secure`；`/health/config` 暴露生产阻断项（如 eager worker、不安全 cookie、缺失关键密钥项名）。
- **审计**：`audit_events` 不可变追加；写入即脱敏，绝不写业务原文、客户数据、storage 引用、对象存储 URL、完整 token、外部系统内部 id。

## 7. 部署 / migration / smoke

- **编排**：`docker-compose.yml`（postgres / redis / migrate / backend / worker / beat / frontend）。`migrate` 服务一次性执行 `alembic upgrade head`，backend/worker/beat 依赖其成功后启动。
- **本地启动**：`docker compose build && docker compose up -d`；可选 `docker compose exec backend python -m app.seed.dev_seed`。后端调试端口 `8001`，前端入口 `18080`。
- **本地 Python**（可选）：创建虚拟环境、`pip install -r requirements.txt`、`alembic upgrade head`、`uvicorn app.main:app --reload`。
- **生产前提**：真实域名、HTTPS/TLS 与反向代理、企业微信可信回调域名、外部系统密钥注入、对象存储与监控接入需运维实际执行。仓库内提供部署 runbook 与无密钥 smoke 脚本（见根 README 与 `docs/deployment/`）。
- **安全验证**：不要运行或粘贴完整 `docker compose config`（会展开 `env_file` 密钥）；用 `docker compose config --services` / `--volumes` 或对 `docker-compose.yml` 定向检索验证编排结构。

## 8. 测试

```powershell
cd backend
python -m compileall app          # 语法编译检查
python -m pytest                  # 全量测试（async pytest 配置在 backend/）
python -m pytest tests/test_permission_service.py   # 单模块示例
```

测试覆盖权限判定、入库与检索、审核与生命周期、原文访问、登录与安全守卫、外部集成的降级与无泄露行为。前端构建用 `npm run build`（仓库根）。
