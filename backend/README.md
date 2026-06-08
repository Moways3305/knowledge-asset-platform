# Backend — AI Knowledge Asset Platform

当前已包含 **IMPLEMENT-00 工作台 + IMPLEMENT-01 身份/角色/项目成员 + IMPLEMENT-02 知识资产核心数据模型 + IMPLEMENT-03 权限判断服务**。已有身份模型与 `/api/v1/auth/me` 身份上下文接口、知识资产核心 6 表的 ORM 与迁移，以及集中权限判断服务。**仍不包含** Knowledge API、入库、审核、预览、Agent、审计、生命周期等业务逻辑。

## 技术栈

- **FastAPI**（Web 框架 / API）
- **PostgreSQL**（数据库）
- **SQLAlchemy 2.x + Alembic**（ORM 与迁移）
- **Redis + Celery**（任务队列依赖占位，本阶段不实现任务逻辑）
- **pytest + httpx**（测试），**ruff**（lint）

## 目录结构

```text
backend/
  README.md
  pyproject.toml          # 依赖与工具配置
  .env.example            # 环境变量示例（无真实密钥）
  Dockerfile
  alembic.ini             # Alembic 配置（URL 由 env.py 从环境读取，保持 ASCII）
  alembic/
    env.py                # 读取 DATABASE_URL，target = Base.metadata（已导入 models）
    script.py.mako
    versions/
      0001_create_identity_and_project_membership_tables.py  # 身份/项目成员迁移
  app/
    main.py               # FastAPI app 入口（工厂 create_app）
    api/health.py         # /health
    api/auth.py           # /api/v1/auth/me（身份上下文）
    core/config.py        # pydantic-settings 配置
    core/trace.py         # trace_id 中间件骨架
    db/base.py            # SQLAlchemy Base
    db/session.py         # 异步 engine / session（懒加载）
    models/identity.py    # users / user_company_roles / projects / project_members
    schemas/enums.py      # 角色 / 状态枚举 + 业务/L5 判定集合
    schemas/auth.py       # /auth/me 响应 schema
    services/identity.py  # 开发态 mock identity 解析 + 身份上下文组装
    seed/dev_seed.py      # 开发态 seed 数据（固定 UUID）
  tests/
    conftest.py           # 内存 SQLite + AsyncClient fixtures
    test_health.py
    test_auth_me.py
```

## 本地启动

### 方式一：docker compose（推荐）

在仓库根目录：

```bash
docker compose up --build
```

启动 PostgreSQL + Redis + backend。后端默认监听 `8000`。

> compose 中的数据库账号/密码（dev / devpassword）**仅限本地开发**，不得用于任何共享或真实环境。

### 方式二：本地 Python

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    |  *nix: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # 按需调整 DATABASE_URL / REDIS_URL
uvicorn app.main:app --reload
```

## 健康检查

- 地址：`GET http://localhost:8001/health`（Docker 本地映射；容器内仍为 8000）
- 返回：`status` / `service` / `environment` / `trace_id`
- 仅做存活检查，不连接数据库或外部系统。

## trace_id 行为

- 每个请求携带 `X-Trace-Id`；若未携带则服务端生成一个。
- trace_id 存放于 `request.state.trace_id`，并在响应头 `X-Trace-Id` 回显。
- trace_id 用于全链路关联，**不是权限凭证**，不能用于绕过权限（承接 BE-09）。

## Alembic 基线

- 已建立 SQLAlchemy `Base` 与 Alembic 配置基线。
- `alembic/env.py` 从 `DATABASE_URL` 环境变量读取连接串，target metadata 指向共享 `Base.metadata`（已导入 `app.models`）。
- 已有迁移：`0001`（身份/项目成员 4 表）→ `0002`（知识资产核心 6 表）。
- **尚未创建权限 / 入库 / 审核 / 预览 / Agent / 审计 / 生命周期等后续业务表**，这些将在后续 IMPLEMENT 任务中按 `docs/backend/01-数据模型DATA_MODEL.md` 添加。

## 测试

```bash
cd backend
python -m pytest
```

`/health` 测试不依赖数据库。

## IMPLEMENT-01：身份、角色、项目成员

已实现身份上下文底座（不含权限判断服务、知识资产、审计等业务）：

- 模型：`users` / `user_company_roles` / `projects`（最小字段）/ `project_members`
- 迁移：`alembic/versions/0001_create_identity_and_project_membership_tables.py`
- 接口：`GET /api/v1/auth/me`
- 开发态 mock identity：见下

### 开发态 mock identity

- 通过请求头 `X-Dev-User-Id` 指定当前用户；缺省时回退到默认开发用户（顾问A）。
- **仅在 `APP_ENV ∈ {local, dev, test}` 时启用**；其它环境返回 403。
- 这是开发态便捷机制，**不是正式鉴权**；正式身份由**企微 OAuth 提供（已在 R6 实现**，见后文 R6 节：`/api/v1/auth/wecom/start` + `/callback`）。`X-Dev-User-Id` 仅在无有效会话且 `APP_ENV ∈ {local, dev, test}` 时回退。

### `/api/v1/auth/me` 契约要点

- 返回 `user_id / name / email / status / company_roles / is_business_user / can_discover_l5 / project_memberships`。
- `company_roles` 与 `project_memberships` 分离；**admin 出现在 company_roles 不等于业务权限**。
- `is_business_user`：active 公司角色含 boss / consulting_director / consultant。
- `can_discover_l5`：active 公司角色含 boss / consulting_director。
- 公司角色与项目成员关系都只统计 `status=active`。

### seed 与测试

- 开发态 seed：`app/seed/dev_seed.py`（固定 UUID，幂等），覆盖 consultant / project_manager / boss / consulting_director / 纯 admin / consultant+admin 等身份边界。
- 测试使用内存 SQLite（`sqlite+aiosqlite`，StaticPool）+ pytest-asyncio（auto 模式），不依赖外部系统；正式运行仍以 PostgreSQL 为准。
- 运行测试：

```bash
cd backend
pip install -e ".[dev]"   # 需 sqlalchemy / aiosqlite / pytest-asyncio 等
python -m pytest
```

### Alembic 运行说明

- 默认 `DATABASE_URL` 指向 PostgreSQL（asyncpg），需 docker compose 的 postgres 在运行：

```bash
docker compose up -d postgres
cd backend && python -m alembic upgrade head
```

- 迁移已做跨库验证（可临时用 `DATABASE_URL=sqlite+aiosqlite:///./check.sqlite3 python -m alembic upgrade head` 在无 PostgreSQL 时验证建表）。
- 注意：`alembic.ini` 保持 ASCII，避免 Alembic 以 OS 本地编码（如 Windows GBK）读取配置时报错。

## IMPLEMENT-02：知识资产核心数据模型

已实现 6 张知识资产核心表（仅数据层，无 API / 权限 / 入库 / 审核 / 审计 / 预览 / Agent / 向量化）：

- `knowledge_assets`、`knowledge_asset_versions`、`knowledge_asset_chunks`、`knowledge_asset_file_objects`、`knowledge_asset_summaries`、`knowledge_asset_tags`
- 模型：`app/models/knowledge.py`；枚举：`app/schemas/enums.py`（知识资产相关）
- 迁移：`alembic/versions/0002_create_knowledge_asset_core_tables.py`
- 测试：`tests/test_knowledge_models.py`

### 关键边界说明

- **scope / zone**：`scope=personal/project/company` 是知识库归属；`zone=material/asset` 是【同一知识库内】的资产化状态标签，**不是两个物理库**。
- **personal owner 业务用户约束**：`scope=personal` 的 owner 必须是业务用户（active 公司角色 boss/consulting_director/consultant）；仅 admin 身份不得作为 personal owner。该跨表约束本阶段**不在 DB 层强制**，留待权限/服务层（后续任务）校验。
- **archived / deprecated**：归档/废弃资产与 superseded/invalid 版本、chunk 不进入默认检索 / RAG / Agent 上下文（由检索/网关层在后续任务落实）。
- **`storage_ref` 内部字段**：`knowledge_asset_file_objects.storage_ref` 是服务端内部存储引用，**禁止出现在任何 API / 响应 schema 中**，不向前端明文返回。
- **current_version_id**：为规避 assets↔versions 循环外键在 SQLite 迁移上的复杂度，`current_version_id` 仅作普通 UUID 列保存（无 DB 级外键），其一致性由服务层维护。

### 与 BE-02 的差异（待 reviewer 确认）

本阶段按 IMPLEMENT-02 任务的精简字段清单落地，与 BE-02 完整 schema 存在以下差异，留待 reviewer 决定是否对齐：

- `Visibility` 取值采用 BE-02 + 前端 mock 的 `public / project_only / confidential`（任务文本枚举小节误写为 private/project/company，未采纳）。
- `knowledge_asset_summaries` 采用**窄表**（`summary_type` + `content`，每种类型一行）；BE-02 为宽表（one_liner/detailed/... 多列）。
- 字段名精简/重命名：`version_no`（BE-02: version_number）、`file_size`（size_bytes）、`file_hash`（file 对象侧，BE-02: checksum）、`token_count`（BE-02 无）、`invalid_reason`（invalidation_reason）。
- 本阶段未落地 BE-02 的部分字段（如 chunk 的 contains_customer_data/vector_id、summaries 的 summary_level、assets 的 confidence/company_source_project_id 等），按"最小落地"留待后续任务补充。

### active version 约束（IMPLEMENT-02_FIX）

- “同一 asset 至多一个 active version”已落地为**部分唯一索引** `uq_asset_one_active_version`（`asset_id` UNIQUE WHERE `version_status = 'active'`）。
- PostgreSQL 与 SQLite（>=3.8）均支持带 WHERE 的部分唯一索引，因此该约束在单元测试（SQLite）与生产（PostgreSQL）上都生效。
- 服务层在激活版本时仍应做防御性校验（DB 约束是兜底，不替代业务流程）。

### Alembic（IMPLEMENT-02）

- 迁移链：`0001_identity` → `0002_knowledge`。
- 已在 SQLite 跨库验证 `alembic upgrade head` 成功建立全部 10 张表（4 身份 + 6 知识）及 `uq_asset_one_active_version` 部分唯一索引。
- 真实 PostgreSQL 验证需 Docker 守护进程运行（见下）。

## IMPLEMENT-03：权限判断服务

已实现**集中权限判断服务**（仅服务层 + 测试，**无 API、无新表、无 migration**），供后续 IMPLEMENT-04 Knowledge API 调用：

- 服务：`app/services/permission.py`（`build_caller_context` + `decide`）
- 类型：`app/schemas/permission.py`（AccessLayer / AccessChannel / DeniedReason / EffectiveAccessSource / CallerContext / PermissionDecision / DefaultAccessPolicy）
- 测试：`tests/test_permission_service.py`（矩阵式覆盖）

### decision 输出字段

`PermissionDecision`：`allowed`、`requested_layer`、`allowed_layer`（可达最高层级）、`denied_reason`、`effective_access_source`、`audit_required`、`strong_audit_required`、`summary_variant`（L3/L4 摘要提示 `redacted_summary`）。

### 关键语义

- **三层递进**：discovery < summary < original；发现层被拒则摘要/原文必拒。
- **个人知识**：本人业务用户三层全开（source=owner）；他人/仅 admin 身份一律 `personal_asset_not_owned`。
- **项目知识**：本项目 active 成员三层全开、原文需审计（source=project_member）；非成员 L3/L4 原文 `original_requires_request`、摘要脱敏，L1/L2 业务用户按默认策略可得原文、非业务用户 `no_project_membership`。
- **公司知识**：发现/摘要面较宽；L1/L2 业务用户默认可得原文（需审计）、非业务用户原文 `original_requires_request`；L3/L4 原文 `original_requires_request`、摘要脱敏。
- **L5**：仅 boss / consulting_director 可发现/摘要/原文，原文强审计（source=company_role）；其余（含 admin）`l5_not_discoverable`，不泄露存在信息。
- **A4 边界**：仅 `access_channel=agent` 的原文请求受 A4 限制（`agent_a4_original_denied`）；human 不因 A4 自动拒绝。
- **读侧状态过滤**：`asset_status` 为 archived/deprecated 默认不可发现（`asset_not_active`）。

### 当前限制与后续替换

- IMPLEMENT-03 当时无 `access_grants` / `original_access_requests` 表，跨项目 / 公司 L3/L4 原文一律按"需要申请"拒绝。**现状（PBC-06 已实现）**：两表已落地；无授权时仍 `original_requires_request`，经申请 → 审批 → 生成 active `access_grant` 后，`decide(has_original_grant=…)` 在运行时放行原文层（source=`access_grant`，需审计），过期 / 撤销立即失效。
- **L1/L2 原文默认放行策略**：`DefaultAccessPolicy`（`app/schemas/permission.py`）现作为出厂回退常量（`DEFAULT_POLICY`）。PBC-03 落 `permission_rules` 配置中心；PBC-06 已接入 active `access_grant` 的运行时原文放行与 `access_grant_duration_days`（grant 默认有效期来源）。**PBC-11E 已规则化接入运行时**：`permission_rules.load_access_policy()` 按 `cross_project_l1_l2_original_for_business_user` / `company_l1_l2_original_for_business_user` 两开关构建运行时 `DefaultAccessPolicy` 注入 `decide()`（规则缺失回退 `DEFAULT_POLICY`、禁用/非法 fail-closed），`access_request_timeout_hours` 驱动原文申请超时自动通过（仅 L1/L2）。后续增强仅余：其余 `permission_rules`（个人流转 / 升格阈值 / 生命周期）尚未规则化运行时，仍为治理配置视图。
- 本服务只做读侧判断，不写审计：`audit_required` / `strong_audit_required` 是给后续 IMPLEMENT-09 审计落点使用的标记，本阶段不落 `audit_events`。

## IMPLEMENT-04：基础 Knowledge 读 API 与前端 mock 第一批替换

已实现三类**只读** API（权限判断全部复用 `app/services/permission.py`，不在 router/页面散落权限矩阵）：

- `GET /api/v1/knowledge`：列表，只返回调用人可发现的资产；L5/他人 personal 直接过滤；archived/deprecated 默认不返回。
- `GET /api/v1/knowledge/{asset_id}`：详情；`l5_not_discoverable` / `personal_asset_not_owned` / archived 表现为 404；不返回原文内容、内部存储引用、token。
- `GET /api/v1/my/knowledge`：仅本人 `scope=personal` 资产；纯 admin 返回 403 + `admin_business_permission_denied`。

实现文件：`app/api/deps.py`（`get_caller_context` 复用开发态 mock identity + CallerContext）、`app/api/knowledge.py`、`app/schemas/knowledge.py`、`app/services/knowledge.py`、seed 扩展 `app/seed/dev_seed.py::seed_dev_knowledge`、测试 `tests/test_knowledge_api.py`。

### access_info 与摘要口径

- 每个资产返回 `access_info`（discovery/summary/original/effective_source/can_request_original），由权限服务三层决策得到；前端据此生成权限展示。
- **L3/L4 摘要过渡策略**：summaries 为窄表，L3/L4 列表/详情仅返回 `redacted_summary` / `safe_summary` 行作为安全摘要（无则为 None），不暴露 key_points；这是 IMPLEMENT-04 过渡口径，正式脱敏策略后续细化。
- `confidence` 未在 knowledge_assets 落地（见 IMPLEMENT-02 差异），API 固定返回 None。
- `no_project_membership` 仍为权限服务内部返回 key（IMPLEMENT-03 已通过）；本阶段 API 未强制改写为 `project_membership_required` 别名，避免改动已通过的权限服务；统一对外命名留待引入错误码映射层时处理。
- **include_archived**：当前不额外放行归档资产（权限服务对 archived/deprecated 作 asset_not_active 处理），治理归档视图留 IMPLEMENT-10；前端"包含归档"开关暂无额外效果。

### 前端 mock 替换（第一批）

- `/knowledge`、`/knowledge/:id`、`/my/knowledge` 三页主数据已改为真实 API（`src/api/client.ts` + `src/types/knowledge.ts`），不再依赖前端静态 mock 数据（早期前端静态数据层后续已删除）。
- `vite.config.ts` 增加 `/api` → `http://localhost:8001` 代理；开发态身份头 `X-Dev-User-Id` 由 client 统一附加（`VITE_DEV_USER_ID` 可覆盖，留空则后端回退默认开发用户）。
- 保留布局；写动作（提交/申请/预览/重新启用）保持禁用占位；洞察侧栏为本地展示占位。

### 开发态 seed 命令（IMPLEMENT-04_FIX）

本地完成迁移/建表后，可一条命令写入幂等开发态数据（身份 + 知识资产）：

```bash
# 先建表（PostgreSQL 需 docker compose 的 postgres 在运行）
docker compose up -d postgres
cd backend && python -m alembic upgrade head
# 写入 seed（幂等，可重复执行）
python -m app.seed.dev_seed
```

- 入口 `python -m app.seed.dev_seed` 调用 `seed_all`（identity + knowledge），两者均幂等。
- **仅允许 `APP_ENV ∈ {local, dev, test}`**；其它环境直接拒绝（非生产初始化机制）。
- 复用 `get_settings()` / `get_engine()` / `get_sessionmaker()`，不复制数据库 URL 默认值。
- 不含真实客户数据 / 真实路径 / 真实对象存储 URL / 真实 token。
- 无 PostgreSQL 时可临时用 SQLite 验证：
  `DATABASE_URL=sqlite+aiosqlite:///./dev.sqlite3 APP_ENV=local python -m alembic upgrade head && DATABASE_URL=sqlite+aiosqlite:///./dev.sqlite3 APP_ENV=local python -m app.seed.dev_seed`

### `/my/knowledge` 读侧状态过滤（IMPLEMENT-04_FIX）

- `/api/v1/my/knowledge` 复用 `decide(caller, asset, discovery)` 过滤，本人 **archived / deprecated** personal 资产默认不返回，与"归档/废弃不进入读侧检索/访问"的权限口径一致（不只写 SQL 状态条件，避免规则分叉）。

## IMPLEMENT-05：入库流水线最小闭环（Path B）

实现 Path B 本地上传 → AI 建议占位 → 人工确认 → 写入 KnowledgeAsset 的最小闭环（不实现真实文件存储/AI/Path A/审核流/审计）：

- 模型：`app/models/ingest.py`（`ingest_tasks` / `ingest_task_ai_results`，仅两表）；迁移 `0003_create_ingest_pipeline_tables`。
- API（`app/api/ingest.py` + `app/services/ingest.py` + `app/schemas/ingest.py`）：
  - `POST /api/v1/ingest/upload`：仅业务用户；同步生成确定性 AI 建议占位（基于文件名，不调真实 AI）；`upload_url` 固定 `null`（不返回签名上传地址）；不接收文件二进制（metadata-only）。
  - `GET /api/v1/ingest/{task_id}/ai-result`：创建人/治理角色看完整建议；**admin 仅运营元数据**（business 正文置 None）；其余 403。
  - `POST /api/v1/ingest/{task_id}/confirm`：人工确认后创建 KnowledgeAsset（zone=material）+ v1 active version + summaries（L3/L4 含脱敏摘要）+ tags，置 `current_version_id`，任务置 completed 并记 `result_asset_id`；二次确认返回 409。
  - `GET /api/v1/admin/ingest`：admin/治理只读运营列表（无业务原文 / 内部引用）。
- 权限边界：纯 admin 不可上传/确认（403 `admin_business_permission_denied`）；project 入库需目标项目 active 成员（否则 `project_membership_required`）；**consultant 直接确认 company 资产被拒**（`company_confirmation_requires_governance`，不假装完成公司级审核），仅 boss/咨询总监可确认 company。
- 安全：响应绝不含 `source_file_ref` / `storage_ref` / 真实上传下载 URL；`source_file_ref` 是 **server-only 内部存储引用**，当前本地存储格式为 `internal://<uuid>/<safe_name>`（仅供后端解析，非 URL，绝不外泄前端，见 IMPLEMENT-13）。
- 前端：`/upload` Path B 主流程接真实 API（创建任务 → AI 建议 → 人工校正 → 提交 → "查看新资产"链接）；目标项目下拉来自 `/auth/me` active 成员；Path A 企微 Agent 面板仍为 mock 占位（**现状：PBC-07 已接真实待确认任务 `GET /api/v1/ingest/pending?source=path_a_wecom` + 复用 Path B confirm 链路**）；写动作"保存草稿"等保持禁用。
- 测试：`tests/test_ingest_api.py`（10 用例），后端 64 passed；前端 `npm run build` 通过；迁移 SQLite `0001→0002→0003` 验证通过。
- **过渡口径**：新增 `IngestStatus.pending_confirmation`（BE-02 无，已由 reviewer 接受，`waiting_review` 保留给审核流）。
- **IMPLEMENT-05_FIX**：
  - confirm 归属校验：仅**任务创建人**或**业务治理角色（boss/咨询总监）**可确认；其他业务用户 403 `ingest_confirm_forbidden`；纯 admin 仍 403。
  - confirm 现接收并写入 `visibility`，且 `/upload` 人工校正区可编辑 `visibility` / `asset_type` / `confidentiality_level` / `ai_access_level` 并真实提交（中文可见性在前端映射为 enum key，不把中文发给 API）。
  - `IngestConfirmRequest` 的 `target_scope`/`target_zone`/`asset_type`/`visibility`/`confidentiality_level`/`ai_access_level` 改用 `app.schemas.enums` 的 Enum 做 Pydantic 校验，非法值返回 **422**，不写脏数据；DB 仍 String 存储（写入取 `.value`）。

## IMPLEMENT-06：审核流最小闭环（material → asset）

实现项目 material 资产 → 登记验证证据 → ReviewTask → PM approve → `zone=asset` 的闭环（不实现原文授权/预览/审计表/Agent/生命周期/通知）：

- 模型：`app/models/review.py`（`validation_evidences` / `review_tasks` / `review_task_evidences`，仅三表）；迁移 `0004_create_review_workflow_tables`。
- API（`app/api/review.py` + `app/services/review.py` + `app/schemas/review.py`）：
  - `GET /api/v1/reviews`（队列，业务用户；纯 admin 403；治理角色看全部，其余看自己提交/被分配的）+ `review_type`/`status` 过滤
  - `GET /api/v1/reviews/{id}`（提交人/审核人/治理/项目 PM 可见）
  - `POST /api/v1/projects/{project_id}/knowledge/{asset_id}/evidence`（项目 active 成员登记证据；自动绑定到非终态 material_to_asset review 并把 pending_evidence → pending_reviewer）
  - `POST /api/v1/projects/{project_id}/knowledge/{asset_id}/confirm-asset`（创建/复用 material_to_asset review；reviewer = 项目 active PM，无 PM → 422 `reviewer_not_found`；有证据 pending_reviewer 否则 pending_evidence；不直接改 zone）
  - `POST /api/v1/reviews/{id}/approve`（仅 reviewer；需 ≥1 证据否则 422 `review_evidence_required`；非 pending 终态 409；approve → `zone=asset`）
  - `POST /api/v1/reviews/{id}/reject`（仅 reviewer；review_comment 必填；终态 409；不改 zone）
- 权限边界：纯 admin 全部业务动作 403；非项目成员不能登记证据/发起 confirm-asset（`project_membership_required`）；consultant 可登记/发起但不能 approve/reject（非 reviewer → `review_action_forbidden`）；project_manager 仅能处理分配给自己的 review。
- approve/reject **不写 audit_events / 不通知 / 不调用 Agent / 不发布公司库 / 不创建 access grant**（审计留 IMPLEMENT-09，代码注释已标注）。
- seed：新增 2 个 Alpha 项目 material 资产；`seed_dev_reviews` 为其一创建证据 + pending_reviewer 审核任务（审核人=经理 B）用于 `/review` 开发态展示；`python -m app.seed.dev_seed` 已含。
- 前端：`/review` 主队列接 `GET /api/v1/reviews`（真实字段：标题/类型/来源项目/证据数/状态），approve/reject 调真实 API 且仅 reviewer 在 pending_reviewer 时可见；角色职责/治理机制为静态说明。
- 测试：`tests/test_review_api.py`（10 用例），后端 78 passed；`npm run build` 通过；迁移 SQLite `0001→0004` 验证通过。
- **过渡口径**：新增 `ReviewTaskStatus`（pending_evidence/pending_reviewer/approved/rejected，区别于 BE-02 ReviewStatus，已由 reviewer 接受）；`validation_evidences` 加 `project_id`、`review_tasks` 加 `submitted_by`/`target_scope`/`target_project_id`（BE-02 无，便于最小闭环）；无 PM 时 422 不自动升级咨询总监。
- **IMPLEMENT-06_FIX**：
  - approve / reject 开头显式拦截非业务用户 / 纯 admin（403 `admin_business_permission_denied`），不再依赖"数据不会把 admin 设为 reviewer"。
  - 证据附件 metadata 校验（`services/review.py::_validate_attachments`）：key 含 url/download_url/file_url/path/storage 内部引用/bucket/object_key/token，或值以 `http(s)/file/s3/oss/internal://` 开头时返回 422 `attachment_metadata_forbidden`，且不创建 evidence；仅允许安全占位 metadata。
  - 补齐非项目成员 confirm-asset 测试（403 `project_membership_required`）。

## IMPLEMENT-07：原文预览凭证最小闭环

实现"申请受控预览凭证 → 平台受控占位入口"的最小闭环（IMPLEMENT-07 当时不实现真实文件/对象存储/ONLYOFFICE/access_grants/审计）。**现状**：ONLYOFFICE 真预览已由 R7 落地、审计由 IMPLEMENT-09 落地、原文授权由 PBC-06 落地（预览原文层会叠加 active `access_grant`）：

- 模型：`app/models/preview.py`（`preview_credentials`，仅一表）；迁移 `0005_create_preview_credentials`。枚举新增 `PreviewType` / `CredentialStatus`。
- API（`app/api/preview.py` + `app/services/preview.py` + `app/schemas/preview.py`）：
  - `POST /api/v1/knowledge/{asset_id}/preview`：复用权限服务，拥有 original 层权限签发 `preview_type=full`；返回 `credential_id`/`preview_type`/`credential_fingerprint`/`preview_entry_url`/`expires_at`/`credential_status`。
  - `GET /api/v1/preview/{credential_id}`：平台受控占位入口，校验状态/过期/资产 active，更新 used_at/last_used_at，返回占位 metadata（不加载真实文件）。
- 安全：只存 `token_hash`（sha256），**不返回明文 token**；`credential_fingerprint` = 哈希前 16 位（可对外）；`preview_entry_url` = 平台相对路径 `/api/v1/preview/{id}`（非对象存储签名 URL）；响应不含 storage_ref/source_file_ref/bucket/对象存储 URL。默认有效期 30 分钟（`PREVIEW_TTL_MINUTES`）。
- 权限边界：纯 admin 403 `admin_business_permission_denied`；无 original 权限（含 L3/L4 denied、仅 summary）一律 403 `original_requires_request`（不签 summary_only，引导到真实原文访问申请；**PBC-06 起预览原文层叠加 active `access_grant`**，授权通过后签发 full）；L5 普通用户 404 不泄露、boss/咨询总监签发 full；archived/deprecated 403 `asset_not_active` 且不创建凭证；A4 仅限制 agent 上下文、不阻 human preview。入口仅凭证申请人可用。
- 前端：`/knowledge/:id` 原文预览按钮在 `access.original` 时可"申请受控预览"，签发后展示 preview_type/指纹/有效期 + "打开受控预览"链接（平台相对入口，占位 metadata，不加载真实文件、不展示完整 token/对象存储 URL）。
- 测试：`tests/test_preview_api.py`（9 用例），后端 89 passed；`npm run build` 通过；迁移 SQLite `0001→0005` 验证通过。
- **过渡口径**：本阶段仅 full 凭证；GET 入口为占位（不渲染真实文件）；过期/状态比较对 SQLite naive 时间做 UTC 归一（`_as_aware`）。
- **IMPLEMENT-07_FIX**：
  - 签发时校验 `version_id`：为空用 `current_version_id`；非空必须存在且属于本资产（否则 404 `version_not_found`）且 `version_status=active`（否则 403 `preview_type_not_available`）；不满足不创建凭证。
  - `GET /api/v1/preview/{id}` 开头显式拦截非业务用户 / 纯 admin（403 `admin_business_permission_denied`），早于 credential 查询。

## IMPLEMENT-08：Agent Gateway 最小闭环（历史；provider 中立网关的早期桩，PBC-01 后为外部 Agent / 工作流网关）

实现"项目 Q&A 进入平台权限网关 → 以真实调用人身份复用集中权限判断 → 记录调用 / 决策 / 候选项 / 引用 → 返回确定性 stub 回答与安全引用"的最小闭环。**不接真实 Dify / LLM / 向量库**，使用 `internal_stub` 桩 provider。

- 模型：`app/models/agent.py`，仅四张表 `agent_calls` / `agent_gateway_decisions` / `agent_gateway_decision_items` / `agent_call_citations`；迁移 `0006_create_agent_gateway_tables`。枚举新增 `AgentProvider`（仅 `internal_stub`）/ `AgentCapability`（本阶段仅 `qa`）/ `AgentCallStatus` / `GatewayDecisionStatus`。**不新增** `agent_whitelist_rules` / `agent_registry` / `permission_rules` / `access_grants` / `original_access_requests` / `audit_events` / 向量索引 / Dify 配置密钥表。
- API（`app/api/agent.py` + `app/services/agent.py` + `app/schemas/agent.py`）：
  - `POST /api/v1/projects/{project_id}/qa`：创建 `agent_calls` → 从当前项目 `scope=project & asset_status=active` 资产做关键词/最近创建的**粗召回**（无真实向量库）→ 对每个候选 `permission.decide(..., channel=agent)` 三层判断写 `decision_items` → 按 `returned_layer` 裁剪 → 生成确定性 stub 回答 → 写 `agent_call_citations`。
  - `GET /api/v1/agent-calls/{call_id}`：调用人本人 / boss / 咨询总监可见；纯 admin 403 `admin_business_permission_denied`；他人业务用户 404。响应含 `query_text` + 人类可读名 `caller_name` / `project_name`（对齐契约 §15，治理展示用；各一次主键查询，无 N+1）。
  - `GET /api/v1/agent-calls/{call_id}/decision-items`：同一可见性；过滤 `l5_not_discoverable` / `personal_asset_not_owned` 项，避免反查 L5 / 他人个人知识存在性。
- `provider`：固定 `internal_stub`（平台抽象桩标识，**不是** provider 内部敏感标识）。不引入外部 Agent SDK，不保存 provider 内部标识（如 Dify 适配器的 app_id / workflow_id / dataset_id / api_key）。
- 权限与安全边界：
  - 纯 admin / 非业务用户发起 Q&A → 403 `admin_business_permission_denied`；非项目成员 → 403 `project_membership_required`；inactive 用户 → 403 `user_inactive`；非 `qa` 能力 → 403 `agent_capability_denied`。
  - **A4 资产**在 `channel=agent` 请求 original 被 `decide()` 拒绝 → `original_allowed=false`，`returned_layer` 落到 `summary`，不进原文上下文。
  - **L5** 对普通 consultant `discovery_allowed=false`，不进引用、不在可见 decision-items 暴露；**archived/deprecated** 被候选 SQL 过滤，不进候选 / 引用。
  - 全部候选被拒（或无候选）→ 403 `agent_scope_denied`，不编造引用。
  - citation 必来自 allowed decision_items（`returned_layer ≠ null`），`used_access_layer = returned_layer`，**不超过** returned_layer。引用字段名为 `cited_zone`（对齐契约 §10，值仍 `material / asset`）。
  - 响应与 schema 不含 storage_ref / source_file_ref / vector_id / api_key / dataset_id / workflow_id / bucket / 对象存储 URL / provider 内部标识（如 Dify）/ chunk 原始主键。
- 前端：`/project/:id/knowledge` 阶段问答**主流程接真实 API**（`projectQa` → `POST /projects/{id}/qa`），展示回答文本、`model_key`、`decision_status`、`call_id` / `trace_id`、引用列表（标题 / `cited_zone` / `used_access_layer`）；非项目成员 / admin / 无可用上下文时展示后端业务原因。路由 `:id` 在 Demo 导航里是占位串，因此从 `/auth/me` 解析"本次问答实际所在项目"。页面的生命周期阶段、KPI、风险、治理提示、知识卡片网格**仍为静态 mock**。
- 测试：`tests/test_agent_api.py`（9 用例），后端 **101 passed**；`npm run build` 通过；迁移 SQLite `0001→0006` upgrade / downgrade 验证通过。
- **本阶段未实现**：真实 Dify / LLM 调用、Dify SDK / Gateway Tool、agent registry / whitelist 配置与管理 API、真实向量检索 / embedding / pgvector、access_grants / original_access_requests、audit_events、Agent 推荐升格 / 更新 / 风险抽取、Agent 治理写动作（审核 / 确认资产 / 登记证据 / 授权原文 / 归档 / 废止 chunk / 替换版本）、流式响应、WeCom / ONLYOFFICE / 对象存储。chunk 级召回留空，故 `is_pending_review` 恒为 false。

## IMPLEMENT-09：审计日志与 trace_id 贯穿（最小闭环 + 回填已实现模块）

新增 `audit_events` 一张表 + 集中审计写入服务，并回填 ingest / review / preview / agent 各写动作的审计埋点与 trace_id 贯穿；新增 Admin Audit 查询 / trace / 标记处理 API，按角色分层脱敏；`/admin/audit` 接真实 API。

- 模型：`app/models/audit.py`（`audit_events`，仅此一表，字段对齐 BE-02 §4.7）；迁移 `0007_create_audit_events`。枚举新增 `AuditLogType` / `AlertSeverity` / `AuditAction` / `AuditRiskLevel`（String 存储 + 应用层校验）。
- 集中写入服务 `app/services/audit.py`：唯一入口 `record_event`（被拒路径用 `record_denied` 写后即 commit）。
  - 角色快照：`actor_company_role` 取治理代表角色（boss > consulting_director > consultant > admin），多角色全集存 `extra.actor_company_roles`；`actor_project_role` 在动作涉及 project 时按成员关系记录。
  - 写入时脱敏（§7.1）：`before/after/extra` 经 `_sanitize` 兜底——既递归剔除 storage_ref / source_file_ref / token / api_key / dataset_id / workflow_id / kb_id / bucket / collection / vector_id / 原文正文等**禁止键**，也对**字符串值**做值级脱敏：值命中对象存储 / 文件 / 内部地址前缀（`s3:// oss:// file:// http:// https:// internal://`）或 `bucket` / `object storage` 等用语时整串替换为 `[redacted]`（递归至 dict / list），避免敏感值经无害键名落库；UUID / trace_id / 枚举值 / denied_reason / access layer / 角色 key 等安全标识不受影响。业务侧本就只应传安全元数据。
  - 事务边界：审计事件与业务写动作在同一 session / 事务内提交（业务回滚则审计同回滚）。
  - 不可变：只提供写入与「标记处理」，不提供修改 / 删除原始事实能力。
- trace_id 贯穿：`get_trace_id(request)` 从 API 层透传进 ingest / review / preview 服务（agent 已有），同一调用链所有事件共享同一 trace_id。
- 回填的 action：`ingest.task_created` / `ingest.confirmed`；`review.evidence_bound` / `review.created` / `review.approved` + `asset.zone_changed` / `review.rejected`；`preview.issued` / `preview.denied` / `preview.used` / `l5_original_access` / `preview.l5_used`；`agent.called` / `agent.allowed` / `agent.denied` / `agent.a4_original_denied`；跨模块 `admin.business_denied`。**读路径**（knowledge list/detail、my/knowledge）本轮不写审计（避免读放大写），后续可扩展。
- 强审计（severity + `extra.risk_level`）：`admin.business_denied`、`agent.a4_original_denied`、L5 原文预览签发 / 使用（`l5_original_access` / `preview.l5_used`）。
- 三视图脱敏：普通业务用户无审计查询权（403）；admin 元数据视图（不回快照、L5 事件隐藏 target_id、extra 仅安全子集）；boss / 咨询总监业务治理视图（可见快照 / title / L5 强审计，技术敏感标识本就不入库）。
- API（`app/api/audit.py`，契约 §18）：`GET /admin/audit`（过滤 + 分页 + 角色脱敏）、`GET /admin/audit/trace/{trace_id}`（按可见性脱敏，不放大权限）、`POST /admin/audit/{event_id}/mark-processed`（仅 admin；只更新处理三字段 + 追加 `audit.exception_processed`；非 exception 事件 422；幂等）。
- 前端：`/admin/audit` 三个 tab（操作 / 异常 / 登录）改接真实 `GET /admin/audit`；异常 tab「标记已处理」接 `POST .../mark-processed`；非授权角色显示后端业务原因（默认开发用户为 consultant，会显示 403，可经 `VITE_DEV_USER_ID` 切换 admin/boss/咨询总监查看）。登录 tab 展示真实 `login.*` 审计事件（本地会话登录与 R6 企微 OAuth 写入；本地无登录事件时为空态）；trace_id 说明区为静态说明。
  - 注：本节为 IMPLEMENT-09 历史实现日志；登录审计已在 IMPLEMENT-12 + R6 落地（见后文），下方「本轮未实现」按当时口径阅读。
- 测试：`tests/test_audit_api.py`（10 用例），后端 **111 passed**；`npm run build` 通过；迁移 SQLite `0001→0007` upgrade / `0007→0006` downgrade 验证通过。
- **本轮未实现**：`alert_rules` / `notification_records` 与真实告警 / 通知发送、`asset_lifecycle_events` 与生命周期审计（IMPLEMENT-10）、审计异步导出 / 留存清理、原文授权表与原文访问审计、trace_id 真实跨服务（Celery / 向量库）传播。（登录审计 `login.success` / `login.failed` / `login.logout` 已在 IMPLEMENT-12 + R6 落地，不再属未实现项。）**现状（PBC-06 已实现）**：`original_access_requests` / `access_grants` 两表、申请/审批/拒绝/撤销流、`access.original_requested` / `access.original_approved` / `access.original_rejected` / `access.original_grant_revoked` 审计及 active grant 运行时原文层放行（`decide(has_original_grant=…)`）均已落地，不再属未实现项；本行其余各项（告警 / 通知、生命周期审计、审计导出 / 清理、trace_id 跨服务传播）仍未实现。

## IMPLEMENT-10：生命周期、归档、重新启用与通知（最小闭环）

新增生命周期治理三表 + 生命周期/告警服务，落地归档「发起建议 → 人工确认」与重新启用治理动作、本地告警规则与通知记录；`/admin/alert-settings` 接真实 API，知识详情页补生命周期动作区。

- 模型：`app/models/lifecycle.py`（`asset_lifecycle_events` / `alert_rules` / `notification_records`，仅此三表）；迁移 `0008_create_lifecycle_alert_notification`（down_revision `0007_audit`）。枚举新增 `LifecycleEventType` / `LifecycleTriggeredBy` / `NotificationChannel` / `NotificationStatus`，`AuditAction` 增 `lifecycle.*` / `asset.status_changed` / `config.alert_rule_updated`。
  - 说明：`asset_lifecycle_events.trace_id` 为满足契约 §14A 事件查询响应必含 `trace_id` 字段并支持同链路串联而新增（BE-02 §4.7 原表未列），属贯穿 trace_id 的实现期补充，留待 reviewer 回写数据模型确认。
- 生命周期服务 `app/services/lifecycle.py`（治理流程，不是物理删除）：
  - 权限统一闸门 `_load_governable_asset`：纯 admin → `admin.business_denied`（强审计）+ 403；不可见资产（他人个人 / 无权 L5）→ 404 不泄露；按 scope 治理角色授权（personal 本人 / project maintainer·PM / company boss·咨询总监）→ 否则 `lifecycle_action_not_allowed`。判断收口在集中权限服务 `permission.lifecycle_visibility / lifecycle_actor_allowed / lifecycle_is_strong_audit`（`CallerContext` 增 `active_project_roles`，避免散查 ProjectMember）。
  - `archive-request`：建 `asset_lifecycle_events`（archive_warning / archive_candidate，有 candidate_source → candidate），**不改 asset_status**，审计 `lifecycle.archive_warning` / `lifecycle.archive_candidate`。
  - `archive-confirm`：置 `asset_status=archived` + `archived_at` + `archive_reason`，建 archived 事件，审计 `lifecycle.archived`；L5 / A4 / 公司级强审计（severity + risk_level）。
  - `reenable-request`：建 reenable_requested 事件，**不改状态**，审计 `lifecycle.reenable_requested`。
  - `reenable-confirm`：要求 `target_status ∈ {active, needs_update}`（否则 422 `lifecycle_invalid_target_status`），置回目标状态，**保留 `archived_at` / `archive_reason`** 供追溯，审计 `lifecycle.reenabled`；L5 / A4 / 公司级强审计。非法流转返回 409 `lifecycle_invalid_transition`。
  - `events`：按可见性返回事件（含 archived 资产可查；他人个人 / 无权 L5 → 404）。字段 `event_id/event_type/old_status/new_status/reason/actor_display/created_at/trace_id`。
- 告警 / 通知服务 `app/services/alert.py`（仅本地，**不实现真实发送**）：默认归档阈值规则（730 天未调用 + 30 天预警期）幂等落 `alert_rules`、可配置不硬编码；`GET /admin/alerts/rules`、`PATCH /admin/alerts/rules/{id}`（admin；审计 `config.alert_rule_updated`）、`GET /admin/alerts/notifications`（admin；只回安全元数据）。归档 / 重新启用确认时写一条本地站内通知（recipient = 维护人 / 所有者，安全标题 + 安全摘要内容，`send_status=pending`，可关联 `audit_event_id`）。
- 写入时值级脱敏（IMPLEMENT-10_FIX，复用审计 `audit.sanitize_text`，与 BE-09 §7 同口径）：用户文本 `reason` 在落 `asset_lifecycle_events.reason` / `knowledge_assets.archive_reason` / 各响应 / 通知前整串脱敏；`record_local_notification` 对 `title` / `content` 再做一道兜底脱敏。命中对象存储 / 文件 / 内部地址（`s3:// oss:// file:// http(s):// internal://`）或 `bucket` / `object storage` 的串整串替换为 `[redacted]`，安全文案 / 枚举 / UUID / trace_id 不受影响。
- trace_id 贯穿：生命周期事件 / 审计事件 / 通知共享同一入站 trace_id。
- 既有行为保持：archived 资产仍被知识列表（`include_archived=true` 对普通用户不放大，发现层仍按 `asset_not_active` 排除）、预览签发（`asset_not_active`）、Agent 召回（`asset_status=active` 过滤）排除；IMPLEMENT-09_FIX 审计脱敏不变。
- 前端：`/admin/alert-settings` 改接真实规则 / 通知 API（阈值 / 启用可编辑写回，审计 `config.alert_rule_updated`；非 admin 显示后端业务原因）；知识详情页生命周期区补「发起归档建议 / 确认归档 / 查看生命周期事件」动作（前端不直连、不绕权限，结果由后端裁定）。
- 测试：`tests/test_lifecycle_api.py`（13 用例，覆盖任务 1-12），后端 **126 passed**；`npm run build` 通过；迁移 SQLite `0001→0008` upgrade / `0008→0007` downgrade 验证通过。
- **本轮未实现**：定时扫描 / Celery 归档任务、真实通知发送（邮件 / 企微 / webhook）、对象存储 / 冷存储 / 物理删除、向量索引重建 / 删除、access_grants / original_access_requests、外部 Agent / 工作流执行治理动作、完整 lifecycle_change 审核流扩展（`review_task_id` 仅作可空元数据携带）、审计导出 / 留存清理、新前端路由。

## IMPLEMENT-12：真实会话身份最小闭环

把"开发态 `X-Dev-User-Id`"这一最大演示边界替换为**真实会话身份**，并保留本地开发回退。

- 会话机制：**服务端会话表 `user_sessions` + httpOnly cookie 中的不透明随机 token**。服务端只存 `sha256(token)`，**明文 token 绝不进入任何 JSON 响应**，只经 `Set-Cookie`（httpOnly / SameSite=Lax）下发（沿用 BE-08 预览凭证只存哈希口径）。模型 `app/models/auth_session.py`，迁移 `0009_create_user_sessions`（仅此一表）。
- 当前用户解析（`app/api/deps.py` + `app/services/auth_session.py::resolve_current_user`）优先级：① 有效会话 cookie → 该用户（任何环境）；② 无有效会话时**仅 local/dev/test** 回退到 `X-Dev-User-Id` / 默认开发用户；③ 否则 401 `not_authenticated`。**不改任何业务权限语义**，仅替换"当前用户从哪来"。
- API（`app/api/auth.py`）：
  - `POST /api/v1/auth/login`（**PBC-12 密码登录**）：提供 `password` → **所有环境**按 email+密码校验（`login_method=password`）；不提供 `password` → 仅 local/dev/test 走无凭证开发适配器（`login_method=dev_local`），prod 返回 403 `auth_password_required`。用户不存在 / 密码错 / 未设密码 / inactive 统一 401 `invalid_credentials`（不区分原因）。成功下发 cookie + 写 `login.success`；已知用户失败写 `login.failed`，未知 email 不写（无可归属 actor）。
  - `POST /api/v1/auth/logout`：撤销会话（置 `revoked_at`）+ 清 cookie + 写 `login.logout`。
  - `GET /api/v1/auth/me`：会话优先、开发态回退；返回身份上下文。
- 登录审计：`AuditAction` 新增 `login.success` / `login.failed` / `login.logout`（`log_type=login`），经集中 `record_event` / `record_denied` 写入，`extra` 记 `login_result` / `login_method` / `ip_address`（非敏感）。`login_method` 三种：`password`（PBC-12 密码登录）/ `wecom_oauth`（R6 企微）/ `dev_local`（开发无凭证）。**密码凭证校验已实现（PBC-12，见下）**。未知 email 登录失败不写审计（无可归属 actor）。

## PBC-12：密码凭证登录

把"本地便利登录"升级为可生产使用的密码凭证登录，保留开发便利入口与企微 OAuth。

- **模型/迁移**：`users` 增 `password_hash`（server-only PBKDF2 编码，绝不进响应/审计/日志）+ `password_set_at`；迁移 `0025`（仅 add_column，可逆）。dev_seed 给开发用户设统一开发密码 `DEV_PASSWORD`（仅 seed/测试，不入 `.env.example`）。
- **哈希服务** `app/services/passwords.py`：标准库 PBKDF2-HMAC-SHA256（260000 迭代、16B salt、`secrets`/`hmac.compare_digest`），格式 `pbkdf2_sha256$iter$salt_b64$digest_b64`；空/格式非法/未知算法 → 校验失败（不抛）；`validate_password_strength`（≥8、非全空白）；`dummy_verify` 均衡用户不存在时的时间侧信道。
- **登录** `auth_session.login_with_password`（所有环境）+ `login_local`（仅 dev）；`/auth/login` 按 password 是否提供 + env 分流（见上）。明文 session token 只经 Set-Cookie，不进 JSON；`/auth/me` 会话优先；dev `X-Dev-User-Id` 回退仍仅 local/dev/test；企微 OAuth 不改。
- **admin 设置/重置密码**：`POST /api/v1/admin/people/{user_id}/password`（**仅 active admin**；boss/咨询总监/consultant → 403 `password_set_admin_required`；纯 admin 设密码不授予任何业务原文权）。弱密码 422，未知用户 404，允许给 inactive 用户设密码但其登录仍失败。审计 `auth.password_set`（`target_type=user`，extra 仅 `password_set`/`target_user_status`/`actor_is_admin`，**绝不**含 password/hash/salt）。people 视图新增安全布尔 `password_set` + `password_set_at`（**不**返回 hash）。
- **前端**：顶栏登录加密码输入框（提交后清空、type=password）；`/admin/people` 详情加"设置/重置密码"（type=password、保存后清空、不回显）；`/help` 移除"密码登录尚未实现"，改为已接入 + login_method 说明。
- 测试：`tests/test_pbc12_password_login.py`（哈希单元；prod 密码成功/email-only 拒/错密码·未知·未设密码·inactive 统一 401；审计 login_method=password、已知失败有审计、未知 email 无 actor 审计；dev_local 仍可用；admin 设密码+重置后旧失效、非 admin 403、弱密码 422、404；审计安全；people 只回安全字段）。
- **未做（非目标）**：MFA/OTP、忘记密码/邮件找回、密码过期/轮换、账户锁定/风控限流、多设备会话 UI、CSRF 全站改造、OAuth 自动建用户。
- 前端：顶栏身份改由 `/auth/me`（会话）驱动，新增邮箱登录 / 登出最小控件（明文 token 由 httpOnly cookie 持有，前端不接触）；所有请求带 `credentials: "include"` 以携带会话 cookie，`X-Dev-User-Id` 仍作开发态回退。
- 测试：`tests/test_auth_session.py`（10 用例）+ `test_auth_me.py` 更新（prod 无会话 → 401），后端 **137 passed**；`npm run build` 通过；迁移 SQLite `0001→0009` upgrade / `0009→0008` downgrade 验证通过。
- **历史边界（IMPLEMENT-12 当时）**：当时未实现密码校验；该项**现已由 PBC-12 关闭**（所有环境 `email + password` 真实校验，`login_method=password`，见上文 PBC-12 节）。仍为后续增强：MFA / SSO、会话续期 / 滑动过期 / 多设备管理、CSRF token 全站改造、生产 cookie `Secure=True` 强制（本地 http 置 False）、未知 email 失败登录审计。（企微 OAuth / 授权码流已在 R6 实现，见后文 R6 节，state 校验、按 `users.wecom_user_id` 解析、`login_method=wecom_oauth`、未配置 `WECOM_*` 时 fail-closed。）

## IMPLEMENT-13：文件存储边界最小闭环

把"入库不写真实文件字节"这一边界替换为**受控本地文件存储**，存储引用保持 server-only。

- 存储抽象 `app/services/storage.py`：`LocalFileStorage`（dev/test 本地后端）+ `get_storage()` 依赖。`save(content, original_name)` 把字节写入 `<storage_root>/<uuid4>/<safe_name>`，返回 server-only 引用 `internal://<key>`；`resolve_path` 仅供后端读取。接口与未来 S3/OSS 后端一致，可平替。
- 安全：
  - 文件名归一化 `safe_filename`：只取 basename + 清洗为 `[A-Za-z0-9._-]`，**杜绝路径穿越**；实际 key 另含随机 uuid 段。`save`/`resolve_path` 再做 root 归属双校验。
  - 大小上限 `MAX_UPLOAD_BYTES=25MiB`：上传读取时 `file.read(MAX+1)` 即判，超限 413 `file_too_large`，不全量读入。
  - 空文件 422 `empty_file`。
  - 存储引用只写入模型 `ingest_tasks.source_file_ref`（既有禁止外泄列），**不进入任何响应 schema**；引用以 `internal://` 前缀，天然被审计值级脱敏标记覆盖（纵深防御）。
  - 被拒上传（纯 admin）在业务校验后、落盘前返回 403，**不持久化任何字节**。
- 上传写字节：`POST /api/v1/ingest/upload` 改为 **multipart/form-data**（`file` + 可选 `target_scope` / `target_project_id`）；服务在业务用户校验通过后经存储服务落盘，`source_file_size` 取真实字节数。AI 建议占位、确认流程、运营列表均不变。
- 配置：`STORAGE_ROOT`（默认 `./_local_storage`，已加入 `.gitignore`；清理本地上传删除该目录即可）。依赖新增 `python-multipart`。
- 前端：`/upload` Path B 发送**真实选中文件**（FormData，带 `credentials`），不再只发元数据；不渲染任何存储 URL。Path A 仍 mock（**现状：PBC-07 已收口为真实待确认任务面板**）。
- 测试：`tests/test_ingest_api.py` 新增用例（真实落盘 + 无泄露、空文件、路径穿越归一化、被拒不落盘，以及 IMPLEMENT-13_FIX 的存储根真实包含校验 `relative_to`、save/resolve_path 防兄弟前缀绕过）；conftest 用 `tmp_path` 覆盖 `get_storage` 保持 hermetic。后端 **143 passed**；`npm run build` 通过；无新表 / 无迁移。
- **本轮未实现**：S3/OSS 生产对象存储、公网对象 URL、ONLYOFFICE 真实渲染、真实 WeCom 微盘扫描（Path A）、真实文本抽取 / 向量化、预览真实加载文件（仍平台受控占位）。

## IMPLEMENT-14：入库抽取管线最小闭环

把"只读文件名的占位建议"替换为**真实读取文件字节、抽取文本、产出基于内容的草稿元数据**；抽取错误持久化且可审计；人工确认仍是资产创建前置。

- 抽取服务 `app/services/extraction.py`：`extract_text(content, file_name, mime) -> ExtractionResult(text/status/error_type/error_message/char_count)`。按扩展名 / mime 路由——`txt/md/csv/...` 直读（UTF-8，`errors=replace` 稳健回退）、`pdf` 用 `pypdf`、`docx` 用 `python-docx`；其余（xlsx/pptx/图片等）→ `unsupported`（不崩溃、不阻断）；抽不到文本 → `empty`；损坏 / 解析异常 → `failed`（捕获，不抛出）。纯 Python，无系统二进制依赖（新增依赖 `pypdf` / `python-docx`）。
- 数据模型（窄 ALTER，迁移 `0010_add_ingest_extraction_columns`，down 至 `0009_session`；**不建新表、不动 knowledge 表**）：`ingest_tasks` + `source_file_hash`；`ingest_task_ai_results` + `extracted_text` / `extracted_char_count` / `extraction_status` / `duplicate_of_task_id` / `duplicate_of_asset_id`。**未新增 IngestStatus 枚举值**（复用既有值）。
- 上传流程（`create_upload`）：业务用户校验通过、落盘成功后 → 计算 `sha256` 内容哈希 → 真实抽取 → 据**抽取文本**生成确定性建议（`_build_ai_result`，仍非真实 LLM：首个非空行作标题、前 ~200 字作摘要、`confidence` 反映抽取成败；失败/unsupported 提示"请人工补全"）。状态机：`extracted`/`unsupported` → `pending_confirmation`；`empty`/`failed` → `failed` + 持久化 `error_type`/`error_message`。**被拒上传（纯 admin）在落盘与抽取之前 403，零落盘、零抽取。**
- 去重软提示（非阻塞）：按 `source_file_hash` 命中最早任务时，写 `duplicate_of_task_id` / `duplicate_of_asset_id`（均为安全 UUID，**不暴露 storage_ref**），不硬拦截入库。
- 审计：抽取失败写 `ingest.failed`（exception，复用 BE-09 §5 既有 action；`AuditAction` 补 `ingest_failed`）；`extra` 仅安全元数据（`failure_stage`/`extraction_status`/`error_type`/`source_file_name`/mime），**绝不含抽取全文 / storage_ref / 真实路径**，复用 IMPLEMENT-09_FIX 值级脱敏作兜底。
- 读侧可见性：`extracted_text` 是业务内容——完整视图（创建人 / 治理角色）可得 `extracted_text_preview`（截断 500 字）+ 建议正文；**admin 元数据视图不返回抽取全文与建议正文**，只回运营元数据（`extraction_status`/字符数/错误/去重提示）。`AdminIngestItem` 增 `extraction_status`，列表查询 `defer(extracted_text)` 避免放大。
- 前端：`/upload` Path B 展示抽取状态 / 字数 / 截断预览 / 重复软提示 / 失败中文原因（真实 API，不渲染 storage_ref / 路径 / 对象 URL）；`/admin/ingest` mock 提示 `50 MB → 25 MiB` 对齐。
- 测试：`tests/test_extraction.py`（8 单测，含真实 PDF / docx 抽取、unsupported/empty/failed、非 UTF-8 回退）+ `tests/test_ingest_api.py` 扩展（内容建议、unsupported 待确认、失败持久化 + ingest.failed 审计无泄露、admin 不见全文、哈希去重软提示）。后端 **156 passed**；`npm run build` 通过；SQLite Alembic `0001→0010` upgrade / `0010→0009` downgrade 通过。
- **本轮未实现**：真实 LLM / 大模型抽取、脱敏管线、`knowledge_asset_chunks` 切块、embedding / 向量化（IMPLEMENT-15）、Celery / 异步 worker（IMPLEMENT-16）、OCR、xlsx/pptx/图片抽取、真实对象存储、预览真实加载文件。

## R1：WeKnora 底座接入（Client + KB 映射 + 原文入库）

把 WeKnora 从桩转为真实集成：确认入库时把**原文字节**推进 WeKnora、建 scope→KB 映射、回写底座 id 并对账解析状态。蓝图 `docs/backend/11-WeKnora集成与检索INTEGRATION_RETRIEVAL.md`（BE-12）。

- `WeKnoraClient`（`app/services/weknora_client.py`）：唯一 WeKnora 访问入口，base `${WEKNORA_BASE_URL}/api/v1`，header `X-API-Key`（校验 `sk-` 前缀）+ `X-Request-ID=trace_id`。方法 `create_kb` / `get_kb` / `upload_file`（multipart）/ `get_knowledge` / `delete_knowledge`。统一解析 `{success,data,error}`，非 success 抛 `WeKnoraError`（只带 code/message，**不含 key**）；HTTP 409 抛 `WeKnoraDuplicateError`（带已存在 doc id）。`httpx.AsyncClient` + `WEKNORA_TIMEOUT`，失败不重试。**dev/降级**：`weknora_enabled()` = base_url + api_key 都配置；未配置 → `NullWeKnoraClient`（调用抛 `weknora_not_configured`），confirm 据此**跳过索引**，app 仍可起；测试经依赖覆盖注入 fake，不打真实网络。
- scope→KB 映射：新表 `weknora_kb_mappings`（`app/models/weknora.py`，唯一约束 `(scope,owner_user_id,project_id)`）。`resolve_or_create_kb`（`app/services/weknora_kb.py`）懒创建幂等——同 scope 实体只建一个 KB，并发靠唯一冲突重查；**映射行独立提交**（不随 asset 上传失败回滚，KB 可复用）。命名 `personal_{uid}_kb` / `project_{pid}_kb` / `company_kb`。建库用 env `WEKNORA_EMBEDDING_MODEL_ID`（全平台统一、建库后不可改）。
- 业务库回写：`knowledge_asset_versions` + `weknora_kb_id` / `weknora_doc_id` / `weknora_parse_status`（前两者 server-only，第三个是安全业务状态）。迁移 `0011`（建一表 + 加三列，可逆 downgrade；**无 chunk 列、不动其它表**）。
  - 说明：迁移加了 `weknora_parse_status` 第三列（蓝图 §5"version 上记 weknora_parse_status"授权该字段），用于持久化异步解析状态，避免每次读都打 WeKnora；已显式列为 Codex 裁决点。
- confirm 改造（`ingest.confirm`）：**~~建 asset 前先 resolve KB；WeKnora 写入失败整单回滚 + 502~~（旧口径，PBC-11B 作废）**。现行（PBC-11B，见下）：阶段1 先落库资产，阶段2 解耦索引，底座失败不回滚。409 重复 → 复用既有 doc，`parse_status=duplicate`，不算失败、不重复入库（与 IMPLEMENT-14 内容 hash 软提示统一为单一去重口径）。
- 解析对账：`POST /api/v1/ingest/{task_id}/refresh-parse`（创建人/治理/admin 可触发，按需刷新，**不引 Celery**）→ `weknora.get_knowledge(doc_id)` 读 `parse_status` 回写 version，只回安全业务状态。
- 审计：成功写 `ingest.weknora_indexed`（operation，extra 仅 `parse_status`/`is_duplicate`/`scope`）；失败写 `ingest.failed`（extra 仅 `failure_stage`/`error_code`）。**审计 extra 绝不含 kb_id/doc_id/api_key/原文/storage_ref。**
- 安全：`weknora_kb_id`/`weknora_doc_id`/`weknora_chunk_id`/`weknora_api_key`/`knowledge_id`/`file_path` 加入审计 `_FORBIDDEN_KEYS`；值级脱敏标记加 `sk-`。无任何响应 schema 暴露 weknora_*。
- 配置：`WEKNORA_BASE_URL` / `WEKNORA_API_KEY` / `WEKNORA_EMBEDDING_MODEL_ID` / `WEKNORA_SUMMARY_MODEL_ID` / `WEKNORA_TENANT_ID` / `WEKNORA_TIMEOUT`（见 `.env.example`）。
- 测试：`tests/test_weknora_r1.py`（10 用例，fake client）覆盖 client 单测、KB 幂等、推送回写、parse 对账、失败回滚无悬挂、409 去重软提示、无泄露、api_key 脱敏、admin 边界不变。后端 **166 passed**；`npm run build` 通过；SQLite Alembic `0001→0011` upgrade / `0011→0010` downgrade 通过。
- **本轮未实现（R2-R8 边界）**：检索 / 两阶段 / `knowledge-search`（R3）、外部 LLM 内容处理与脱敏引擎（R2）、Dify（R4）、Celery 异步轮询（R5）、OSS/MinIO（继续 LocalFileStorage）、Ollama 脱敏（原文入库）、预览真实加载。

## PBC-11B：KB 预创建/初始化 + 索引失败可恢复（取代 R1 的"WeKnora 写入失败整单回滚"）

把知识底座生命周期接管进平台：建库即初始化模型配置、项目创建即预建 KB、入库确认与底座索引解耦。蓝图 `docs/backend/11-...INTEGRATION_RETRIEVAL.md` §7（已修订）。

- **client 初始化 wrapper**：`WeKnoraClient.initialize_kb`（`POST /initialization/initialize/:kb_id`，只发非空 chat/embedding/rerank/multimodal id）+ `get_initialization_config`（`GET /initialization/config/:kb_id`）。`NullWeKnoraClient` 补齐同名方法（抛 `weknora_not_configured`）。失败经 `_unwrap` 抛 `WeKnoraError`（只带 code/message，不含 key）。
- **建库即初始化**：`resolve_or_create_kb` 建 KB 后立即 `initialize_kb`。初始化失败**不写 active 假成功**——映射置 `init_failed` + raise；下次 resolve 命中 `init_failed` 映射会 ensure-initialized 重试，成功翻 `active`（避免孤儿 KB）。模型 id 源自 env `WEKNORA_EMBEDDING_MODEL_ID`（必需）/ `WEKNORA_CHAT_MODEL_ID` / `WEKNORA_RERANK_MODEL_ID` / `WEKNORA_MULTIMODAL_MODEL_ID`（可选）；`WEKNORA_SUMMARY_MODEL_ID` **不参与**（OQ3）。
- **项目预建 KB**：`ensure_project_kb`（`app/services/weknora_kb.py`）在 `create_project` 主事务提交后 best-effort 预建并初始化 project KB；底座未配置/失败**不阻断项目创建**（返回安全状态串，不外泄 kb_id）。API 经 `Depends(get_weknora_client)` 注入（测试可注 fake）。
- **入库状态机解耦**：`knowledge_asset_versions` 新增 `index_status`（`not_indexed|indexing|indexed|index_failed|skipped`）/ `index_error_code` / `index_error_message`（安全文案）/ `indexed_at`；迁移 `0024`（仅加四列，可逆）。`ingest.confirm` 阶段1 落库资产（`status=completed` 仅表示确认+落库）→ 提交点 A → 阶段2 `_index_asset`（resolve+upload）：成功标 `indexed`、409 标 `indexed`+`duplicate`、失败标 `index_failed`+安全 `index_error_code` + 写 `ingest.index_failed`（exception）审计，**绝不回滚已落库资产/人工校正**。未配置底座 → `skipped`。响应 `IngestConfirmResponse` 增 `index_status`；前端 `/upload` 据此提示"已提交、索引暂未完成可重试"。
- **安全/不变量**：权限判断与 `index_status` 解耦；未索引/index_failed 资产 WeKnora 召不回、不进语义检索结果，不构成越权泄露；原文预览仍走受控预览凭证链路。审计/响应/回写**绝不**含 kb_id/doc_id/api_key/原文/storage_ref/模型内部 id。
- 新枚举 `AuditAction.ingest_index_failed = "ingest.index_failed"`。
- 测试：`tests/test_weknora_r1.py`（新增 init wrapper 单测、建库即初始化、初始化失败置 init_failed 不假成功、init_failed 重试恢复、上传失败保资产标 index_failed）；`tests/test_pbc10b_...`（项目创建预建 KB、底座失败仍建项目）。
- **留给后续**：模型 CRUD/配置中心页面（PBC-11A）、索引失败批量重试/运维面板（PBC-11C）、错误提示分层（PBC-11F）。

## PBC-11C：索引状态可见性 + 失败重试 + 运维面板

把 PBC-11B 的索引状态字段变成可见、可操作的恢复闭环。蓝图 `docs/backend/11-...INTEGRATION_RETRIEVAL.md` §7.1。

- **共享索引机制**：`app/services/indexing.py::index_asset_version`（建库+初始化+上传+回写 version 索引状态 + `mark_index_failed`）。confirm（`ingest._index_asset`）与 retry（`knowledge.retry_index`）共用，与 `IngestTask` 解耦（调用方传 `file_bytes` + 安全文件元数据）。**绝不**回滚业务资产、绝不外泄 kb/doc/key。
- **状态可见**：`KnowledgeListItemOut` / `KnowledgeDetailOut` 增安全 `index_status` / `weknora_parse_status` / `index_error_message` / `indexed_at`（详情另含 `index_error_code`）；`AccessInfoOut.can_retry_index`（后端权威）。列表批量加载 current_version 索引字段（`_version_index_map`，避免 N+1）。dev_seed 已索引资产标 `index_status=indexed`。
- **单条重试**：`POST /api/v1/knowledge/{asset_id}/retry-index`（`app/api/knowledge.py`）。仅 `index_failed | not_indexed | skipped` 的 active 版本；`indexed` → 409 `knowledge_index_already_indexed`。权限 `_can_retry_index`：个人 owner / 项目 active project_manager·coach / 公司治理，治理跨项目；纯 admin → 403（不可发现 → 404）。底座未配置 → 标 `skipped` 返回；底座仍失败 → `index_failed` + 安全 error_code。审计 `knowledge.index_retry_requested|retried|retry_failed`（新枚举），区别于 confirm 的 `ingest.index_failed`。
- **运维面板**：`GET /admin/ops/indexing`（admin 或业务治理角色，`_require_ops_viewer`）。安全计数（index_failed/indexing/not_indexed/skipped/parse_pending/parse_processing/kb_init_failed）+ 最近 20 条失败资产安全摘要。**标题边界（PBC-10D）**：治理角色见真实标题；纯 admin 标题隐藏、owner 名隐藏（`title_visible=False`）。响应**绝不**含 kb_id/doc_id/api_key/内部存储引用/原文。
- **refresh-parse vs retry-index 边界**：`refresh-parse` 只读对账 `weknora_parse_status`，不重传、不改 `index_status`；`retry-index` 是「重新推进底座」唯一入口。（批量化 / reparse 见 PBC-15。）
- 前端：`/knowledge` 列表索引小角标；`/knowledge/:id` 详情「知识底座索引」区 + 重试按钮（仅 `can_retry_index`）；`/admin/ingest` 增「知识底座索引运维」面板。
- 测试：`tests/test_pbc11c_index_status_retry.py`（列表/详情安全字段无泄露、owner/PM/治理重试、非 owner/纯 admin 拒绝、重试仍失败、indexed 409、ops 面板安全 + 标题边界 + 非治理 403）。
- **留给后续**：错误提示分层（PBC-11F）、模型配置中心（PBC-11A）、微盘目录浏览（PBC-11D）、批量重试 / 后台队列 / reparse（PBC-15）。

## PBC-15：索引批量重试 / 显式 reparse / 后台队列

把 PBC-11C 留下的「批量重试 + 后台队列 + reparse 封装」补齐。运维可对筛选出的资产发起批量底座运维，进入后台作业异步执行，不在 HTTP 请求里逐条阻塞。

- **运维任务表**：`indexing_operation_jobs`（迁移 `0027`，create_table，PG/SQLite 兼容、可逆）。字段 `operation_type`(retry_index|reparse) / `status`(queued|running|completed|completed_with_errors|failed) / 安全 `scope_filter`(JSON) / `requested_by_user_id` / 时间戳 / `total/success/failed/skipped_count` / 安全 `error_code`(经 `error_catalog.safe_code`)+`error_message` / `trace_id`。**绝不**存原文 / 文件名 / storage·source ref / WeKnora kb·doc id / 上游原始 message。
- **批量 retry-index**：`POST /admin/ops/indexing/retry`（`app/api/ops.py`）。仅 ops viewer（admin 或业务治理角色，`_require_ops_viewer`）；请求体 `{scope, project_id?, statuses, limit}`，`statuses` 白名单过滤（仅 `index_failed|skipped|not_indexed`，**绝不**含 indexed），`limit` 上限 200；返回 `202` + 安全 job 摘要。
- **显式 reparse**：`POST /admin/ops/indexing/reparse`。请求体 `{scope, project_id?, parse_statuses, limit}`，选已 `indexed` 且 `weknora_parse_status ∈ {failed,pending,processing}` 且有 doc 的资产。**WeKnora 无独立 reparse 端点**，封装为「受控重传」`WeKnoraClient.reparse_knowledge`（先删旧 doc + 重新上传原文触发底座重新解析，**会更新 `weknora_doc_id` 为新 doc**）；`indexing.reparse_asset_version` 写最终 `index_status`(保持 indexed)/`weknora_parse_status`(新解析态)，失败 → `index_failed`（可再试）。与 retry-index 差异：retry 用于尚未进底座的资产（建库+首次上传），reparse 用于已进底座但解析异常的资产。
- **后台作业**：`indexing.run_operation_job` Celery 任务（`app/worker/tasks/indexing.py`，loop-local engine）+ `enqueue_indexing_operation`（eager 内联跑完 / 非 eager 排队返回 queued）。核心 `app/services/jobs/indexing_operations.py`：按安全筛选选 active 资产**标量快照**（避免循环内 `rollback()` 过期 ORM 触发 MissingGreenlet）、逐条复用 `index_asset_version`/`reparse_asset_version`，**单条失败不终止整个 job**；`failed==0 → completed`，否则 `completed_with_errors`；job 级异常 → `failed` + 安全 code/message。
- **作业查询**：`GET /admin/ops/indexing/jobs`（最近 20）。仅安全统计 + 安全筛选条件 + 安全错误文案 + 发起人姓名；**不返回**所处理资产标题 / 原文 / 文件名 / WeKnora id / 存储引用。
- **审计**：`knowledge.index_batch_retry_requested|completed`、`knowledge.index_reparse_requested|completed`（operation，新枚举）。extra 只放 `job_id` / `operation_type` / 安全 `filters` / `counts` / `trace_id`，**绝不**含标题 / 原文 / 内部 id。
- **前端**：`/admin/ingest`「知识底座索引运维」面板增批量「重试索引」（默认 index_failed，可勾选含 skipped/not_indexed，limit 20/50/100/200）、「重新解析（底座）」按钮（文案明确这是底座解析运维、不改权限放行）、最近作业列表（类型/状态/计数/发起人/时间/安全诊断）。不渲染任何 kb/doc id / 存储引用 / token。
- 测试：`tests/test_pbc15_indexing_operations.py`（入队权限 admin/治理可·普通业务用户拒、批量执行多条 index_failed→indexed、单条失败不影响其他条 completed_with_errors、indexed 不被选中、reparse 受控重传刷新解析、refresh-parse 仍只读不重传、job list/审计无标题·原文·WeKnora id·storage/source ref 泄露、纯 admin 无标题泄露）。
- **仍未实现（非目标）**：OCR / 扫描件识别、结构保持式文件重写、Ollama/LLM 脱敏、历史资产全量重索引策略系统。

## PBC-16：Knowledge 运营洞察 API

把 `/knowledge` 右侧的本地规则洞察升级为**真实后端安全聚合**。

- **API**：`GET /api/v1/knowledge/ops-insights`（`app/api/knowledge.py`，注册在 `/knowledge/{asset_id}` 之前避免 UUID 误匹配）。参数 `scope`(personal|project|company|all) / `project_id` / `days`(默认30,≤180) / `limit`(默认10,≤50)。响应：`title_visible` / `cards` / `indexing` / `access` / `lifecycle` / `recommendations` / `recent_items`。
- **权限矩阵**（`knowledge_insights._require_access` + `_asset_visibility_conditions`）：未登录/inactive/非业务非 admin → 403 `insights_forbidden`；纯 admin（系统运维）→ 系统聚合但 `title_visible=false`、recent_items 标题隐藏、可见 ops 作业摘要；boss/咨询总监 → 公司/跨项目治理聚合 + title-visible drilldown（排除他人个人知识）；项目经理/coach/普通业务用户 → 限本人资产 + 所在项目资产聚合。**不绕过 `/knowledge` 发现权限**：他人个人知识不计入、不下钻。
- **真实信号来源**：indexing 来自 `knowledge_asset_versions.index_status`/`weknora_parse_status` + `weknora_kb_mappings.status==init_failed` + `indexing_operation_jobs`（仅 ops viewer 见作业摘要，沿用 PBC-15 边界）；access 来自 `original_access_requests`（pending / 自动审批=`reviewer_user_id IS NULL`+`status=approved` / overdue=按 `access_request_timeout_hours` cutoff 的旧 pending）；lifecycle 来自 `asset_lifecycle_events`(archive_candidate/warning)、`knowledge_assets.asset_status==needs_update`、`audit_events.action==knowledge.upgrade_recommended`。cards / recommendations 由真实计数派生（仅非零信号，空则前端显示「暂无需要处理的运营项」），**不用假数字**。
- **安全**：drilldown item 仅 `asset_id`/safe scope/index_status/safe message(`error_catalog`)/updated_at；标题按 `title_visible` 边界。响应 / 服务**绝不**含 weknora kb/doc id、storage/source ref、download URL、token/cookie/api_key、provider 内部 id、文件名、原文——这些只作 server-only 查询条件。
- **前端**：`/knowledge` 右侧 `kl-aside` 由 `fetchKnowledgeOpsInsights` 驱动，展示真实 cards / recommendations / recent 失败项 / 最近作业；空态诚实、失败显示安全错误态不回退假数据；颜色按 severity 派生（仅 UI，非业务事实来源）。删除原「运营洞察接口为后续增强」本地提示。
- 测试：`tests/test_pbc16_knowledge_ops_insights.py`（非业务非 admin 403、普通业务用户限本人/项目范围且跨项目不下钻、纯 admin title 隐藏但计数在、治理 title 可见 + 公司范围、indexing/access 真实统计、overdue 依赖 timeout 规则、空态诚实、days/limit clamp、无 WeKnora id/存储引用/文件名泄露）。
- **仍未实现（非目标）**：OCR、结构保持式文件重写、Ollama/LLM 脱敏、历史资产全量重索引、登录安全进阶。

## PBC-17：生产部署守卫与安全烟测

把"上线前可验证的安全/运行守卫"做成代码可测、脚本可跑、文档可执行的闭环（**无新 API 形状、无新 migration**）。

- **Cookie Secure 生产守卫**（`app/core/config.py` + `app/api/auth.py`）：新增 `SESSION_COOKIE_SECURE`（默认 None=按环境推断）。`session_cookie_secure(settings)` 统一决定有效 Secure：**`APP_ENV=prod` 强制 True**（即使显式注入 `false` 运行时也不退让），非 prod 读配置、默认 False（便于 http://localhost）。login / OAuth `wecom/start` state / OAuth `wecom/callback` 三处会话/state cookie 经统一 helper（`_set_session_cookie` / `_set_oauth_state_cookie`）下发，不再各自硬编码 `secure=False`。`session_cookie_secure_misconfigured()`：prod 下显式 `false` → `/health/config` 报 blocker（运行时仍被强制安全，但向运维诚实暴露错误配置）。
- **`/health/config` 生产就绪诊断**（`app/api/ops.py`）：在 `integrations` / `missing_config` 之外新增 `production_ready` / `production_blockers` / `production_warnings`（**只回安全项名 / 布尔，绝不回值/密钥/URL/连接串/内部 id**）。blockers **仅 prod 评估**（非 prod 恒空，避免误判本地 eager 开发为失败）：`CELERY_TASK_ALWAYS_EAGER`（prod 必须接真实 worker）、`SESSION_COOKIE_SECURE`（显式 false）、WeKnora 启用缺 `WEKNORA_EMBEDDING_MODEL_ID` / `WEKNORA_MODEL_REF_SECRET`、ONLYOFFICE 启用缺 `ONLYOFFICE_DOCUMENT_SERVER_URL` / `ONLYOFFICE_JWT_SECRET`、企微通知启用缺 `WECOM_CORP_ID/WECOM_APP_SECRET`。`production_ready = APP_ENV==prod and not blockers`（非 prod 恒 False——按定义不是生产部署）。warnings（不阻断）：`LLM_NOT_CONFIGURED` / `WEKNORA_NOT_CONFIGURED`。
  - **为什么 ONLYOFFICE_JWT_SECRET 是 blocker**：代码 `build_view_config` 仅在配了 secret 时签 JWT；生产 Document Server 通常**强制 JWT**，未签名 config 会被拒/不安全，故 prod 启用 ONLYOFFICE 时把缺 JWT secret 视为硬阻断（与"生产安全签名"对齐）。
- **安全烟测脚本**（`scripts/production_smoke.py`，**纯标准库**，不读 `.env`、不调 `docker compose config`）：参数 `--base-url`（默认 `$KAP_BASE_URL` 或 `http://localhost:18080`）/ `--fail-on-production-blockers` / `--json`。探活 `/health`、`/health/ready`、`/health/config`（只摘白名单安全字段）、前端入口 `/`（HTML+200）、未登录 `/admin/ops/summary`（401/403=鉴权生效）。**输出只打印端点名 / HTTP status / 安全字段摘要**，绝不打印响应正文 / Authorization / cookie / api_key / 连接串。退出码：health 或 ready 不通过 → 非 0；`--fail-on-production-blockers` 且存在 blockers → 非 0；admin 401/403 → 0。
- **trace_id 跨链路回归**（已存在的传递经测试锁定，本轮无功能改动）：HTTP `X-Trace-Id` → enqueue → worker service（`ingest.ai_extracted`/`ingest.failed` 审计）/ 索引作业（`indexing_operation_jobs.trace_id` 落库 + WeKnora upload/reparse 收到同一 trace_id + 完成审计沿用）均沿用同一 trace_id；trace_id 仅作链路关联，**不是鉴权凭证、不放大数据访问**。
- 测试：`tests/test_pbc17_production_guards.py`（cookie secure 规则 + prod login/start/callback Set-Cookie 含 Secure + 本地不强制；`/health/config` 各 blocker / production_ready；trace_id 跨 HTTP→worker→WeKnora→审计）、`tests/test_pbc17_production_smoke.py`（脚本 redaction / 安全摘要 / HTML 判定 / 退出码 / 无密钥输出，用 fake opener，不启动 Docker）。`tests/conftest.py` 测试 client 改用 `https://test` 基址，使 prod 守卫下发的 Secure cookie 在 cookie jar 中正常回送。
- **仍需真实运维执行（PBC-17 不替代）**：真实域名、HTTPS/TLS 证书与反代、WeCom trusted callback domain、真实 secret 注入（WeKnora/LLM/企微/ONLYOFFICE）、镜像重建、DNS、对象存储、指标/告警后端接入。**不做** K8s/Helm/云密钥管理/真实公网部署，**不建议**运行会展开 `.env` 密钥的 `docker compose config` 完整输出。

## PBC-18：登录失败守卫与安全审计

最小登录失败风控闭环：记录失败尝试、按不可逆标识短时锁定 / IP 限流、保持统一用户态错误、给审计/运营留不可逆安全线索。**不做** MFA / 找回密码 / 密码轮换 / 多设备会话 / 全站 CSRF。

- **新表 / migration**：`auth_login_attempts`（`app/models/auth_security.py` + 迁移 `0028_auth_login_attempts`，PG/SQLite 兼容、可逆）。字段全为 server-only 安全统计：`identifier_hash`(HMAC-SHA256，不可逆) / `identifier_hint`(hash 前缀) / `user_id`(已知用户，未知 email=null) / `ip_hash`(HMAC，无原始 IP) / `login_method` / `result`(failed/success/locked/rate_limited) / `reason_code` / `trace_id` / `created_at`。索引 `(identifier_hash,created_at)`/`(ip_hash,created_at)`/`(user_id,created_at)`。**绝不**存 raw email / password / hash / salt / digest / session token / OAuth state / cookie / token_hash / 原始 IP。
- **配置**（`config.py`）：`AUTH_ATTEMPT_HASH_SECRET`（仅 HMAC key，绝不外泄；prod 必须配置——缺失 → `/health/config.production_blockers` 含 `AUTH_ATTEMPT_HASH_SECRET`；非 prod 空值回退稳定常量）+ `AUTH_FAILED_WINDOW_MINUTES`(15) / `AUTH_MAX_FAILED_ATTEMPTS`(5) / `AUTH_LOCKOUT_MINUTES`(15) / `AUTH_IP_FAILED_WINDOW_MINUTES`(15) / `AUTH_IP_MAX_FAILED_ATTEMPTS`(30)。服务层对 `<1` 的非法阈值钳制为安全默认（绝不无限放行）。
- **服务**（`auth_security.py`）：`normalize_login_identifier`(去空白+小写) / `hash_login_identifier(value, purpose)`(HMAC，purpose 命名空间隔离 identifier vs ip) / `check_login_guard` / `record_login_attempt` / `record_login_success`。锁定语义：identifier 维度自**最近一次成功之后**、窗口内失败类计数达阈值且距最近失败不足 `lockout_minutes` → locked；IP 维度窗口内失败达阈值 → rate_limited；成功写 success 后 identifier 失败计数从此重置。
- **`/auth/login` 集成**（`auth.py` + `auth_session.py`）：password 登录先 `check_login_guard`；命中则**不做真实 PBKDF2**（也不 dummy_verify）直接安全拒绝——这是有意为之的资源保护：锁定的目标就是停止在暴力尝试下消耗 PBKDF2，而统一 401 + 已知/未知 identifier 同样处理已消除账号枚举，残留的计时差异只暴露"该 identifier/IP 当前被限流"（非账号存在性）。正常路径：成功写 success attempt + `login.success`；失败写 failed attempt，已知用户保留归属 `login.failed`，未知 email 改写 `record_system_event(actor=None)` 的 `login.failed`。
- **统一错误**：未知用户 / 密码错 / 未设密码 / inactive / locked / rate_limited 一律 401 `invalid_credentials` + 同一文案「邮箱或密码错误，请稍后再试」，**不区分**、不返回 429（避免限流状态成为枚举信号）。前端只显示该安全文案，不显示阈值 / 锁定原因。
- **审计**：新增 action `login.locked` / `login.rate_limited`（系统事件，actor=None）；未知 email 失败用系统 `login.failed`。extra 只含 `login_result` / `login_method` / `reason_code` / `identifier_hash_prefix` / `ip_hash_prefix` / `failed_count` / `window_minutes` / `lockout_minutes`——**绝不**含 raw email / email 域名 / password / hash / salt / digest / raw IP（系统事件）/ token / cookie / OAuth state。已知用户 `login.failed` 沿用既有口径（含 `ip_address`）+ 补安全 `reason_code` / `identifier_hash_prefix`。
- **前端**：`/admin/audit` 登录 tab 为 `login.locked` / `login.rate_limited` 补安全中文 label（`auditDisplay.ts`）；不展示内部阈值 / hash 全量。
- **测试**：`tests/test_pbc18_auth_failed_login_guards.py`（known/unknown 失败记录、锁定后跳过真实 verify、统一 401 不泄露锁定态、成功重置预算、IP 限流服务层、阈值钳制、hash 不可逆+purpose 隔离、prod 缺 secret blocker、非 prod 不阻断、attempts/审计/响应无泄露）。
- **后续（本任务明确不做）**：MFA/OTP、找回密码/邮件找回、密码轮换/强制过期、多设备会话 UI、admin 手动解锁 API、查看用户锁定状态页（如需 admin-only 解锁留作后续）。

## PBC-19：Cookie 会话 CSRF 防护

为浏览器 cookie 会话下的有副作用请求提供统一 CSRF 校验（**无新业务表 / 无 migration**）。**不做** MFA / 找回密码 / 密码轮换 / 多设备会话 / OAuth 自动建用户。

- **token 机制**（`app/services/csrf.py`）：无状态签名 token `"{expiry}.{nonce}.{sig}"`，`sig=HMAC-SHA256(key=CSRF_TOKEN_SECRET, msg=f"{expiry}.{nonce}.{session_binding}")`，`session_binding=sha256(raw kap_session)`（无会话=`"anon"`）。绑定 session → 一个会话签发的 token 不能跨会话重放；带过期；synchronizer-token 形态（JSON 下发 + `X-CSRF-Token` 头回送，**不**下发可读 CSRF cookie）。`CSRF_TOKEN_SECRET` 仅 HMAC key，prod 必须配置（缺失 → `/health/config.production_blockers` 含 `CSRF_TOKEN_SECRET`），非 prod 回退稳定常量。
- **发放端点**：`GET /api/v1/auth/csrf`（安全方法，自身免校验）→ `{csrf_token, expires_at}`，绑定当前 `kap_session`（或 anon）；**不返回** session token / cookie 值 / secret。
- **中间件**（`app/core/csrf.py::CsrfMiddleware`，注册在 `TraceIdMiddleware` 内层 → 403 仍带 `X-Trace-Id`）：仅当 `method∈{POST,PUT,PATCH,DELETE}` **且** 带 `kap_session` cookie **且** 无 `Authorization` 头 **且** path 非豁免时校验；在业务 handler 前 fail-closed → 失败请求无业务写入 / 无业务审计。校验无状态（HMAC + cookie 派生绑定，**不触 DB**）。
- **三类请求**：①cookie 会话 unsafe → 必须带有效 `X-CSRF-Token`，否则 403；②dev `X-Dev-User-Id`（无 cookie）→ 跳过；③`Authorization: Bearer`（外部 Agent / Dify）→ 跳过（Bearer 鉴权不依赖 ambient cookie，不在 CSRF 面）。
- **登录 / 登出 / OAuth 边界**：`/api/v1/auth/login` 豁免（新用户登录前不可能持 token，登录成功前端随后取新 token）；`/auth/logout` 受 CSRF 保护（unsafe + cookie）；WeCom OAuth `start`/`callback` 为 GET（安全方法）天然不校验，OAuth state 校验语义不变（不把 OAuth state 当全站 CSRF token）。
- **失败响应**：统一 403 + 安全 reason_code（`csrf_token_missing` / `csrf_token_invalid` / `csrf_token_expired`）+ 固定用户文案「请求校验失败，请刷新页面后重试」，**不回显** token / cookie / header 值。
- **CSRF 失败不写审计**：避免攻击流量放大审计；依赖 HTTP 访问日志 / metrics（`TraceIdMiddleware` 已记 method/path/status/trace_id）。测试证明失败请求不产生业务写入 / 业务审计。
- **前端**（`src/api/client.ts`）：CSRF token 仅**内存缓存**（绝不入 localStorage/sessionStorage）；`ensureCsrfToken()` 取并缓存，所有 unsafe API 自动带 `X-CSRF-Token`；CSRF 403 时刷新一次 token 重试（仅一次，不循环）；登录成功后清旧 token 并预取绑定新会话的 token，登出后清理。
- **配置**：`CSRF_TOKEN_SECRET`（prod 必配）+ `CSRF_TOKEN_TTL_MINUTES`(720)。
- **测试**：`tests/test_pbc19_csrf_guard.py`（缺/无效/过期 403、有效成功、session 绑定、login 豁免、dev/Bearer 不误伤、OAuth callback GET 不受影响、CSRF 失败无业务写入/审计、prod blocker、service 单元）；`tests/test_auth_session.py` / `tests/test_pbc12_password_login.py` 的 cookie 会话 mutation 用例改为先取 `/auth/csrf` 再带 `X-CSRF-Token`。
- **未做**：MFA / 找回密码 / 密码轮换 / 多设备会话 UI / OAuth 自动建用户 / WebAuthn / WAF。

## PBC-20：登录风控运维 + 手动解锁

admin-only 登录风控运营闭环：安全聚合面板 + 手动解除 identifier 短时锁定（**无新表 / 无 migration**）。**不做** MFA / 找回密码 / 多设备会话 / WAF / IP 黑名单 / 删历史 attempt。

- **API**（`app/api/ops.py` + `app/services/auth_security_ops.py`，复用既有 `/admin/ops/*` 风格 + `_require_admin`）：
  - `GET /admin/ops/auth-security`：参数 `window_minutes`(默认60,≤7d) / `limit`(默认20,≤100) / `result`(failed|locked|rate_limited|success|unlocked 可选过滤)。响应 `window_minutes` + `counts`(failed/locked/rate_limited/success/unlocked/unique_identifier_count/unique_ip_count) + `recent_events`（`attempt_id` / `identifier_hash_prefix`(≤12) / `ip_hash_prefix` / `user_id` / `user_name`(仅已知用户) / `user_status` / `login_method` / `result` / `reason_code` / `created_at`）。**只读、不写审计**（避免读放大）。
  - `POST /admin/ops/auth-security/unlock`：二选一 `user_id`（推荐，后端从 `users.email` server-only 算 identifier_hash）或 `identifier_hash_prefix`（≥8 位且近期唯一）；可选 `reason`(≤200)。响应 `{ok, unlocked, user_id, identifier_hash_prefix, reset_at}`。cookie-auth unsafe → 受 **PBC-19 CSRF** 保护。
- **reset anchor**（PBC-18 复用）：`auth_login_attempts` 新增 `result="unlocked"` 语义（**无 enum 表 / 无 migration**，result 本就是 String）。`check_login_guard` 的 `_FAILED_RESULTS` **不含** unlocked；`_last_reset_anchor_at` 把 reset anchor 从「仅 success」扩展为 `("success","unlocked")`——unlocked 锚点（最新）使 identifier 失败计数从其之后重算 → 解除锁定。
- **手动解锁语义**：只写一条 `result="unlocked"`（`ip_hash=None`、`login_method="manual_unlock"`、`reason_code="manual_unlock"`）reset anchor + `auth.lockout_unlocked` 审计；**不**删历史 attempt、**不**绕过密码校验、**不**建会话、**不**改密码、**不**重置 IP rate limit（anchor 不带 ip_hash，IP 维度照常统计）。
- **prefix 唯一性 + 字面 hex**（含 PBC-20-Residual）：`identifier_hash_prefix` 先 `strip().lower()`；长度 <8 → 422 `unlock_prefix_too_short`；非十六进制（`[0-9a-f]+` 之外，含 SQL `LIKE` 通配符 `%`/`_`、空白、`-`）→ 422 `unlock_prefix_invalid`（identifier_hash 是 sha256 hex，强制 hex 后 `LIKE prefix+"%"` 不含任何用户可控通配符，按字面前缀匹配）；近期无匹配 → 404 `unlock_identifier_not_found`；匹配到多个 distinct identifier_hash → 409 `unlock_identifier_ambiguous`；唯一 → 解锁。不接受 raw email。
- **权限矩阵**：仅 active admin（`_require_admin`，缺权 403 `ops_admin_required`）；boss / 咨询总监 / consultant / project_manager / coach 全部 403。纯 admin 访问登录风控**不**获得任何业务知识原文 / 标题 / 文件名权限（端点只返回风控数据）。
- **审计**：`auth.lockout_unlocked`（log_type=`operation`，actor=admin）。extra 仅 `target_user_id`(如有) / `identifier_hash_prefix` / `reset_attempt_id` / `matched_attempt_count` / `window_minutes` / `unlock_reason`(可选,截断)。**绝不**含 raw email / raw IP / 完整 identifier_hash·ip_hash / password·hash·salt·digest / session token / token_hash / cookie / OAuth state。
- **前端**：`/admin/auth-security`（导航「登录风控」）。计数卡 + 最近事件表（安全显示名 / hash 前缀 / 原因 / 时间）+ 对可定位锁定事件的「解锁」按钮（用 `user_id` 或 hash 前缀）；解锁成功刷新；失败显示安全文案；CSRF 由统一 client 自动附带；不在 localStorage/sessionStorage 存任何 token/hash。
- **测试**：`tests/test_pbc20_auth_lockout_ops.py`（admin 可看；boss/director/consultant/pm 403；无泄露；user_id 解锁后正确密码可登录；解锁不重置 IP；prefix 唯一/不存在 404/多匹配 409/过短 422；审计安全；无 CSRF 解锁 403 且无审计；有 CSRF 成功）。

## PBC-21：账号安全变更时撤销平台会话

最小生产级会话撤销闭环：账号停用 / 改密 / admin 强制下线时撤销目标用户的平台会话（**复用既有 `user_sessions.revoked_at`，无新表、无 migration**）。**不做** MFA / 找回密码 / 设备指纹 / 风险评分 / 多设备管理产品。

- **撤销服务**（`app/services/session_revocation.py`）：`revoke_user_sessions(session, user_id, *, exclude_token_hash=None)` 把目标用户「未撤销且未过期」的会话标记 `revoked_at`（**不删行**），可排除当前会话；`list_sessions` / `active_session_count` 返回安全元数据。`token_hash` 仅作 server-only 比对（标记 / 排除当前会话），**绝不**外泄。
- **API**（`app/api/ops.py`，admin-only `_require_admin`）：
  - `GET /admin/ops/sessions/users/{user_id}` → `{user_id, active_count, sessions[{session_id, login_method, created_at, last_seen_at, expires_at, revoked_at, active, is_current_actor_session}]}`。`session_id` 是 `UserSession.id`（安全行标识，**非** token hash）。**绝不**返回 token / token_hash / cookie / ip / device_info / user-agent。
  - `POST /admin/ops/sessions/users/{user_id}/revoke`（body `{reason?, preserve_current_session?}`）→ `{ok, user_id, revoked_count, revoked_at, preserved_current_session}`。cookie-auth unsafe → 受 **PBC-19 CSRF** 保护。`preserve_current_session` 仅当目标==当前 admin 自己时生效。
- **自动撤销 hook**：
  - **改密**（`people.set_password`，已有路径）：改密成功后撤销目标用户**全部**活动会话（含 admin 改自己密码——强制重登，无保留），写 `auth.sessions_revoked` trigger=`password_reset`。
  - **停用**（新增 `POST /api/v1/admin/people/{user_id}/status`，body `{status, reason?}`，admin-only）：active→inactive 撤销目标全部活动会话，trigger=`user_deactivated`。fail-closed：不能停用自己（409 `cannot_deactivate_self`）、不能停用最后一个可用 admin（409 `last_active_admin_protected`）。inactive→active 不撤销。
  - **角色 / 项目成员变更**：**不**联动撤销——授权每请求实时从 DB 读角色 / 成员关系，无陈旧会话风险，故不加撤销。
- **权限矩阵**：admin → 全部会话运维 + 停用；boss / 咨询总监 / consultant / project_manager / coach / 普通业务用户 → 会话运维 403 `ops_admin_required`、停用 403（people admin-only）。纯 admin 仅获会话安全运维，**不**因此获得业务知识标题 / 原文 / 文件名权限。`/auth/logout` 仍是用户自助登出路径。
- **审计**：`auth.sessions_revoked`（log_type=operation，actor=admin）extra 仅 `target_user_id` / `revoked_count` / `trigger`(admin_manual/password_reset/user_deactivated) / `preserved_current_session` / `reason`(可选截断)；`config.people_status_updated`（停用/启用）extra 仅 `target_user_id` / `old_status` / `new_status`。**绝不**含 token / token_hash / cookie / OAuth state / password·hash·salt·digest / raw IP / user-agent。
- **前端**：`/admin/people` 用户详情新增「活动会话」计数 + 「撤销全部会话」「停用/启用账号」按钮（仅安全计数与状态；CSRF 由统一 client 自动附带）；`PersonOut.active_session_count` 仅详情接口返回。
- **测试**：`tests/test_pbc21_session_revocation.py`（admin 可列会话；boss/director/consultant/pm 403；无泄露；手动撤销使会话失效；停用 / 改密联动撤销；不能停用自己；无 CSRF 撤销 403 且无审计；有 CSRF 成功；preserve_current_session 保留当前 admin 会话）。

## PBC-22：企微身份生命周期同步

把平台用户生命周期对齐其绑定的企微成员有效性（**复用既有 WeCom OAuth 凭证，无新 config、无 migration、无 /health blocker**）。**不做** 自动建用户 / 组织树同步 / 部门角色映射 / 通讯录档案展示 / Celery 定时同步。

- **成员状态 wrapper**（`wecom_client.py`）：`WeComOAuthClient.get_member_status(wecom_user_id) -> WeComMemberStatus`（调官方 `GET /cgi-bin/user/get`，只读 `errcode`/`status`，**不读** name/mobile/email/department/avatar）。`normalize_member_status` 归一：`status==1`→`active`(active=True)；`2`→`disabled`、`4`→`not_activated`、`5`→`deleted`、errcode 60111/60121/46004→`deleted`、其余→`unknown`（均 active=False，**fail-closed**）。`WeComMemberStatus{wecom_user_id(server-only), active, status_code, status_message(安全中文)}`——`wecom_user_id` 不进 API 响应，`status_message` 非上游 errmsg。`NullWeComOAuthClient.get_member_status` 抛 `wecom_not_configured`。
- **OAuth 回调**（`GET /api/v1/auth/wecom/callback`）：state 校验 → 换 `wecom_user_id` → 载平台用户 → **建会话前核验成员状态**：
  - 上游/未配置错误 → fail-closed，不建会话、**不改**平台状态（避免瞬时故障误停用），写 `login.failed`(reason_code=`wecom_status_check_failed`)，401 `wecom_status_check_failed`；
  - 成员失效（disabled/deleted/not_activated/unknown）→ 停用平台用户（若 active）+ 撤销活动会话（PBC-21）+ 系统审计 `identity.user_deactivated_by_wecom_sync`(trigger=`oauth_callback`)，401 `wecom_user_inactive`；
  - 成员有效但平台用户已被 admin 停用 → 维持既有 401 `user_inactive`；
  - 未绑定平台用户 → 维持既有 403 `user_not_provisioned`（不自动建用户）；
  - 成员有效 + 平台 active → 建会话（既有 `login.success`）。绝不存/返 code/access_token/state。
- **admin 对账 API**（`app/api/ops.py` + `app/services/wecom_identity.py`，admin-only `_require_admin`，cookie-auth unsafe → PBC-19 CSRF）：`POST /admin/ops/wecom-identity/reconcile` body `{user_id?, limit=100, dry_run=false}`（`limit` clamp ≤200）。`user_id` 给定则仅对账该绑定用户（未绑定→422 `user_not_wecom_bound`，不存在→404）；否则对账 `wecom_user_id` 非空用户前 N 个。响应 `{ok, checked, deactivated, already_inactive, failed, dry_run, items[{user_id, user_name(平台显示名), previous_status, new_status, wecom_status, sessions_revoked, error_code}]}`。失效成员 → 停用 + 撤销会话；`dry_run` 只预演 `new_status` 不变更/不审计；上游错误 → 该项 `error_code`（安全 code）+failed++，**不改**状态。**不返回** raw wecom_user_id / 档案 / token / errmsg。
- **停用条件**：仅当企微成员**非 active** 且平台用户当前 active → `users.status=inactive` + 撤销活动会话。已 inactive 仅撤销残留活动会话；上游错误不停用；**不删用户、不动公司角色 / 项目成员关系 / 资产权限**。
- **权限矩阵**：reconcile → 仅 active admin；boss / 咨询总监 / consultant / project_manager / coach / 普通业务用户 → 403 `ops_admin_required`。纯 admin 仅获身份运维，**不**因此获业务标题 / 原文 / 文件名权限。回调仍是公开 OAuth 回调但 fail-closed。
- **审计**：`identity.user_deactivated_by_wecom_sync`（回调=系统事件 actor=None / 对账=actor admin）extra 仅 `target_user_id`/`trigger`(oauth_callback|admin_reconcile)/`wecom_status`(归一 code)/`previous_status`/`new_status`/`sessions_revoked`；`identity.wecom_user_synced`（对账批量摘要）extra 仅 `trigger`/`checked`/`deactivated`/`already_inactive`/`failed`/`dry_run`。**绝不**含 access_token / app_secret / OAuth code·state / raw wecom_user_id / 上游 payload·errmsg / 手机·邮箱·部门·头像等档案 / session token·hash·cookie。
- **前端**：`/admin/people` 用户详情对**已绑定企微**用户新增「企微身份对账」按钮（仅显示安全结果：成员是否失效 / 撤销会话数 / 安全文案；不显示 wecom_user_id / 档案 / token）。CSRF 由统一 client 自动附带。
- **测试**：`tests/test_pbc22_wecom_identity_lifecycle.py`（回调有效建会话 / 禁用 fail-closed 停用+撤销+审计 / 上游错误 fail-closed 不改状态 / 未绑定不自动建用户；对账单用户停用 / dry_run 不变更 / clamp limit / 未绑定 422 / 不存在 404 / 非 admin 403 / 上游错误计 failed；全程无泄露）；`tests/test_r6_wecom.py` 的 FakeOAuth 补 `get_member_status` 默认有效。

## PBC-23：生产部署 Runbook + Live Smoke

把「如何安全部署、如何不泄露密钥地检查、如何做最小 live smoke、失败后如何回滚/排障」收敛为 **repo 内可执行交付**（**无新业务功能、无新 API / migration、无真实公网部署**）。本任务是部署交付，不是业务功能。

- **新增部署文档**（`docs/deployment/`）：
  - `PRODUCTION_DEPLOYMENT_RUNBOOK.md`：阶段顺序 = ①上线前准备（git commit / 镜像 tag / migration head 一致；`backend`/`worker`/`beat`/`migrate`/`frontend` 同代码版本；`CELERY_TASK_ALWAYS_EAGER=false`；worker+beat 真实运行；共享上传存储；外部依赖连通）→ ②部署顺序（拉/建镜像 → 备份 DB → 迁移 → 起 backend/worker/beat/frontend → health/ready/config → live smoke → 观察日志与审计）→ ③域名与 TLS（前端 nginx 同源反代、TLS 终止位置、`APP_ENV=prod` 强制 Secure cookie 的 HTTPS 依赖、`X-Forwarded-*`/trace header 透传、企微可信回调域名/`WECOM_REDIRECT_URI`）→ ④验证 → ⑤回滚与排障矩阵（migration / backend / worker·beat / blocker / CSRF 403 / HTTP 下 Secure cookie / WeCom callback / WeKnora 索引 / ONLYOFFICE / nginx 404·502）。
  - `PRODUCTION_SECRET_CHECKLIST.md`：按类别（app/session/csrf/auth · db/redis/celery · WeKnora · LLM · WeCom · ONLYOFFICE · storage · frontend/反代）**只列配置项名**，标注 required/conditional/optional + 对应 `/health/config` blocker/warning/missing_config + 缺失症状 + 安全验证方式。**绝无任何值**；显式写「不要运行/粘贴完整 `docker compose config`（会展开 `env_file` secrets）」。
  - `LIVE_SMOKE_CHECKLIST.md`：自动脚本（`production_smoke.py`，含 exit code 与「为何输出不含 secrets」）+ 手工 B1–B12（未登录 admin 401/403、密码登录+登出 CSRF、企微 OAuth 配置检查、admin 可达/业务用户不可达 ops、上传 Path B upload→ai-result→confirm、索引状态可见、search 召回 indexed、index_failed/skipped 不召回、原文权限有/无授权边界、WeCom scan 配置页安全显示、ONLYOFFICE 预览、`/health/config` 无 blocker），每步注明操作人角色 / 预期 / 可观察审计 / 不应出现的敏感字段。
- **脚本增强（最小、安全）**（`scripts/production_smoke.py`）：新增 `--expect-prod-ready`，作为 `--fail-on-production-blockers` 的**别名**（`fail_on_blockers_from_args()` 把二者 OR 合并），给 runbook 更清晰入口；**未新增任何输出面**——仍只打印端点名 / HTTP status / `/health/config` 白名单安全字段，仍不读 `.env`、不调 `docker compose config`、不需 admin cookie。退出码语义不变（health/ready 不通过或 blockers 存在且要求阻断 → 非 0）。`build_parser()` 抽为独立函数便于单测。
- **测试**：`tests/test_pbc17_production_smoke.py` 新增 `test_expect_prod_ready_is_alias_of_fail_on_blockers`（`--expect-prod-ready` 与 `--fail-on-production-blockers` 解析等价、都不传为 False），不触网络、复用 fake-opener 风格。
- **边界（PBC-23 不替代真实运维）**：真实公网域名、TLS 证书申请/续期、云密钥注入、DNS、对象存储、云监控、镜像推送仍需实际运维执行；**本仓库不声称已完成真实公网部署**。**未做** K8s/Helm/Terraform/云密钥平台、OCR、MFA/OTP/短信、找回密码/邮件重置、密码轮换、完整多设备会话 UI、结构保持式文件重写、Ollama/LLM 脱敏、历史资产全量重索引。

## PBC-11A：WeKnora 模型配置中心

让 admin 不登 WeKnora 控制台即可管理底座模型与 KB 初始化配置。蓝图 `docs/backend/11-...INTEGRATION_RETRIEVAL.md` §7.2。

- **路由**：`/api/v1/admin/weknora/*`（`app/api/weknora_admin.py`），**admin-only**（company role=admin；业务角色/治理 403）。`providers` / `models`（GET/POST/PUT/DELETE）/ `models/check` / `kb-configs`（GET）/ `kb-configs/{mapping_id}/initialization`（PUT）。
- **client wrapper**（`weknora_client.py`）：`list_model_providers` / `list_models` / `get_model` / `create_model` / `update_model` / `delete_model`（`/models*`）、`update_initialization_config`（`PUT /initialization/config/:kb_id`）、`check_remote_model` / `test_embedding_model` / `check_rerank_model` / `test_multimodal_model`（`/initialization/*`）。Null client 全部抛 `weknora_not_configured`。
- **service**（`weknora_models.py`）：把底座原始结果脱敏为安全形态；前端别名 ↔ WeKnora ModelType 映射。
- **model_ref（server-only id 不外泄）**：`model_id` → 单向 HMAC-SHA256（key=`WEKNORA_MODEL_REF_SECRET`，缺省稳定常量仅 dev 兜底，**生产必须配置**——启用 WeKnora 但缺失时 `/health/config` 的 `missing_config` 会列出），对前端不可逆；`_model_ref` 对空/`"None"` id fail-closed；解析靠「实时列举 + 重算 ref 匹配」，无需 DB 表、无 migration。
- **错误兜底（PBC-11A residual）**：`/admin/weknora/*` 的所有 `WeKnoraError` 经 `_wrap_weknora` 转固定安全文案（502「底座模型配置调用失败…」/ 503 未配置），**绝不**回显上游 message（可能含 api_key/base_url/model_id/kb_id）；denied_reason 仅在 code 为简单安全标识符时透传。`create_model` 缺上游 id → 502 `weknora_model_create_no_id` fail-closed，不写成功审计、不返回 model_ref。
- **secret**：模型 `api_key`/`base_url` 仅上送、代理写底座；平台 DB 不存、响应/审计/错误不回显（审计只记 provider/type/名称，新枚举 `weknora.model_created|updated|deleted|kb_config_updated`）。连通性测试只回 success+安全文案（兜底剔除 key/url）。
- **KB 初始化配置**：用平台 `weknora_kb_mappings.id` 定位（绝不回 `weknora_kb_id`）；更新解析 `model_ref`→真实 id 调底座，成功后 `init_failed`→`active`；不改资产级 `index_status`（仍按 PBC-11C 重试）。
- **未配置**：安全 503，detail 只回 `missing_config` 项名；权限闸先于配置闸。
- **前端**：`/admin/weknora-models`（admin 导航「模型配置」）：provider/模型列表、模型创建/编辑/删除（保存后清空、绝不回显密钥）、连通性测试、KB 初始化配置选择与保存（init_failed 醒目）；未配置时只显示缺失项名。新增 `apiPut`/`apiDelete` + `ApiError.detail`。
- 测试：`tests/test_pbc11a_weknora_model_config.py`（权限、secret 只上送不回显/不入审计、model_ref 不可逆且无真实 id、kb-configs 无 kb_id、ref→server id 解析、未配置 503、连通性测试无泄露）。
- **不做**：未改 PBC-11B confirm 两段式 / PBC-11C retry-index·ops 语义；未把 `WEKNORA_SUMMARY_MODEL_ID` 接回业务摘要（OQ3）；未做批量重试 / 微盘浏览 / 错误分层。

## PBC-11F：错误提示与诊断分层

同一底座/扫描失败按受众分三层显示，但**都不**泄露密钥/真实 model id/kb id/doc id/内部存储引用/上游原始 message/payload/URL 值。蓝图 `docs/backend/11-...INTEGRATION_RETRIEVAL.md` §7.3。

- **中央目录** `app/services/error_catalog.py`：allowlist `code → {user_message, operator_message, remediation_hint, severity}`；未知 code 降级 `unknown`；别名（`weknora_down`/`http_*`→`weknora_call_failed`，`wecom_*`→`wecom_scan_failed`）。绝不把上游 message/payload/id 拼进文案。
- **用户态**（`index_error_message`）：`indexing.mark_index_failed` 写入按 code 派生；**响应层（知识列表/详情、retry-index）始终按 `index_error_code` 重新派生**（`knowledge._index_user_message`），历史脏文案永不外显，无需清洗写回。
- **运营态**：`GET /admin/ops/indexing` 的 `recent_failed[]` 新增 `operator_error_message` / `remediation_hint` / `severity`（可含配置项名，不含值/id/secret）；沿用 PBC-11C 标题边界。前端 `/admin/ingest` 面板展示运营态诊断，`/knowledge/:id` 展示用户态。
- **系统/审计**：`error_code` + `severity` + `trace` 稳定；审计 extra 不写上游 message。
- **WeKnora admin**：`_wrap_weknora` 维持固定安全文案（PBC-11A residual，不回退）。**WeCom 扫描**：既有 `error_type`(code)+固定安全 `error_message` 已合规，新增目录条目 `wecom_scan_failed`。
- 测试：`tests/test_pbc11f_error_layering.py`（目录单元；详情/retry 用户态按 code 重派生、脏文案不外显；ops 运营态三字段+标题边界；上游 leaky 错误用户态/运营态/审计均不泄露；wecom 目录安全）。
- **留给后续**：批量 retry-index/后台队列、显式 reparse —— 由 PBC-15 实现（见后文）。

## PBC-11D：WeCom 微盘目录浏览与选择

让 admin 在平台内从微盘空间/目录树选择扫描目录，不再手填 `spaceid:<id>;fatherid:<id>`。

- **client**（`wecom_client.py`）：`list_spaces` / `list_directories`（`/cgi-bin/wedrive/space_list` · `file_list`，`# pragma: no cover`）；归一抽成静态 `_to_spaces` / `_to_directories`（仅目录、丢弃普通文件）；`WeComDriveSpace(space_ref,name)` / `WeComDriveDirectory(directory_ref,name,parent_ref,has_children)`，`directory_ref` 即可保存的 `directory_path`。NullClient 补方法抛 `wecom_not_configured`。
- **API**：`GET /api/v1/admin/wecom-scan/drive/spaces` · `…/drive/directories?space_ref=&parent_ref=`，**admin-only**（`_require_admin`）。响应只回安全选择元数据；未配置 → 安全 503（仅缺失项名）；上游失败 → 502 固定安全文案；非法 ref → 422。
- **保存兼容**：选择器回填 `directory_ref` → 现有 `create/update config` + `parse_directory_path()` 校验，**无 migration**；旧手填串仍可用。
- 前端 `/admin/wecom-scan`：`WecomDirectoryPicker`（列空间 → 面包屑钻取 → 使用当前目录）+ `<details>` 高级手动输入 fallback。
- 测试：`tests/test_pbc11d_wecom_directory_browser.py`。

## PBC-11E：运行时权限规则化

把既有 `permission_rules` 接入真实权限运行时（不重写权限体系）。蓝图 `docs/backend/02-权限模型` + 审计 PBC-11E。

- **运行时 loader**（`permission_rules.py`）：`load_access_policy(session) -> DefaultAccessPolicy` 读 `cross_project_l1_l2_original_for_business_user` / `company_l1_l2_original_for_business_user` 两个 toggle。**fail-closed**：缺失→出厂默认（True，未 seed 不全锁）；**禁用/非 toggle/value 空→False**（治理端禁用即生效，绝不回 True）。`access_request_timeout_hours(session) -> float|None`：仅 enabled+numeric+>0 才返回，否则 None。
- **decide() 接入**：`decide()` 仍纯函数（默认 `DEFAULT_POLICY`）；所有业务读路径在调用前注入 runtime policy——`knowledge`（列表/详情/我的：`_build_access_info`/`_to_list_item` + discovery 过滤）、`original_access.create_request`、`preview.issue`、`retrieval`（召回逐资产 + 单资产原文取件）。关闭开关后非成员业务用户对跨项目/公司 L1/L2 最多到摘要层，原文 denied；**active access_grant 仍放大到 original**；项目成员/owner/L5 治理/grant 边界与 PBC-10D admin 边界不变。
- **超时自动审批**（`original_access.auto_approve_timed_out_original_access_requests`）：仅处理早于 `now-timeout` 的 **L1/L2** pending（L3/L4/L5 → `skipped_confidential`）；申请人须 active 业务用户、资产 active 且仍可发现、且「授予 grant 后能拿到 original」（天然排除 L5/他人 personal 硬边界）。finalize 时 `reviewer_user_id=None`（系统审批）、`review_note` 固定安全文案、按 `access_grant_duration_days` 建 active grant（已有 live grant 不重复建）。`granted_by_user_id` 非空 FK 且无系统用户行 → 记为申请人本人（自动性质以 `reviewer=None` + 审计 `auto=True` 标识，不引入 migration/假系统用户）。审计走 `record_system_event`（actor=None）`access.original_approved`，extra 仅 `asset_id/grantee/source_request_id/rule_key/timeout_hours/auto`，无原文/refs/secret。
- **Celery**：`app/worker/tasks/original_access.py`（`access.auto_approve_timed_out`）+ beat 每 30 分钟；只返回安全统计 `checked/approved/skipped_confidential/skipped_invalid/errors/enabled`。
- 前端/文档：`/help` roadmap 移除「未接入运行时」旧条目；`权限规则`/`原文访问授权` 说明改为已运行时生效；`permission_rules` 默认描述更新。
- 测试：`tests/test_pbc11e_runtime_permission_rules.py`（loader 缺失/禁用/非法 fail-closed；toggle 关闭 API `can_view_original` 变化 + grant 仍放大；自动审批各放行/跳过条件、不重复 grant、审计安全、celery wrapper）。
- **不做**：L1/L2 以外自动审批、把所有规则接运行时、改 PBC-03/06 语义、改 A4/L5 边界。

## R2：外部 LLM 内容处理（分类 / 三层摘要 / 标签 / 关键知识点）

把"内容处理"从确定性占位换成真实外部 LLM：上传期对抽取文本调 LLM 出**分类 + 三层摘要（one_liner/detailed/key_points）+ 标签**草稿,供 `/upload` 人工校正;confirm 写资产。

- LLMClient(`app/services/llm_client.py`):一个 **OpenAI 兼容**客户端(`POST {base}/chat/completions`,`Authorization: Bearer {key}`)+ provider 注册表(deepseek/kimi/qwen/glm/minimax/openai/custom 的 base_url + 默认 model)。统一 env 方案:`LLM_PROVIDER` + `LLM_API_KEY`(+ 可选 `LLM_BASE_URL`/`LLM_MODEL` 覆盖)。`response_format=json_object` + 稳健解析。MiniMax 薄 adapter(`_endpoint` 隔离其 GroupId query 差异)。**dev/降级**:`llm_enabled()`=provider+api_key 都配置;否则 `NullLLMClient`(调用抛 `llm_not_configured`),内容处理降级;测试注入 fake。`LLMError` 只带 code/message,**api_key/Bearer 绝不进异常/日志/审计/响应**。
- 内容处理(`app/services/content_processing.py`,取代 `_build_ai_result`):`process_content` 对 `extracted_text` 调 LLM → 校验 JSON(脏字段回退默认枚举/启发式)→ 写草稿;记录 `llm_provider`/`llm_model`。**LLM 是 advisory**:未配置/调用失败/JSON 解析失败一律**降级到确定性最小草稿 + 标记原因,上传绝不失败**。命名合规仍基于文件名。
- 草稿列迁移 `0012`(仅 ALTER `ingest_task_ai_results`,可逆):`suggested_one_liner`(Text) / `suggested_key_points`(JSON) / `llm_provider` / `llm_model`;`suggested_summary` 复用为 detailed。**不动其它表、不动 WeKnora 链路。**`key_points` 写资产无需迁移(summaries 为 String 存储)。
- confirm 三层摘要写穿:`_build_summaries` 扩展为建 `one_liner` + `detailed` + **`key_points`**(+ L3/L4 `redacted_summary`);`IngestConfirmRequest` 增 `one_liner`/`key_points`(可选,向后兼容)。**AI 推荐与人工确认独立存储**(系统设计 §181):suggested_* 在 `ingest_task_ai_results`,人工确认值在 `knowledge_asset_summaries`,互不覆盖。
- 脱敏引擎(`app/services/desensitization.py`,PBC-13):入库前置接口升级为返回结构化 `DesensitizationResult`(text/status/counts/error_code);`get_desensitizer()` 默认返回 **`RuleBasedDesensitizer`**(本地正则,无外部网络/新依赖),`NullDesensitizer` 仅供测试/显式禁用。覆盖邮箱/中国大陆手机号/固话/身份证号/银行卡号/长数字账号/金额表达/联系人字段/客户公司字段,占位符如 `【邮箱】【手机号】【金额】【联系人】【客户】`;规则**有序**(长/结构化标识先于泛数字),counts 只记类别与数量、**绝不记原值**。`content_processing.process_content` 抽取成功后**先脱敏**,平台侧外部 LLM 内容建议仅吃**脱敏后文本**;脱敏失败 → 平台侧 LLM 不接触原文、降级。**WeKnora 底座及其 LLM 是老板确认的受信任底座处理方**,其索引链路按该信任边界仍可接收原始文件/原文,不在本层阻断;原始文件保留在平台受控存储供授权预览/溯源。**不长期保存脱敏全文**——retry-index 重新从原始文件索引,不依赖脱敏文本。新增列迁移 `0026`(仅 ALTER `ingest_task_ai_results`,可逆):`desensitization_status`/`desensitization_counts`(JSON)/`desensitization_error_code`,均为安全元数据(非脱敏/原文)。
- 读侧:`get_ai_result` 完整视图(创建人/治理)返回三层摘要建议正文 + 抽取预览;**admin 元数据视图不返回建议正文/抽取全文**,只回 `llm_provider`/`llm_model`/`content_processing_status`(安全运营元数据,**非密钥**)。
- 审计:内容处理完成写 `ingest.ai_extracted`(operation;BE-09 §5.3 既有 action),extra 仅 `content_status`/`degrade_reason`/`llm_provider`/`llm_model` + PBC-13 `desensitization_status`/`desensitization_counts`(类别计数)——**无 api_key/Bearer/抽取全文/脱敏全文/原值**。值级脱敏标记加 `bearer `;`_FORBIDDEN_KEYS` 加 `llm_api_key`/`authorization`。
- 前端:`/upload` 展示并可校正三层摘要(一句话/详细/关键知识点每行一条)+ LLM 状态徽标(llm/降级)+ PBC-13 前置脱敏状态(已规则脱敏/未抽取无法脱敏/失败)与类别计数;不渲染任何 LLM key/base_url、不展示脱敏前后正文对比。
- 测试:`tests/test_r2_llm.py`(12 用例,fake LLM)覆盖 client provider 注册表/MiniMax endpoint、结构化解析、围栏 JSON、三类降级(未配置/失败/脏)、confirm 三层摘要写穿 + AI/人工独立、无泄露、Bearer 脱敏。后端 **178 passed**;`npm run build` 通过;Alembic `0001→0012` upgrade / `0012→0011` downgrade 通过。
- **本轮未实现(R3-R8 边界)**:检索/两阶段/`knowledge-search`(R3)、Dify(R4)、Celery 异步(R5,上传期同步调 LLM)、真实 Ollama 脱敏(Null 透传)、WeKnora 链路未改(R1)。

## R3：两阶段检索与问答（`POST /knowledge/search`）

WeKnora 检索召回 → 映射回资产 → 集中权限 `decide()` 复核 → 阶段1卡片 / 阶段2脱敏原文 / 问答自拼答案。取代 IMPLEMENT-08 的关键词桩召回与占位答案。

- `WeKnoraClient.search/hybrid_search`、`app/services/retrieval.py`（KB 路由、chunk→资产映射去重、三道过滤）、`app/services/intent.py`（6 类意图，降级默认 search）、`LlmOutputDesensitizer`（外部 LLM 输出脱敏，**no-op / 失败 fail-closed = 不返回原文**）。
- Agent provider 由 `internal_stub` 改为 **`weknora_llm`**（真实链路）。WeKnora chunk 引用存 server-only 列（`target_weknora_chunk_ref` / `cited_weknora_chunk_ref`，迁移 `0013`），审计 `_FORBIDDEN_KEYS` / 值级标记（`wk-doc`/`wk-kb`）兜底脱敏。
- 检索审计 action `knowledge.searched`（已回写 BE-09 §5）。

## R4：Dify 外部知识 / HTTP Tool 网关（PBC-01 后为兼容适配器）

把 Dify 作为**上层调用方**接入：Dify 经 Bearer 鉴权调用本平台知识权限网关，**绝不绕过**调用人权限，**不发明 Dify 超级用户**。

> **PBC-01 抽象收口（见下方 PBC-01 节）**：权限 / 检索 / 审计 / 无泄露核心已抽到 provider 中立的 `external_agent_gateway` + `schemas/external_agent`；本节描述的 Dify 端点（`app/api/dify.py` + `schemas/dify.py`）现为**兼容适配器**，只做 Dify 线缆转译，不再持有业务逻辑。

- 端点：`POST /api/v1/dify/external-knowledge/retrieval`（Dify External Knowledge 官方协议，Dify 侧端点填 `/api/v1/dify/external-knowledge`）、`POST /api/v1/dify/tools/knowledge-search`（HTTP Tool，返回 R3 SearchResponse）、`GET/POST/PATCH /api/v1/admin/permissions/agent-whitelist`（接入注册管理，admin-only）。
- 接入注册表 **`agent_whitelist_rules`**（迁移 `0014`）：沿用数据模型 §4.5 / BE-07 §11.1 表名与语义（**外部 Agent 接入注册与 capability 边界**，provider 中立，非逐 Agent 名单），R4 为 Bearer 鉴权与 provider 抽象补充 `provider` / `capability` / `token_hash` / `allowed_project_id` / `risk_level`（BE-07 §11.1 已预告 provider / capability / external_*）。**绝不存明文 token**（只存 `token_hash` sha256，明文仅创建/重置时一次性返回）；`token_hash` / `external_app_id` / `external_workflow_id` / `agent_identifier` 是 server-only，绝不进任何响应。
- 调用人身份：必须由 `metadata_condition.caller_user_id` / `X-Platform-User-Id`（External）或 `caller_user_id`（Tool）解析为真实平台用户，否则 **fail closed**（绝不以 admin / system / Dify 身份检索）。检索全程 `AccessChannel.agent`：A4 原文降级、L5 不可发现、无权只给安全摘要、他人个人不可见，全由权限网关收口。records 内容只可能是已脱敏证据 / 安全摘要，`metadata` 恒为安全 dict（asset_id/scope/zone/used_access_layer/citation_order），绝不 weknora kb·doc·chunk id / external_* / dataset·workflow·app id / token。
- 审计：注册变更 `config.agent_registry_updated`；Dify 检索复用 `knowledge.searched`（extra 记 channel=agent、provider，不记 token）。
- 测试：`tests/test_r4_dify.py`（fake WeKnora + fake LLM，不接真实 Dify）。

## PBC-01：外部 Agent 网关 provider 抽象

把 R4 的「以 Dify 为核心」的网关重构为 **provider 中立的外部 Agent / 工作流网关**，并把现有 Dify 端点保留为**适配器**。Dify 为临时集成面；长期平台核心可同时支持 Dify、未来 Coze / 自研 HTTP Agent / 内部工作流引擎，而无需重写权限 / 检索 / 审计 / 无泄露逻辑。

- **provider 中立核心**（不依赖任何具体 provider）：
  - `app/services/external_agent_gateway.py`：`resolve_caller`（fail-closed）、`parse_knowledge_selector`（中立选择器语法 all/company/project:<id>/personal:<id>）、注册行 scope/天花板收口、`run_retrieval`（→ 安全 records）。审计 `target_type=external_agent_retrieval`，extra 记 `provider`（来自注册行）。
  - `app/schemas/external_agent.py`：`ExternalRetrievalRecord`（content/score/title/metadata，metadata 仅 asset_id/scope/zone/used_access_layer/citation_order）+ 接入注册 schema（`RegistryRuleOut/...`，安全视图不含 token_hash / provider 内部标识 / agent_identifier）。
- **Dify 适配器**（provider 专属，仅线缆转译）：`app/api/dify.py`（路由不变，handler 改为薄适配，调用中立网关）+ `app/schemas/dify.py`（仅 `DifyExternalRequest` / `DifyToolRequest` 等 Dify wire 形态；注册 / record schema re-export 自 `external_agent`）。`dify_gateway.py` 已删除（逻辑迁入中立核心）。
- **注册表 provider 中立**：`agent_whitelist_rules` 既有列已支持中立语义（`provider` 列区分 dify/coze/custom；`agent_identifier` / `external_app_id` / `external_workflow_id` 为 server-only provider 内部标识，绝不进响应）。**无需迁移**——无新增 / 改列，仅服务与文档去 Dify 化。
- 兼容性：`POST /dify/external-knowledge/retrieval`、`POST /dify/tools/knowledge-search`、`GET/POST/PATCH /admin/permissions/agent-whitelist` 行为与响应不变；`tests/test_r4_dify.py` 全绿。
- 新增测试 `tests/test_pbc01_external_agent_gateway.py`：直接针对中立核心——调用人解析 fail-closed、中立选择器解析、`run_retrieval` 返回 `ExternalRetrievalRecord` 且 metadata 仅安全标识、无 provider 内部标识 / WeKnora id / 未脱敏原文泄露。
- 安全：响应 / 审计 / 前端绝不含 `api_key` / `token_hash` / `dataset_id` / `workflow_id` / `app_id` / `weknora_*` / `storage_ref` / `source_file_ref`；调用人身份解析失败一律 fail-closed；provider 与 capability 检查保持后端权威。

## R5：Celery 异步治理作业

把重活/周期性后端工作迁到真实 Celery（仅依赖 Redis/Celery，不引入其它外部系统）。

- Celery 应用 `app/worker/celery_app.py`（broker/backend 缺省回退 `REDIS_URL`；`task_always_eager` 来自 `CELERY_TASK_ALWAYS_EAGER`，默认 True 便于无 worker 运行）；任务薄包装 `app/worker/tasks/*`（自建 async 会话，不复用请求会话）；业务逻辑在 `app/services/jobs/*`（async、可直接调用、幂等、可测）。
- **异步入库**：`POST /ingest/upload` 只持久化字节 + 建 `ingest_tasks(status=processing)` + 入队；作业做抽取/R2 内容处理/写 `ai_result`/推进状态/安全审计。`enqueue`（`app/worker/enqueue.py`）：eager 模式在**当前事件循环内联同步执行**（避免嵌套 `asyncio.run`），非 eager `.delay()` 到 broker。幂等（已处理跳过、ai_result upsert 不重复建行）；瞬时失败递增 `retry_count` 尊重 `max_retries`，失败仅留安全元数据。`empty/invalid file` 与纯 admin 拒绝仍同步。
- **WeKnora 解析对账** `jobs/parse_reconcile.py`：扫 pending/processing 版本调 `get_knowledge` 回写**安全解析状态**；只更新安全字段、不暴露/审计 kb/doc id、单条失败不中断整批、幂等。手动 `refresh-parse` 端点不变。
- **生命周期归档扫描** `jobs/lifecycle_scan.py`：按 `alert_rules` 阈值（`ensure_default_rules`，缺失回退 730/30 天）产生 `archive_warning` / `archive_candidate` + 本地通知；**绝不**置 `archived`（归档仍须人工 archive-confirm）；按 asset+event_type+时间窗口去重。
- **跨项目复用 / 升格推荐** `jobs/reuse_upgrade.py`：从 `agent_call_citations` join `agent_calls.project_id` 算复用信号，回写 `last_called_at`，对被多项目复用/超调用阈值的 **project** 资产推一条**人审升格推荐**（通知 Boss/咨询总监 + `knowledge.upgrade_recommended` 审计）。**绝不**自动升格 scope/zone；按资产去重。采用**通知+审计**而非建 `project_to_company` ReviewTask——现有审核流仅实现 material_to_asset，扩展审批属本票 Non-Scope（后续：在 review 服务补 project_to_company approve 后，把推荐产物换/补为 ReviewTask）。
- 系统作业审计：新增 `audit.record_system_event`（`actor_user_id=None`，无业务发起人）；新增 action `knowledge.upgrade_recommended`。
- **无新表/迁移**（幂等用既有状态 + 事件/审计查询覆盖）。docker-compose 加 `worker` / `beat` 服务（`CELERY_TASK_ALWAYS_EAGER=false` 启用真异步）；`.env.example` 加 Celery 配置。
- 测试 `tests/test_r5_celery.py`（7 用例，直接调用 job + fake WeKnora/LLM，不需真实 Redis）。

## R6：企微 OAuth 身份 + Path A 微盘扫描

把最后的生产身份与 Path A 占位换成真实实现。

- **OAuth**：`GET /auth/wecom/start`（生成 state 写短时 httpOnly cookie + 返回授权 URL，无 secret）、`GET /auth/wecom/callback`（校验 state → 换身份 → 按 `users.wecom_user_id` 解析用户 → 建 `user_sessions`（login_method=wecom_oauth）+ login.success）。fail closed：state 无效/缺 code/换取失败/未知用户/非 active 均拒绝，不自动建用户；code/token/state 绝不持久化或进响应。dev-local 登录仍仅 local/dev/test。
- **WeCom 客户端** `app/services/wecom_client.py`：`WeComOAuthClient`（gettoken + auth/getuserinfo）+ **真实 `WeComDriveClient`**（`/cgi-bin/wedrive/file_list` 翻页列举 + `/cgi-bin/wedrive/file_download` 两步下载：换临时 URL+cookie → 后端带 cookie 取字节）。access_token / 临时下载 URL / cookie / app_secret / 上游 payload **绝不**外泄/持久化/审计/日志；失败映射为安全 `WeComError(code,...)`。扫描目录用**文档化内部格式** `spaceid:<id>;fatherid:<id>`（`parse_directory_path`，两 id 均 server-only）。测试用 fake 客户端，不打网络。
- **Path A 扫描**：`/api/v1/admin/wecom-scan/configs[...]`（读=admin/boss/咨询总监；启停+触发=admin，仅运营、不得业务原文）。`run_scan`：列文件 → 按内容 hash 去重 → 后端下载字节 → 经 `LocalFileStorage` 落盘（server-only ref）→ 建 `path_a_wecom` IngestTask(material) → **复用 R5 处理链**（与 Path B 一致）。单文件失败不中断整批；列目录失败整次 failed。
- **幂等**：手动触发支持 `Idempotency-Key`；DB 级 **部分唯一索引** `(config_id, idempotency_key)`（仅非空，迁移 `0016`，PostgreSQL/SQLite 通用）保证并发同 key 只建一条记录，冲突时回滚重查返回既有记录、不重复建任务。
- 迁移 `0015`（users.wecom_user_id 唯一索引 + wecom_scan_configs/records）+ `0016`（幂等部分唯一索引）。审计 action：`wecom_scan.config_updated/triggered/completed/failed`；审计禁止键扩展（access_token/auth_code/oauth_state/app_secret/wecom_file_id/download_url）。
- 测试 `tests/test_r6_wecom.py`（fake WeCom OAuth/Drive，不打网络）。

## R7：ONLYOFFICE 真预览 + 企微真通知

把预览入口占位与本地通知占位换成真实实现（统一配置/部署收口留 R8）。

- **预览**：`GET /api/v1/preview/{credential_id}` 返回真实 **ONLYOFFICE 只读** 配置（`app/services/onlyoffice.py`，view 模式、禁编辑/下载/打印；JWT 可选，secret 绝不入配置）。新增**平台受控取件端点** `GET /api/v1/preview/{credential_id}/file?ft=…`：Document Server 凭短时不透明 `ft`（只存 sha256 哈希 `preview_credentials.fetch_token_hash`，迁移 `0017`）回取字节，经既有 `LocalFileStorage`（按入库回链 `IngestTask.result_asset_id` 解析 server-only ref）流出。仍走集中权限 `issue_preview`（仅 original 权限、仅申请人、active 资产、L5 强审计），admin 不可签发故拿不到取件 token。**不接 WeKnora preview**。未配置/不支持类型/无源 → 安全 message（onlyoffice_not_configured / preview_type_not_available / preview_source_unavailable），绝不回退泄露原文 URL。响应/配置/头部不含 storage_ref/源引用/对象存储 URL/完整凭证 token/jwt 密钥/WeKnora id。
- **通知**：`notification_records` 仍是唯一事实源；新增可 fake 的 `WeComNotificationSender`（企微应用消息）+ 派发器 `dispatch_pending`（Celery `notifications.dispatch_pending`）。channel=wecom 的待发记录按 `users.wecom_user_id` 解析收件人下发；缺绑定/非 active/上游失败 → 安全失败（`failure_reason` 仅 code），`send_attempts` 计重试，已 sent 不重复下发，失败不回滚治理事实。消息体只含安全元数据（落库时已值级脱敏）。`default_notification_channel()` 在 `WECOM_NOTIFY_ENABLED`+企微配齐时返回 wecom（默认 in_app，不改既有行为/去重）。迁移 `0017` 加 `notification_records.send_attempts/failure_reason`。审计新增 `notification.sent/failed`（系统事件，不含正文/密钥）。
- 测试 `tests/test_r7_preview_notifications.py`（fake ONLYOFFICE 开关 + fake 发送器，不打网络）。

## R8：部署 / 可观测 / 生产配置

让 Docker 路径可复现、配置集中且不泄密、加就绪/诊断/运营可观测面，保留 R1–R7 全部安全边界。

### Docker 一键启动（PowerShell）

```powershell
docker compose build
docker compose up -d          # postgres/redis 起后，migrate 自动跑迁移，backend/worker/beat 随后启动
docker compose exec backend python -m app.seed.dev_seed   # 可选 seed（仅 dev/test）
# 冒烟：GET http://localhost:8001/health 、/health/ready 、/health/config
```

- **端口**：本机 8000 常被占用，backend 宿主端口映射 **8001**（容器内仍 8000）；前端 `vite.config.ts` 代理已对齐 `http://127.0.0.1:8001`。
- **迁移**：专设一次性 `migrate` 服务跑 `alembic upgrade head`，backend/worker/beat 经 `depends_on: migrate: service_completed_successfully` 等其成功后才启动——**只此一处迁移、不并发**，无需手动 `alembic upgrade`。
- **环境去重**：compose 用 YAML 锚点 `&backend-env` 让 backend/worker/beat 共享同一份运行时环境；仅本地非密凭证，真实密钥经部署注入、**不入仓库**。
- **依赖**：`httpx` 等运行时依赖在 `pyproject.toml` 主 `dependencies`（非 dev extras）；`tests/test_r8_deployment_ops.py` 有 import 冒烟防回归。

### ⚠️ `docker compose config` 会展开 `.env` 密钥

backend/worker/beat/migrate 经 `env_file: ./backend/.env` 加载环境（本地联调需要，**勿移除**）。`docker compose config` 会把 `env_file` 的值（`WEKNORA_API_KEY` / `LLM_API_KEY` / `WECOM_APP_SECRET` / `ONLYOFFICE_JWT_SECRET` 等）**明文展开**到输出。

- 含真实密钥时，**不要**把 `docker compose config` 完整输出贴进 issue / 完成报告 / 截图 / 聊天。
- 验证 compose 结构时，优先用脱敏方式（只检查存储挂载片段，或临时换占位 `.env`）。
- 安全验证 backend/worker 共享上传存储结构（不展开 `.env`、不打印任何 `*_KEY`/`*_SECRET`/token/连接串）——`STORAGE_ROOT` 与共享卷都写在 `docker-compose.yml`，直接读 compose 文件即可：

  ```powershell
  # 应命中两行（backend + worker）都挂载共享卷
  Select-String -Path docker-compose.yml -Pattern 'upload_storage:/data/uploads'
  # &backend-env 锚点把 STORAGE_ROOT 指向 /data/uploads（backend/worker 共用）
  Select-String -Path docker-compose.yml -Pattern 'STORAGE_ROOT:\s*/data/uploads'
  # 只列服务名 / 卷名（不展开 env_file 值）
  docker compose config --services
  docker compose config --volumes
  ```

### 可观测端点

- `GET /health`：活性（不触依赖）。
- `GET /health/ready`：就绪——DB 连通 +（async 模式）Redis 连通；未就绪 → 503。
- `GET /health/config`：安全配置诊断——只回 enabled/disabled 布尔 + LLM provider 名 + 缺失项名，**绝不**回值/密钥/连接串/URL/token/内部标识。
- `GET /admin/ops/summary`（admin）：版本/环境 + 就绪 + Celery 模式 + 入库计数 + 待发 wecom 通知数 + 未处理审计异常数。
- 请求访问日志（`app.request`）只记 method/path/status/耗时/trace_id——无 body/query/密钥；合规留痕仍以 `audit_events`（值级脱敏）为准。

### 外部集成启用清单（部署注入，勿入仓库）

| 集成 | 关键 env | 启用判定 |
|---|---|---|
| WeKnora | `WEKNORA_BASE_URL` / `WEKNORA_API_KEY` / `WEKNORA_EMBEDDING_MODEL_ID` | base_url + api_key 齐 |
| LLM | `LLM_PROVIDER` / `LLM_API_KEY`（+ `LLM_BASE_URL` / `LLM_MODEL`） | provider + api_key 齐 |
| WeCom | `WECOM_CORP_ID` / `WECOM_AGENT_ID` / `WECOM_APP_SECRET` / `WECOM_REDIRECT_URI` / `WECOM_DRIVE_BASE_URL` / `WECOM_NOTIFY_ENABLED`；扫描目录 `spaceid:<id>;fatherid:<id>` | corp_id + app_secret 齐 |
| ONLYOFFICE | `ONLYOFFICE_ENABLED` / `ONLYOFFICE_DOCUMENT_SERVER_URL` / `ONLYOFFICE_INTERNAL_BASE_URL` / `ONLYOFFICE_JWT_SECRET` | enabled + document_server_url 齐 |
| Celery | `REDIS_URL` / `CELERY_TASK_ALWAYS_EAGER=false` + worker/beat 进程 | eager=false 启用异步 |
| 前端 | vite 代理 → `127.0.0.1:8001` | — |

`.env.example` 是完整字段清单；`/health/config` 的 `missing_config` 列出已开启但缺值的配置名。

### 仍需的真实基建 / 密钥（部署假设）

真实 WeKnora / 外部 LLM / 企微（OAuth + 微盘 + 应用消息）/ ONLYOFFICE Document Server 的可达地址与密钥须由部署环境提供；本仓库不含真实凭证，真实网络路径（`pragma: no cover`）以 fake 测试覆盖。生产应置 cookie `secure=True`（HTTPS）、按需调 beat 周期、按规模切换对象存储（`StorageBackend` 可插拔）。统一密钥管理 / K8s·Helm / 指标后端接入不在本仓库范围（仅暴露 `/health/*` 与 `/admin/ops/summary` 供接入）。

## PBC-02：人员 / 公司角色 / 项目成员关系后端闭环（`/admin/people`）

把 `/admin/people` 从前端静态 demo 收口为真实后端能力，复用既有 `users` / `user_company_roles` / `projects` / `project_members` 表（不新增 demo-only 字段、不物理删除关系）。

- API（`app/api/people.py` + `app/services/people.py`）：`GET /api/v1/admin/people`（列表 + 过滤）、`GET /{user_id}`（详情）、`POST /{user_id}/company-roles`（公司角色 upsert）、`GET/POST/PATCH /{user_id}/project-memberships`（项目成员关系）。
- 权限：读为 admin / boss / 咨询总监；管理项目成员关系为 admin / boss / 咨询总监；公司角色中 `admin` 角色仅 admin 可分配/移除，业务角色 admin/boss/咨询总监可管；不允许停掉最后一个可用 admin；consultant 无权。admin 是系统身份，不因此获得任何业务原文权。
- 安全：响应 / 审计只含安全身份/治理元数据（`wecom_bound: bool`、安全聚合的 `recent_session_at`），绝不含 token / token_hash / OAuth code·state / ip / device_info / wecom_user_id 明文 / 业务原文 / provider 内部标识。写动作写 `config.people_company_role_updated` / `config.people_project_membership_updated` 审计。
- 测试：`tests/test_pbc02_people.py`。

## PBC-03：权限规则配置中心后端闭环（`/admin/permissions`）

把 `/admin/permissions` 从前端静态 demo 收口为真实 `permission_rules` 配置中心 + 真实 Agent Registry 兼容接口。

- 模型 / 迁移：`app/models/permission_rule.py`（表 `permission_rules`，字段 `rule_key`（唯一）/ `rule_group` / `rule_type`（numeric/toggle/fixed_path）/ `display_name` / `value_bool|value_number|value_text` / `default_*` / `unit` / `description` / `editable` / `enabled` / `updated_by`）；迁移 `0018_permission_rules`（PG/SQLite 兼容，**不存任何 secret**）。
- 默认 seed：`app/services/permission_rules.py::ensure_default_rules` 幂等创建 16 条默认规则（按 `rule_key` 去重），覆盖个人流转 / 项目升格 / 访问申请 / 资产生命周期四组。
- API（`app/api/permissions.py`）：`GET /api/v1/admin/permissions/rules`（读：admin / boss / 咨询总监；consultant 403）、`PATCH /api/v1/admin/permissions/rules/{rule_id}`（写：仅 boss / 咨询总监；admin 只读 → 403 `admin_business_permission_denied`；consultant → 403；fixed_path 不可改 → 422；numeric 负值 → 422）。
- 审计：写动作写 `config.permission_rule_updated`（`target_type=permission_rule`），before/after/extra 只含安全配置值（rule_key / 旧新值 / enabled），不含任何 secret / provider 内部标识 / 业务原文。
- **运行时边界**：PBC-03（历史）只落配置中心，当时不让 `DefaultAccessPolicy` 从规则运行时加载，运行时联动留后续任务。**现状（PBC-06 + PBC-11E 已实现）**：`access_grants` / `original_access_requests` 运行时联动已落地——active grant 经 `decide(has_original_grant=…)` 放行原文层，`access_grant_duration_days` 为默认有效期来源；**PBC-11E 已把 L1/L2 原文默认放行开关与超时自动通过接入运行时**（`load_access_policy()` 构建运行时 `DefaultAccessPolicy`、`access_request_timeout_hours` 驱动 L1/L2 超时自动通过，`DEFAULT_POLICY` 仅作规则缺失回退）。仍未规则化运行时的是其余 `permission_rules`（个人流转 / 升格阈值 / 生命周期），仅作治理配置视图。归档阈值（`asset_archive_*`）在本表仅作治理配置视图，R5/R8 生命周期归档扫描的运行时阈值来源仍为 `alert_rules`。
- Agent Registry：`/admin/permissions/agent-whitelist`（PBC-01 既有 provider 中立兼容接口，admin 管理）；PBC-03 不重新实现其后端，响应不含 token_hash / provider 内部标识。
- 前端：`src/pages/AdminPermissionsPage.tsx` 接真实 API（loading/error/empty 三态、admin 只读 vs 顾问无权区分、fixed_path 只读），删除 `initialRules` / `initialAgents` 等本地 mock；不声称所有规则已驱动运行时。
- 测试：`tests/test_pbc03_permission_rules.py`。
