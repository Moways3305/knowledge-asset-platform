# 知识资产平台 / Knowledge Asset Platform

MOWAYS（博维咨询）内部的**知识资产与交付治理工作台**。面向咨询顾问、项目经理、辅导老师、合伙人/老板与咨询总监，把项目过程中沉淀的资料、方法论、交付物和案例，按权限沉淀为可检索、可复用、可治理的组织知识资产。

> 这是一个可运行的产品工程，不是演示原型。前端为 React + Vite + TypeScript 单页应用，后端为 FastAPI + PostgreSQL + Redis + Celery；外部系统（WeKnora 向量检索、外部 LLM、企业微信、ONLYOFFICE）经环境变量注入启用，未配置时安全降级、不伪装成功。

---

## 它解决什么问题

咨询公司的知识高度分散在个人电脑、项目群和交付物里，难以复用且容易泄露客户敏感数据。本平台提供：

- **沉淀**：从企业微信微盘扫描与本地上传两条入库通道，自动抽取、命名规范化、入库前实体脱敏。
- **治理**：个人 → 项目 → 公司三级知识库，资料区 / 资产区按状态区分，升格需要真实验证证据与对应角色确认。
- **复用**：基于 WeKnora 的语义检索与问答，结果经集中权限网关裁剪与脱敏。
- **管控**：发现 / 摘要 / 原文三层访问模型，原文访问需申请与授权，全程审计。

## 核心能力

- **今日工作台**：登录后首页是个人总览——我的待办（待确认入库、待审核、原文申请、索引失败等）、今日运营状态、快捷入口与项目范围，按角色裁剪。
- **知识资产库**：浏览 + 语义检索（WeKnora 召回 + 意图路由 + 权限裁剪 + 脱敏），按公司 / 项目 / 个人范围切换，展示保密级、索引状态与原文层状态。
- **入库 / 资产化确认**：企业微信微盘扫描（自动通道）与本地上传（手动通道）共享「AI 抽取 → 人工校正 → 确认入库」链路；外部 LLM 生成三层摘要与标签建议，未配置 LLM 时回退确定性草稿。
- **审核与升格**：项目资料 → 资产、个人 → 项目提交，按角色审核并登记验证证据。
- **原文访问授权**：申请 / 审批 / 拒绝 / 撤销原文访问，审批通过生成有时效的访问授权，运行时叠加放行，过期或撤销立即失效。
- **运维后台**：索引失败重试 / 重新解析、审计日志、登录风控、告警设置、权限规则配置、人员与项目成员、微盘扫描配置、WeKnora 模型配置。
- **安全**：密码登录（PBKDF2）与企业微信 OAuth；服务端会话 + httpOnly cookie；登录失败锁定 / IP 限流、CSRF 防护、账号安全变更时撤销会话、企业微信身份生命周期同步。
- **预览与通知**：ONLYOFFICE 只读预览（受控取件，不泄露存储地址）；企业微信通知（需开启）。

> **当前不包含 / 计划增强**：OCR 扫描件识别、结构保持式文件重写、基于本地 LLM 的脱敏、历史资产全量重索引、MFA / 找回密码 / 密码轮换 / 完整多设备会话管理。这些尚未实现，界面会按真实边界展示，不放可点击的假按钮。

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
- 保密级 L1–L5 递增；L3/L4 对外摘要必须脱敏；L5 仅 Boss / 咨询总监可发现，管理员不因系统身份获得业务可见性。

## 快速开始（Docker）

前提：安装 Docker Desktop，准备 `backend/.env`（从 `backend/.env.example` 复制；本地可不填外部密钥，相关集成会安全降级）。

```powershell
docker compose build
docker compose up -d      # postgres/redis 就绪 → migrate 自动迁移 → backend/worker/beat → frontend
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

- **今日工作台** `/`：个人总览与待办。
- **知识资产库** `/knowledge`：浏览与语义检索。
- **资产化确认** `/upload`：入库确认（微盘 / 上传两通道）。
- **升级审核** `/review`、**原文访问** `/original-access`、**个人知识** `/my/knowledge`、**项目看板/设置** `/project/:id/...`。
- **管理后台**：入库管理、微盘扫描、模型配置、审计日志、登录风控、告警设置、权限规则、人员权限（按角色可见）。

## 部署说明

`docker-compose.yml` 提供后端 + Postgres + Redis + Celery worker/beat + 前端 nginx 的单机编排（编排内凭证仅本地开发用，**绝非生产凭证**）。生产上线需要真实域名、HTTPS/TLS 证书与反向代理、企业微信可信回调域名、外部系统密钥注入、对象存储与监控接入等运维动作；这些不在仓库内完成。

仓库内提供可执行的部署手册与安全清单，作为上线前的操作依据：

- 部署 runbook：[`docs/deployment/PRODUCTION_DEPLOYMENT_RUNBOOK.md`](docs/deployment/PRODUCTION_DEPLOYMENT_RUNBOOK.md)
- 安全配置清单（只列项名）：[`docs/deployment/PRODUCTION_SECRET_CHECKLIST.md`](docs/deployment/PRODUCTION_SECRET_CHECKLIST.md)
- 上线 smoke 清单：[`docs/deployment/LIVE_SMOKE_CHECKLIST.md`](docs/deployment/LIVE_SMOKE_CHECKLIST.md)
- 无密钥安全烟测脚本：`python scripts/production_smoke.py --base-url http://<host>:<port> --expect-prod-ready --json`

后端架构、API 模块、认证与运维细节见 [`backend/README.md`](backend/README.md)。

## 安全边界

- **不提交真实密钥**：所有外部系统凭证经部署注入，不入仓库；`backend/.env` 已被 Git 忽略。
- **不输出内部标识**：API、前端与审计绝不返回 storage 引用、对象存储 URL、WeKnora / 企业微信内部 id、模型真实 id、完整 token / cookie / api key 或业务原文。
- **不展开密钥**：不要运行或粘贴完整 `docker compose config`（它会展开 `env_file` 里的真实密钥）。验证编排结构请用 `docker compose config --services` / `--volumes`，或对 `docker-compose.yml` 做定向检索。

## 代码质量门禁

CI 对每个 PR 强制：后端 `ruff check` + `ruff format --check` + `mypy` + `pytest`；前端 `eslint` + `prettier --check` + `vitest` + `build`。

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
- 外部集成：WeKnora（向量检索/索引）、外部 LLM（内容处理）、企业微信（OAuth / 微盘 / 通知）、ONLYOFFICE（预览），均经环境变量启用、未配置时 fail-closed 降级。
