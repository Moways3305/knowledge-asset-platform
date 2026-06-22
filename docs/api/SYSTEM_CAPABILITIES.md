# 系统能力清单（System Capabilities）

> 本文描述 **AI 知识资产平台当前实际具备的能力**——以代码与已注册路由为准，不是 PRD、
> 不是蓝图、不承诺未来。机器可校验的接口契约见同目录 [`openapi.json`](./openapi.json)
> （由 `scripts/export_openapi.py` 从 FastAPI 应用导出，CI 检测漂移）。
>
> 安全说明：本文只描述「能做什么 / 谁能做」，**不**包含内部安全实现细节（密钥项名、
> hash / 签名算法参数、server-only 内部标识的格式与映射方式）。这些按设计不外泄。

---

## 1. 业务定位

面向咨询公司的知识资产沉淀与复用平台：把顾问/项目的过程材料，经**资料 → 资产**的
确认治理，沉淀为可检索、可复用、可审计的知识资产；并通过 **provider 中立的外部
Agent / 工作流网关**，让 AI 问答与检索在**权限网关**约束下使用这些知识。

三类知识库，统一用 `zone = material | asset` 表示资产化状态，但**确认规则不同**：

| 知识库 | material（资料） | asset（资产） | material → asset 确认人 |
|---|---|---|---|
| 个人知识库 | 个人资料/草稿/摘录 | 本人整理确认的个人知识资产（仅本人可见） | 知识所有者**本人** |
| 项目知识库 | 项目过程材料 | 经验证的可复用知识资产 | **项目经理**（需真实分享/客户验证证据） |
| 公司知识库 | 公司级资料/候选/待治理 | 公司级知识资产 | **Boss / 咨询总监** |

- 个人知识库可由 Boss / 咨询总监 / 顾问拥有；仅本人使用，不参与他人检索；进项目须本人主动提交。
- 资料区与资产区**不是两个物理知识库**，是同一库内的 `zone` 标签。

---

## 2. 角色模型

| 角色 | 技术 key | 定位 |
|---|---|---|
| 顾问 | `consultant` | 个人知识管理、资料贡献、提交候选、项目问答 |
| 项目经理 | `project_manager` | 项目知识运营、个人到项目提交审核、项目资产区确认 |
| 辅导老师 | `coach` | 现场教学/陪跑/进度观察；**不**做资产区确认 |
| Boss | `boss` | 公司级决策、公司知识资产审核 |
| 咨询总监 | `consulting_director` | 公司级知识治理、权限规则、跨项目治理 |

`admin` 是系统管理身份，**不**作为业务个人知识库主体，也**不**因系统身份自动获得业务原文授权或 L5 发现权。

---

## 3. 核心流程

1. **入库（Ingest）**：上传文件（Path B）或企微微盘扫描（Path A）→ 外部 LLM 内容处理
   （未配置则降级为确定性草稿，不伪装成功）→ 待确认任务 → 确认人确认入库。
2. **索引与检索**：入库确认后经 WeKnora 建立索引（未配置则跳过、降级）→ 两阶段检索
   （发现/摘要层召回 + 原文层受权限网关约束）。
3. **问答（QA）**：项目问答经外部 Agent 网关，**完全跟随调用人权限**取上下文。
4. **资产化确认**：material → asset 按上表规则由对应确认人完成（项目资产需验证证据）。
5. **公司库升格**：项目资产经跨项目复用信号**推荐**为公司候选 → Boss / 咨询总监审核。
6. **生命周期**：知识可归档 / 重启用（archive / reenable，带申请—确认）。
7. **原文访问**：跨项目 / 公司 L3/L4 原文经申请—审批生成授权后方可访问；全程审计。

---

## 4. API 路由概览

后端注册 **21 个业务 router**（共约 95 个 endpoint）。除健康探针与少数集成回调外，
默认需认证会话；写操作在 cookie 会话下受 CSRF 保护；管理类路由额外要求对应治理角色。

> 认证标注：🔓 无需会话；🔐 需登录会话；🛡️ 需登录 + 治理/管理角色。
> 写操作（POST/PUT/PATCH/DELETE）在会话下均需 `X-CSRF-Token`（先取 `GET /api/v1/auth/csrf`）。

### 4.1 健康与运维
- 🔓 `GET /health`、`/health/ready`、`/health/config` — 活性 / 就绪 / 安全配置诊断（只回布尔/项名/provider 名，无值）。
- 🛡️ `GET /admin/ops/summary`、`/admin/ops/indexing`(+`/jobs`,`/reparse`,`/retry`) — 运维概览与索引运维。
- 🛡️ `GET/POST /admin/ops/auth-security`(+`/unlock`) — 登录风控查看与解锁。
- 🛡️ `GET/POST /admin/ops/sessions/users/{user_id}`(+`/revoke`) — 会话查看与撤销。
- 🛡️ `POST /admin/ops/wecom-identity/reconcile` — 企微身份生命周期对账。

### 4.2 身份与会话（auth）
- 🔓 `POST /api/v1/auth/login`、`GET /api/v1/auth/csrf`、`GET /api/v1/auth/wecom/start`、`GET /api/v1/auth/wecom/callback`。
- 🔐 `GET /api/v1/auth/me`、`POST /api/v1/auth/logout`。
- 密码登录带失败风控（锁定/限流）；企微 OAuth 走 Path A 身份；会话为 httpOnly cookie。

### 4.3 知识读 / 检索 / 生命周期 / 预览（knowledge, search, lifecycle, preview）
- 🔐 `GET /api/v1/knowledge`、`GET /api/v1/knowledge/{asset_id}`、`GET /api/v1/knowledge/ops-insights`。
- 🔐 `POST /api/v1/knowledge/search`、`POST /api/v1/knowledge/{asset_id}/preview`。
- 🔐 `POST /api/v1/knowledge/{asset_id}/lifecycle/{archive|reenable}-{request|confirm}`、`GET .../lifecycle/events`。
- 🔐 `POST /api/v1/knowledge/{asset_id}/original-access/request`、`/retry-index`、`/delete`。
- 🔐 `GET /api/v1/preview/{credential_id}`(+`/file`) — ONLYOFFICE 受控只读预览（凭据制，取件 URL server-only）。

### 4.4 个人知识库（my_knowledge, personal_kb）
- 🔐 `GET /api/v1/my/knowledge`、`GET/POST/PUT /api/v1/my/knowledge-base` — 个人库显式创建/改名/状态。
- 🔐 `POST /api/v1/my/knowledge/{asset_id}/{confirm-asset|submit-to-project|validation-evidence}`。
- 边界：他人个人知识**不可发现、不可摘要**；进项目须本人主动提交。

### 4.5 入库与审核（ingest, review）
- 🔐 `POST /api/v1/ingest/upload`、`GET /api/v1/ingest/pending`、`GET .../{task_id}/ai-result`、`POST .../{task_id}/{confirm|refresh-parse}`。
- 🛡️ `GET /api/v1/reviews`、`GET /api/v1/reviews/{review_id}`、`POST .../{approve|reject}` — 升格/提交审核。

### 4.6 项目（projects）
- 🔐 `GET/POST /api/v1/projects`、`GET/PATCH /api/v1/projects/{project_id}/settings`。
- 🔐 `POST /api/v1/projects/{project_id}/qa` — 项目问答（经 Agent 网关 + 权限）。
- 🛡️ `GET/PATCH /api/v1/projects/{project_id}/members/...` — 成员协同。
- 🛡️ `POST /api/v1/projects/{project_id}/knowledge/{asset_id}/{confirm-asset|evidence}` — 项目资产确认（项目经理）。

### 4.7 原文访问授权（original_access）
- 🛡️ `GET /api/v1/original-access/requests`、`POST .../{request_id}/{approve|reject}`、`POST .../grants/{grant_id}/revoke`。
- 授权由审批通过后生成；admin 不因系统身份获得业务原文授权权。

### 4.8 外部 Agent 网关：WorkBuddy MCP（主） / Dify（legacy）
- 🔐 `GET /api/v1/agent-calls/{call_id}`(+`/decision-items`) — Agent 调用记录与候选项。
- 🔐 `POST /api/v1/agent-gateway/tools/knowledge-search`、`GET /api/v1/agent-gateway/projects` — **provider 中立外部 Agent 网关**（WorkBuddy MCP 经此接入）。Bearer token 绑定唯一 KAP 用户，caller 仅由后端从绑定解析（不读客户端自报 user id）；channel=agent，不取原文。
- 🔐 `POST /api/v1/dify/external-knowledge/retrieval`、`POST /api/v1/dify/tools/knowledge-search` — **Dify 兼容适配器（legacy）**，保留可用、不强删；新接入用 agent-gateway。
- 核心是 **provider 中立网关**；Agent **不**拥有独立权限，完全跟随调用人。

### 4.9 治理与管理后台（audit, alert, people, permissions, wecom_scan, weknora_admin）
- 🛡️ 审计：`GET /api/v1/admin/audit`(+`/trace/{trace_id}`,`/{event_id}/mark-processed`)。
- 🛡️ 告警：`GET /api/v1/admin/alerts/{rules|notifications}`、`PATCH .../rules/{rule_id}`。
- 🛡️ 人员：`/api/v1/admin/people/...`（公司角色、项目成员、状态、密码重置）。
- 🛡️ 权限规则：`/api/v1/admin/permissions/{rules|agent-whitelist}`。
- 🛡️ 微盘扫描：`/api/v1/admin/wecom-scan/...`（配置、扫描、目录/空间、归属选项）。
- 🛡️ WeKnora 管理：`/api/v1/admin/weknora/{models|kb-configs|providers}`（模型经不可逆 `model_ref` 对前端暴露，内部 model id 不外泄）。

---

## 5. 权限边界摘要

三层访问模型（敏感度递增 L1<L2<L3<L4<L5）：

- **发现层**：标题、类型、标签、scope、zone、阶段、脱敏简述。
- **摘要层**：safe/redacted summary，不含客户敏感数据。
- **原文层**：原始文件、原文 chunk、客户数据、预览、未脱敏上下文——**权限控制重点**。

关键规则：
- 无项目身份用户**也可**查看公司知识库中允许发现的知识摘要（无项目身份 ≠ 只能看个人知识）。
- 项目组人员对**所在项目**知识库拥有摘要与原文（含客户数据原文）权限，行为受审计、无需额外原文申请。
- 跨项目 / 公司知识库的 L3/L4 原文需原文审核 / 授权。
- L5 仅 Boss / 咨询总监可发现；admin **不**自动发现 L5。
- L3/L4 摘要必须是脱敏摘要，不得含客户敏感数据。L2 是内部一般资料，不强制脱敏，不比 L3/L4 更严格。
- `preview_type` 由保密等级 + 访问场景 + 调用人授权**共同**决定，不固定对应某一保密级别。
- Agent 跟随调用人权限：调用人能看摘要则 Agent 可用同范围摘要；调用人有原文授权则 Agent 同步具备该范围原文能力；调用人无权发现 L5，Agent 亦不能。Agent 只能推荐候选，不自动完成审核 / 验证 / 资产确认 / 公司库升格。

---

## 6. 外部集成点

均为 **env 注入启用、未配置时 fail-closed 安全降级**（不伪装成功），密钥经部署注入、不入仓库：

| 集成 | 作用 | 未配置时 |
|---|---|---|
| **WeKnora** | 知识底座 / 嵌入与索引 / 两阶段检索 | 跳过索引，检索降级 |
| **外部 LLM** | 入库内容处理（摘要/抽取/改写） | 降级为确定性草稿，上传不失败 |
| **企业微信（WeCom）** | OAuth 身份、微盘扫描（Path A）、治理通知 | OAuth/扫描未启用，通知仅本地 in_app |
| **ONLYOFFICE** | 受控只读原文预览 | 预览安全降级，不泄露原文 URL |
| **对象存储 / 向量库** | 受控上传字节存储、向量检索 | 走本地共享卷 / 降级 |

provider 内部标识（dataset/workflow/kb/model id、bucket、api_key 等）为 **server-only，绝不外泄前端**。

---

## 7. 安全红线（不得出现在 API 响应 / 前端 / 日志 / 审计）

- 任何密钥 / 凭证：api_key、app_secret、jwt_secret、各类签名/HMAC 密钥。
- server-only 内部标识：WeKnora kb/doc/model id、Dify dataset/workflow/app id、对象存储 bucket / 受控存储引用、内部文件引用。
- 凭证派生物：登录标识 / IP 的不可逆 hash、密码 hash、会话/CSRF/OAuth state token。
- 客户敏感数据：未脱敏原文 / chunk、原始业务文件名、原始 IP、原文下载 URL。
- L3/L4 摘要中的客户敏感数据；他人个人知识的发现 / 摘要。

> 契约层防回归：`scripts/export_openapi.py` 在导出时扫描**响应可达** schema 的字段名与
> 示例值，命中上述红线标识即报错并阻断（详见脚本头注释）。
