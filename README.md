# 知识资产平台 / Knowledge Asset Platform

MOWAYS（博维咨询）内部的**知识资产与交付治理工作台**。面向咨询顾问、项目经理、辅导老师、合伙人/老板与咨询总监，把项目过程中沉淀的资料、方法论、交付物和案例，按权限沉淀为可检索、可复用、可治理的组织知识资产。

> 这是一个可运行的产品工程，不是演示原型。前端为 React + Vite + TypeScript 单页应用，后端为 FastAPI + PostgreSQL + Redis + Celery；外部系统（WeKnora 向量检索、外部 LLM、企业微信、ONLYOFFICE）经环境变量注入启用，未配置时安全降级、不伪装成功。

---

## 它解决什么问题

咨询公司的知识高度分散在个人电脑、项目群和交付物里，难以复用且容易泄露客户敏感数据。本平台提供：

- **沉淀**：从企业微信微盘扫描与本地上传两条入库通道，自动抽取、命名规范化；入库建议由受信外部 API 处理，对外输出仍按权限与脱敏策略收口。
- **治理**：个人 → 项目 → 公司三级知识库，资料区 / 资产区按状态区分，升格需要真实验证证据与对应角色确认。
- **复用**：基于 WeKnora 的语义检索与问答，结果经集中权限网关裁剪与脱敏。
- **管控**：发现 / 摘要 / 原文三层访问模型，原文访问需申请与授权，全程审计。

## 核心能力

- **工作台**：按当前身份展示我的待办、近期资料和项目入口；通知与任务分别呈现，已读不等于任务完成。
- **知识资产库**：浏览 + 语义检索（WeKnora 召回 + 意图路由 + 权限裁剪 + 脱敏），按公司 / 项目 / 个人范围切换，展示保密级、索引状态与原文层状态。
- **入库 / 资产化确认**：企业微信微盘扫描（自动通道）与本地上传（手动通道）共享「AI 抽取 → 人工校正 → 确认入库」链路；外部 LLM 生成三层摘要与标签建议，未配置 LLM 时回退确定性草稿。入库 / 建库默认使用平台推荐的嵌入 / 重排模型，顾问可在「高级设置」按需切换（前端只用对底座 id 不可逆的 `model_ref` 选择，绝不接触真实模型 id）；平台未配置默认嵌入模型时相关建库/索引操作会受阻并提示补齐配置，不再静默回退环境变量。
- **审核与升格**：项目资料 → 资产、个人 → 项目提交，按角色审核并登记验证证据。
- **原文访问授权**：申请 / 审批 / 拒绝 / 撤销原文访问，审批通过生成有时效的访问授权，运行时叠加放行，过期或撤销立即失效。
- **外部 Agent 接入**：provider 中立的外部 Agent / 工作流网关，当前主接入面为 **WorkBuddy MCP**（`integrations/workbuddy-mcp/`）；Dify 为 legacy 兼容适配器（保留可用，新接入优先使用 WorkBuddy MCP / agent-gateway）。Agent 不拥有独立权限，完全跟随调用人（按 token 绑定的真实用户）权限，经权限网关裁剪与脱敏。
- **运维后台**：索引失败重试 / 重新解析、审计日志、登录风控、告警设置、权限规则配置、人员与项目成员、微盘扫描配置、WeKnora 模型配置（含平台默认模型设置：admin 维护、治理角色只读，业务模型不再写死在 `.env`）。
- **安全**：密码登录（PBKDF2）与企业微信 OAuth；服务端会话 + httpOnly cookie；登录失败锁定 / IP 限流、CSRF 防护、账号安全变更时撤销会话、企业微信身份生命周期同步。
- **预览与通知**：ONLYOFFICE 只读预览（受控取件，不泄露存储地址）；企业微信通知（需开启）。

- **文件解析与恢复**：PDF/图片 OCR、Office 正文抽取、旧版 Office 转换、上传会话恢复和重型解析队列已实现。格式与资源限制见[文件支持说明](docs/deployment/LEGACY_OFFICE_100MB.md)及[OCR 运行手册](docs/operations/OCR_QUEUE_RECOVERY.md)。
- **帮助与手机端**：帮助中心提供按任务组织的使用教程；手机端使用任务导航、条目列表和引用/详情抽屉。

> **当前边界**：已提供管理员会话查询/撤销、人员密码设置与历史正文回填；不等同于用户自助找回密码、MFA、完整的个人多设备管理或历史资产自动全量重索引。结构保持式文件重写、本地 LLM 脱敏和 S3/OSS/MinIO 存储适配也不是当前交付能力。

## 角色模型

| 角色 | 技术 key | 定位 |
|---|---|---|
| 顾问 | `consultant` | 个人知识管理、资料贡献、分享/客户验证候选提交、项目问答 |
| 项目经理 | `project_manager` | 项目知识运营、人员协同、提交审核、资产区确认 |
| 辅导老师 | `coach` | 现场教学、客户陪跑、进度观察；不负责资产区确认 |
| Boss | `boss` | 公司级业务决策、公司知识资产审核 |
| 咨询总监 | `consulting_director` | 公司级知识治理、权限规则、跨项目治理 |
| 管理员 | `admin` | 系统运维身份，不具备业务知识访问权 |

## 知识与访问模型

- 三类知识库（个人 / 项目 / 公司）统一用 `zone = material | asset` 表示资产化状态，确认规则按库不同（个人由所有者本人、项目由项目经理、公司由 Boss / 咨询总监）。
- 三层访问：**发现层**（标题/类型/标签/脱敏简述）、**摘要层**（安全摘要）、**原文层**（原始文件 / 原文 chunk / 客户数据 / 预览）。权限管控集中在原文层。
- 保密级 L1–L5 递增。本人个人库与 active 项目成员权限按所属范围判定；跨项目 L1–L4 仅可发现和查看受控摘要，L5 不可发现。公司 L5 仅总经理 / 咨询总监可发现；纯管理员没有业务知识访问权。L3/L4 对外摘要使用安全变体，原文仍须通过当前权限校验。

## 快速开始（Docker）

前提：安装支持 `up --wait` 的 Docker Compose。首次启动时复制两份示例；已有配置不要覆盖。根 `.env` 用于 Compose 插值，`backend/.env` 用于后端集成配置，Compose 显式 `environment` 的优先级更高。

```powershell
Copy-Item .env.example .env
Copy-Item backend/.env.example backend/.env
# 检查根 .env：本地 APP_ENV=dev；设置 POSTGRES_PASSWORD、REDIS_PASSWORD。
# 示例密码仅供本地开发。外部集成可留空，相关功能会显示不可用或降级。
docker compose build
docker compose up -d --wait # postgres/redis → migrate → backend/worker/ocr_worker/beat → frontend
docker compose exec backend python -m app.seed.dev_seed   # 可选：写入开发种子数据（仅 dev/test）
```

**访问地址**

| 用途 | 地址 |
|---|---|
| 用户入口（前端） | `http://localhost:18080/` |
| 后端调试（仅调试） | `http://localhost:8001` |
| 健康探针 | `http://localhost:8001/health`、`/health/ready`、`/health/config` |

前端 nginx 同源反代后端（`/api/v1`、`/health`、`/admin/ops`），日常使用走 `18080`。本地开发也可 `npm run dev`（Vite，`vite.config.ts` 已把 `/api`、`/admin/ops`、`/health` 代理到 `http://127.0.0.1:8001`）。

**开发账号**：种子数据提供各角色的开发邮箱（如 `boss.c@dev.local`、`consultant.a@dev.local`、`admin.e@dev.local`）。本地/开发环境支持邮箱免密登录；生产必须使用密码或企业微信 OAuth。

## 前端入口

- **工作台** `/`：个人待办、项目入口和近期资料。
- **知识资产库** `/knowledge`：浏览与语义检索。
- **上传资料** `/upload`：上传、核对入库信息和上传记录（含微盘来源任务）。
- **审批中心** `/review`、`/review/completed`、`/original-access`；**我的知识** `/my/knowledge`、**知识维护** `/knowledge-maintenance`。
- **项目空间** `/projects`：成员项目概览、资料、问答和设置；知识库中的“项目库”是资料浏览入口，摘要可见不等于项目成员权限。
- **帮助中心** `/help`、**更新日志** `/release-notes`、**MCP 接入** `/my/workbuddy`（保留兼容路径）。
- **管理后台**：入库管理、微盘扫描、模型配置、审计日志、登录风控、告警设置、权限规则、人员权限（按角色可见）。

## 部署说明

`docker-compose.yml` 提供后端 + Postgres + Redis + Celery worker/ocr_worker/beat + 前端 nginx 的单机编排（编排内凭证仅本地开发用，**绝非生产凭证**）。生产上线需要真实域名、HTTPS/TLS 证书与反向代理、企业微信可信回调域名、外部系统密钥注入、持久卷备份与监控接入等运维动作；这些不在仓库内完成。

仓库内提供可执行的部署手册与安全清单，作为上线前的操作依据：

- 部署 runbook：[`docs/deployment/PRODUCTION_DEPLOYMENT_RUNBOOK.md`](docs/deployment/PRODUCTION_DEPLOYMENT_RUNBOOK.md)
- 安全配置清单（只列项名）：[`docs/deployment/PRODUCTION_SECRET_CHECKLIST.md`](docs/deployment/PRODUCTION_SECRET_CHECKLIST.md)
- 上线 smoke 清单：[`docs/deployment/LIVE_SMOKE_CHECKLIST.md`](docs/deployment/LIVE_SMOKE_CHECKLIST.md)
- 无密钥安全烟测脚本：`python scripts/production_smoke.py --base-url http://<host>:<port> --expect-prod-ready --json`

后端架构、API 模块、认证与运维细节见 [`backend/README.md`](backend/README.md)。

梳理功能或准备跨模块修改时，先看[全模块地图与修改指南](docs/architecture/MODULE_MAP.md)：按业务模块定位页面、接口、状态归属、依赖和针对性验收，再进入各专题文档。

## 安全边界

- **不提交真实密钥**：所有外部系统凭证经部署注入，不入仓库；`backend/.env` 已被 Git 忽略。
- **按输出边界保护数据**：业务摘要、通知、日志与审计不得泄露原文、凭证、存储引用和底座标识。获准原文访问通过受控预览/正文接口执行；登录、CSRF、MCP 配置等专用凭证接口按契约返回必要凭证，不应复制进日志或报告。
- **不展开密钥**：不要运行或粘贴完整 `docker compose config`（它会展开 `env_file` 里的真实密钥）。验证编排结构请用 `docker compose config --services` / `--volumes`，或对 `docker-compose.yml` 做定向检索。

## 代码质量门禁

CI 对每个 PR 检查后端 lint / 类型 / 测试 / 架构 / OpenAPI 契约，前端 lint / 格式 / 单元测试 / 构建 / 接口漂移和浏览器回归，以及 PostgreSQL 迁移、前后端镜像和 MCP 集成。详见 `.github/workflows/ci.yml`。

- 前端结构与接口接入：[维护说明](docs/architecture/FRONTEND_STRUCTURE.md)。
- 接口覆盖：`npm run api:frontend:check`；浏览器全量回归：`npm run test:ui:global-acceptance`。
- 页面使用方法以应用内 `/help` 为入口；仓库文档主要面向开发和部署维护。

本地用 **pre-commit**（一套框架，覆盖前后端；不使用 husky / lint-staged）在提交前自动跑 ruff(check --fix / format) 与 eslint / prettier：

```bash
pip install pre-commit        # 或安装 backend dev 依赖（已含）
pre-commit install            # 安装 git 钩子（一次性）
pre-commit run --all-files    # 手动全量跑
```

格式化命令：后端 `cd backend && ruff format app tests`；前端 `npm run format`（`npm run format:check` 只校验）。

应急跳过钩子（仅紧急修复，不要常态化）：`git commit --no-verify`。

## 技术栈

- 前端：React 18、TypeScript、Vite、React Router；自托管字体（Hanken Grotesk / Fraunces / IBM Plex Mono）与 lucide 图标。
- 后端：FastAPI、SQLAlchemy（async）、Alembic、Celery、PostgreSQL、Redis。
- 外部集成：WeKnora（向量检索/索引）、外部 LLM（内容处理）、企业微信（OAuth / 微盘 / 通知）、ONLYOFFICE（预览）。服务连接经环境配置注入；平台默认模型和 KAP 内容生成连接由模型管理页面维护，敏感配置加密存储，未配置时按实际能力降级。
