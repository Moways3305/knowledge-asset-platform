# Backend — 知识资产平台

知识资产平台的后端服务：FastAPI + SQLAlchemy（async）+ PostgreSQL + Redis + Celery。负责身份与权限、知识资产数据模型、入库流水线、两阶段检索与问答、审核与生命周期治理、原文访问授权、运维与审计，以及对 WeKnora / 外部 LLM / 企业微信 / ONLYOFFICE 的集成。

服务连接经环境变量启用，业务默认模型及生成模型连接由管理页面维护并安全存储；未配置时按能力边界降级或拒绝，不伪装成功。真实密钥经部署注入，不入仓库。

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
- **权限规则**：`permission_rules` 为治理配置中心（阈值 / 开关 / 固定路径）；生效项包括原文申请超时规则和授权有效期；已退役的跨项目 L1/L2 默认原文放行开关不再生效。
- **三层访问模型**：发现层（标题/类型/标签/脱敏简述）、摘要层（安全摘要）、原文层（原文 / 客户数据 / 预览）。管控集中在原文层；L3/L4 对外摘要必须脱敏；个人库仅本人可见；项目 active 成员可读本项目原文，跨项目 L1–L4 仅安全摘要、L5 不可发现；公司 L5 仅总经理 / 咨询总监可发现。纯管理员（`admin`）不获得业务知识可见性。

## 3. 主要 API 模块（`app/api/`）

- `auth`：登录 / 登出 / 当前身份 / 企业微信 OAuth / CSRF token 发放。
- `knowledge`、`search`：知识读 API 与语义检索（`POST /api/v1/knowledge/search`）。
- `ingest`：入库任务、AI 抽取结果、确认入库；`lifecycle`：归档 / 重新启用。
- `people`、`projects`、`permissions`：人员与项目成员、项目设置、权限规则与外部 Agent 接入注册。
- `ops`：健康探针与运维端点（索引运维、审计、登录风控、会话撤销、企业微信身份对账等，挂在 `/admin/ops` 与 `/health`）。
- `wecom_scan`、`weknora_admin`、`weknora_options`：微盘扫描配置 / 触发 / 记录；WeKnora 模型与建库配置中心（admin），含平台默认模型读写 `GET|PUT /api/v1/admin/weknora/default-models`（读 admin / 治理，写仅 admin）；以及顾问只读模型选项 `GET /api/v1/weknora/model-options`（业务用户可读，供入库时选模型）。三者对外只用对底座 id 不可逆的 `model_ref`，绝不回真实 `model_id` / `api_key` / `base_url`。
- `agent_gateway`：provider 中立外部 Agent 网关（**WorkBuddy MCP 主接入面**）——Bearer token 绑定 KAP 用户，caller 仅从 token 绑定解析。检索/问答：`/api/v1/agent-gateway/tools/knowledge-search`、`/projects`。只读知识应用工具全部经同一 `require_bound_caller` 和实时 `decide()`；其中 `/knowledge/{asset_id}/content` 仅在 original 放行后按当前版本受控源文件抽取并分页返回文本，绝不返回文件、存储引用或预览/下载 URL。
- `dify`：**legacy** 兼容适配器（仅承载 Dify 线缆形态；保留可用、不强删，新接入改用 agent_gateway）。

健康探针：
- `GET /health`（活性）、`GET /health/ready`（DB；async 模式下 Redis）。
- `GET /health/config`：安全配置诊断，只回布尔 / provider 名 / 缺失项名 / `production_ready` / `production_blockers` / `production_warnings`，绝不回值、密钥、URL、连接串或内部 id。

## 4. 异步任务与索引运维

- **Celery**（`app/worker/`）：入库处理、解析对账、归档扫描、复用推荐、通知下发、索引批量运维。`CELERY_TASK_ALWAYS_EAGER=true` 时内联同步执行（无需 worker）；接入 worker 时设为 `false` 启用真正异步。生产必须运行轻量 worker、独立 OCR/重型 worker、解析对账 worker 与 beat。
- **解析对账隔离**：`weknora.parse_reconcile` 经 `CELERY_PARSE_QUEUE`（默认 `parse`）交给独立 `parse_worker`；上传生成、事件投递和心跳继续使用 `default`，重型抽取使用 `ocr`。Compose 默认将原普通 worker 的 1 CPU / 4GiB 分为普通 worker 的 0.75 CPU / 3584MiB 与解析 worker 的 0.25 CPU / 512MiB；已有内存覆盖值需将新增的 512MiB 一起计入总预算。正式发布脚本 `scripts/deploy_release.py` 包含新消费者，手工选择服务时也必须部署它。旧 `default` 中的解析消息仍由原队列排空，不清空 broker。正常停止给解析任务 45 秒退出；子进程异常退出会重新入队，残留的 120 秒租约由后续定时对账接续，终态文档不会重复更新。整台 worker 硬退出时沿用 Redis 的投递恢复机制及每 5 分钟的对账扫描；不缩短共享 broker 的可见性超时。回退到旧版前，应先暂停 beat、让 `parse` 的等待和执行中任务排空，再停止新消费者并恢复旧服务，不能遗留无人消费的队列。
- **两阶段入库**：人工确认即落库（阶段 1）；推进 WeKnora 索引为阶段 2，建库 / 初始化 / 上传失败不回滚资产，而是标记索引失败并可重试。
- **索引与解析状态**：`index_status` 的 `indexed` 只表示底座文档已建立；正文解析可读性另由 `weknora_parse_status` 表达。解析失败保持真实 `indexed + failed` 口径并引导重新解析，不伪装成普通索引成功；0 命中维护作业标为 `no_action`。响应 / 审计绝不含 WeKnora kb·doc id / 存储引用 / 原文。
- **检索可见性**：检索只映射并使用活动版本 `index_status=indexed` 的底座文档；失败 / 跳过的资产不被召回。

## 5. 外部集成

连接与开关经环境变量注入，平台模型配置另由管理接口维护。未配置的可选服务按接口返回降级状态；已启用服务缺关键配置可能阻断生产就绪或启动。真实密钥不入仓库，项名见 `.env.example`。

- **WeKnora**（向量检索 / 索引底座）：`base_url + api_key` 配齐启用；建库随模型配置初始化。模型选择（PBC-38）：优先级为「请求显式 `model_ref` > 平台默认模型（DB `weknora_default_models`，模型配置中心维护）> fail-closed」——已不再用 `WEKNORA_EMBEDDING_MODEL_ID` 等 `.env` 项作为生产建库兜底（保留仅 legacy / 测试隔离，见 `.env.example`）；启用 WeKnora 但未配置平台默认 embedding 时，`/health/config` 阻断项列出 `WEKNORA_DEFAULT_EMBEDDING_MODEL`，入库 fail-closed（资产保留、可补配置后重试索引）。每个 KB 建库时绑定其 embedding 模型；显式传入不一致的 `embedding_model_ref` 会按当前底座契约**自动切换** KB 的 embedding 配置并回写绑定（存量文档需在切换后重新解析以重新向量化，避免新旧向量空间混用）。`model_id` / `api_key` / `base_url` / kb_id / doc_id 视同内部标识，绝不进任何响应 / 审计 / 日志。
- **外部 LLM**（内容处理）：优先由模型管理页维护加密的 KAP 内容生成模型及平台默认模型；产品配置存在后不回退旧环境默认值。仅未建立产品配置时兼容 `LLM_*` 环境配置；用于分类 / 三层摘要 / 标签 / 关键知识点；缺失则回退确定性草稿，上传不失败。入库建议由该受信外部 API 处理，**不再前置脱敏**（保留客户/金额等上下文以提升命名与摘要质量）；规则脱敏引擎保留为备用，待本地大模型资源到位后可重新接入。**对外输出仍按权限与脱敏策略收口**：检索原文 chunk / Agent 引用在权限放行后做输出脱敏。
- **企业微信**：OAuth 登录（按 `users.wecom_user_id` 解析，不自动建用户）、微盘扫描（平台后端下载字节落受控存储 → 建入库任务）、通知下发（受总开关控制，默认仅站内）、成员身份生命周期同步。
- **ONLYOFFICE**：只读预览，返回受控取件 URL（Document Server 凭短时 token 经平台回取字节），不暴露存储地址 / 完整 token / JWT 密钥。
- **文件存储**：当前 `services/storage.py` 使用 `LocalFileStorage`，生产通过共享持久卷保存字节，backend / worker / ocr_worker 必须读取同一存储。S3/OSS/MinIO 适配尚未实现，不能仅填云存储环境变量完成切换；存储引用保持 server-only。

## 6. 认证、安全与审计

- **登录方式**：密码登录（所有环境真实校验 PBKDF2，`login_method=password`）、企业微信 OAuth（`login_method=wecom_oauth`）；`local/dev/test` 额外保留邮箱免密的开发适配器（`login_method=dev_local`），生产拒绝免密。明文会话 token 只经 httpOnly cookie 下发，服务端只存 sha256 哈希。
- **登录风控**：失败尝试按不可逆 `identifier_hash` / `ip_hash` 记录，短时账号锁定 + IP 限流；统一非枚举 401；安全审计 `login.locked` / `login.rate_limited`。
- **CSRF**：cookie 会话下的有副作用请求需带签名 + 过期 + 绑定会话的 CSRF token（`GET /api/v1/auth/csrf` 获取）；dev header、Bearer（外部 Agent）、OAuth 回调豁免。
- **会话撤销与身份同步**：账号停用 / 改密 / 管理员强制下线可撤销会话；企业微信成员失效时停用平台用户并撤销会话。
- **生产安全守卫**：`APP_ENV=prod` 时会话 / OAuth cookie 强制 `Secure`；`/health/config` 暴露生产阻断项（如 eager worker、不安全 cookie、缺失关键密钥项名）。
- **审计**：`audit_events` 不可变追加；写入即脱敏，绝不写业务原文、客户数据、storage 引用、对象存储 URL、完整 token、外部系统内部 id。

## 7. 部署 / migration / smoke

- **编排**：`docker-compose.yml`（postgres / redis / migrate / backend / worker / ocr_worker / parse_worker / beat / frontend）。`migrate` 服务一次性执行 `alembic upgrade head`，backend/worker/ocr_worker/parse_worker/beat 依赖其成功后启动。
- **本地启动**：从仓库根 README 准备根 `.env` 和 `backend/.env`，根配置使用开发模式并设置数据库及 Redis 密码，再运行 `docker compose build` 与 `docker compose up -d --wait`；可选 `docker compose exec backend python -m app.seed.dev_seed`。后端调试端口 `8001`，前端入口 `18080`。
- **本地 Python**（可选）：推荐 Python 3.12，与 CI/镜像一致。在 `backend/` 创建虚拟环境，执行 `python -m pip install -e ".[dev]"`，配置本机数据库/Redis 后运行 `alembic upgrade head` 和 `uvicorn app.main:app --reload --port 8001`。Linux 可用 `python -m pip install --require-hashes -r requirements-dev.lock` 复现 CI 依赖。OCR/旧版 Office 还依赖系统解析组件，本地完整流程优先用 Docker。
- **依赖锁定**：生产镜像按带哈希的 `requirements.lock` 安装（再生成命令见该文件头注释）。CI 的 lint / 测试 job 用 `requirements-dev.lock`——以 `-c requirements.lock` 约束、在运行时依赖之上增加 pytest / pytest-asyncio / aiosqlite / ruff，故共享依赖版本与镜像逐一相同。再生成：`uv pip compile pyproject.toml build-requirements.in --extra dev -o requirements-dev.lock --python-version 3.12 --python-platform linux --generate-hashes -c requirements.lock`（也写在文件头注释）。升级运行时依赖时先重生成 `requirements.lock`，再重生成 `requirements-dev.lock`。
- **生产前提**：真实域名、HTTPS/TLS 与反向代理、企业微信可信回调域名、外部系统密钥注入、持久卷备份与监控接入需运维实际执行。仓库内提供部署 runbook 与无密钥 smoke 脚本（见根 README 与 `docs/deployment/`）。
- **安全验证**：不要运行或粘贴完整 `docker compose config`（会展开 `env_file` 密钥）；用 `docker compose config --services` / `--volumes` 或对 `docker-compose.yml` 定向检索验证编排结构。

## 8. 测试

```powershell
cd backend
python -m compileall app          # 语法编译检查
python -m pytest                  # 全量测试（async pytest 配置在 backend/）
python -m pytest tests/test_permission_service.py   # 单模块示例
```

测试覆盖权限判定、入库与检索、审核与生命周期、原文访问、登录与安全守卫、外部集成的降级与无泄露行为。前端构建用 `npm run build`（仓库根）。
