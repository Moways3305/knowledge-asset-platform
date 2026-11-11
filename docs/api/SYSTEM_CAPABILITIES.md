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
| 公司知识库 | 公司级资料/候选/待治理 | 公司级知识资产 | **总经理 / 咨询总监** |

- 个人知识库可由总经理 / 咨询总监 / 顾问拥有；仅本人使用，不参与他人检索；进项目须本人主动提交且本人须为目标项目 active 成员。
- 资料区与资产区**不是两个物理知识库**，是同一库内的 `zone` 标签。

---

## 2. 角色模型

| 角色 | 技术 key | 定位 |
|---|---|---|
| 顾问 | `consultant` | 个人知识管理、资料贡献、提交候选、项目问答 |
| 项目经理 | `project_manager` | 项目知识运营、个人到项目提交审核、项目资产区确认 |
| 辅导老师 | `coach` | 现场教学/陪跑/进度观察；**不**做资产区确认 |
| 总经理 | `boss` | 公司级决策、公司知识资产审核 |
| 咨询总监 | `consulting_director` | 公司级知识治理、权限规则、跨项目治理 |

公司角色与项目角色分别存储、分别判定；公司职务不自动形成任何项目成员关系。`admin` 是系统管理身份，**不**作为业务个人知识库主体，也**不**因系统身份自动获得业务知识、审批或成员管理权。

---

## 3. 核心流程

1. **入库（Ingest）**：上传文件（Path B）→ 外部 LLM 内容处理
   （未配置则降级为确定性草稿，不伪装成功）→ 待确认任务 → 确认人确认入库。
2. **索引与检索**：入库确认后经 WeKnora 建立索引（未配置则跳过、降级）→ 两阶段检索
   （发现/摘要层召回 + 原文层受权限网关约束）。
3. **问答（QA）**：网页项目问答使用第一方会话接口；外部 MCP 通过 Agent 网关接入。两者均按当前调用人权限取上下文，摘要可见不能代替项目成员问答权限。
4. **资产化确认**：material → asset 按上表规则由对应确认人完成（项目资产需验证证据）。
5. **公司库升格**：项目经理发起项目资产升格 → 一名总经理与一名咨询总监分别确认；任一方拒绝或撤回均不升格，任一角色缺失则保持待确认。
6. **生命周期**：知识可归档 / 重启用（archive / reenable，带申请—确认）。
7. **原文访问**：跨项目项目知识 L1-L4、公司知识 L1–L4 的原文经申请—审批生成逐资产授权后方可访问；全程审计。跨项目 L5 不可发现，授权也不得放大其可见性。

---

## 4. API 路由概览

本节按业务概括路由，并非完整接口列表；完整方法、路径和 schema 以 `openapi.json` 为准，前端接入情况见 [FRONTEND_API_COVERAGE.md](./FRONTEND_API_COVERAGE.md)。除健康探针与少数集成回调外，
默认需认证会话；写操作在 cookie 会话下受 CSRF 保护；管理类路由额外要求对应治理角色。

> 认证标注：🔓 无需会话；🔐 需登录会话；🛡️ 需登录 + 治理/管理角色。
> 写操作（POST/PUT/PATCH/DELETE）在会话下均需 `X-CSRF-Token`（先取 `GET /api/v1/auth/csrf`）。

### 4.1 健康与运维
- 🔓 `GET /health`、`/health/ready`、`/health/config`、`/health/release` — 活性 / 就绪 / 安全配置诊断（只回布尔/项名/provider 名，无值）。
- 🛡️ `GET /admin/ops/summary`、`/admin/ops/indexing`(+`/jobs`,`/reparse`,`/retry`) — 运维概览与索引运维。
- 🛡️ `GET /admin/ops/auth-security`、`POST /admin/ops/auth-security/unlock` — 登录风控查看与解锁。
- 🛡️ `GET /admin/ops/sessions/users/{user_id}`、`POST /admin/ops/sessions/users/{user_id}/revoke` — 会话查看与撤销。
- 🛡️ `POST /admin/ops/wecom-identity/reconcile` — 企微身份生命周期对账。

### 4.2 身份与会话（auth）
- 🔓 `POST /api/v1/auth/login`、`GET /api/v1/auth/csrf`、`GET /api/v1/auth/wecom/start`、`GET /api/v1/auth/wecom/callback`。
- 🔐 `GET /api/v1/auth/me`、`POST /api/v1/auth/logout`。
- 密码登录带失败风控（锁定/限流）；企微 OAuth 解析企业成员身份；会话为 httpOnly cookie。

### 4.3 知识读 / 检索 / 生命周期 / 预览（knowledge, search, lifecycle, preview）
- 🔐 `GET /api/v1/workbench/overview` — 第一方浏览器会话工作台聚合；待办、运营摘要、active 成员项目和近期知识动态分别报告可用、空、无权或失败状态。该路由不使用 Agent Gateway，项目与知识字段均按调用人权限裁剪。
- 🔐 `GET /api/v1/knowledge`、`GET /api/v1/knowledge/{asset_id}`、`GET /api/v1/knowledge/ops-insights`。
  - 列表查询先在数据库层应用调用人的发现权限，再执行关键词、scope、项目、资料/资产区、资产类型、状态、保密等级和创建/更新时间筛选；`total` 仅统计有权发现的资产。
  - 支持白名单字段稳定排序及 `page/page_size` 分页，响应包含 `total/page/page_size/has_next`。旧客户端不传分页参数时使用第 1 页、每页 50 条的安全默认值，不再返回无限列表。
  - 关键词只匹配资产标题和标签，不转发给 WeKnora、不写入日志；L3/L4 列表摘要仅投影 safe/redacted 变体。`include_archived` 为旧参数兼容位，不会绕过既有归档资产不可发现规则。
- 🔐 `POST /api/v1/knowledge/search`、`POST /api/v1/knowledge/{asset_id}/preview`。
- 🔐 `POST /api/v1/knowledge/{asset_id}/lifecycle/{archive|reenable}-{request|confirm}`、`GET .../lifecycle/events`。
- 🔐 `POST /api/v1/knowledge/{asset_id}/original-access/request`、`/retry-index`、`/delete`。
- 🔐 `GET /api/v1/preview/{credential_id}`(+`/file`) — ONLYOFFICE 受控只读预览（凭据制，取件 URL server-only）。

### 4.4 个人知识库（my_knowledge, personal_kb）
- 🔐 `GET /api/v1/my/knowledge` — owner-only 分页读模型；支持 `page/page_size`、标题与安全标签关键词、资料类型、个人状态以及创建/更新时间或标题排序。响应包含安全资料项、分页信息和同一 owner 数据集计算的汇总，不返回项目/审核/提交 UUID、原文、存储引用或底座标识。
- 🔐 `PATCH /api/v1/my/knowledge/{asset_id}` — owner-only 安全元数据修改，仅允许标题、资料类型和标签；待项目审批或已进入项目资料区时由后端拒绝修改。
- 🔐 `GET/POST/PUT /api/v1/my/knowledge-base` — 个人库显式创建/改名/状态。
- 🔐 `POST /api/v1/my/knowledge/{asset_id}/{confirm-asset|submit-to-project|validation-evidence}`。
- 个人状态稳定为：待本人确认、可提交项目、待项目经理审批、已进入项目、项目未通过；候选证据仅作为安全汇总提示，不等同于已验证或已采纳。项目审批结果会同步个人提交状态，批准后生成可发现的项目资料副本。只要任一有效项目副本仍存在，“已进入项目”就具有最高优先级，不会被后续其他项目的待审或驳回结果解锁。
- 列表总数、状态筛选与汇总在数据库内计算，资料查询使用稳定排序及 `LIMIT/OFFSET`，服务层只加载和投影当前页资产。
- 边界：他人个人知识**不可发现、不可摘要**；进项目须本人主动提交。待审批或已进入项目的个人资料不可直接编辑或删除，保护规则由后端写接口再次强制执行。

### 4.5 入库与审核（ingest, review）
- 🔐 `POST /api/v1/ingest/upload`、`GET /api/v1/ingest/pending`、`GET .../{task_id}/ai-result`、`POST .../{task_id}/{confirm|refresh-parse}`。
- 🔐 `GET /api/v1/ingest/{task_id}/status`、`POST .../{task_id}/retry` — 第一方单任务进度与安全恢复契约；区分上传、抽取、内容生成、人工确认、审核、索引及完成/降级/失败阶段，只返回白名单错误码、修复建议和安全动作键。无权任务与不存在任务统一不可枚举。
- 🛡️ `GET /api/v1/reviews`、`GET /api/v1/reviews/{review_id}`、`POST .../{approve|reject|withdraw}` — 升格/提交审核。
- 🔐 `POST /api/v1/projects/{project_id}/knowledge/{asset_id}/upgrade-company` — 仅项目经理发起公司资产升格双确认。

### 4.6 项目（projects）
- 🔐 `GET/POST /api/v1/projects`、`GET/PATCH /api/v1/projects/{project_id}/settings`。
- 🔐 `POST /api/v1/projects/{project_id}/qa` — 第一方项目问答，要求有效项目成员身份并执行知识权限裁剪。
- 🛡️ `GET/POST/PATCH /api/v1/projects/{project_id}/members/...` — 总经理/咨询总监任命项目经理，项目经理管理本项目辅导老师与顾问。
- 🛡️ `POST /api/v1/projects/{project_id}/knowledge/{asset_id}/{confirm-asset|evidence}` — 项目资产确认（项目经理）。

### 4.7 原文访问授权（original_access）
- 🛡️ `GET /api/v1/original-access/requests`、`POST .../{request_id}/{approve|reject}`、`POST .../grants/{grant_id}/revoke`。
- 授权由审批通过后生成；admin 不因系统身份获得业务原文授权权。

### 4.8 外部 Agent 网关：WorkBuddy MCP（主） / Dify（legacy）
- 🔐 `POST /mcp` — 标准 Streamable HTTP MCP 主入口，支持 `initialize`、`tools/list`、`tools/call`。支持绑定当前业务用户的自助 Bearer，以及可选的 OAuth 授权码 + PKCE；匿名只能读取协议授权发现元信息，不能查询知识或发现业务工具。生产使用 HTTPS，并有 Origin、请求大小、限流、并发和超时保护。见 [MCP OAuth](./mcp-oauth.md)。
- 🔐 `GET /api/v1/auth/workbuddy-connectors`、`GET .../{platform}/{architecture}/download` — 在职业务用户获取共享 Windows/macOS 连接器的版本、SHA-256、发布渠道与受鉴权安装包；安装包不含个人 token。正式版维持签名/公证链，未签名企业内部版仅在服务器默认关闭的管理员开关显式开启时分发。
- 🔐 `GET /api/v1/auth/workbuddy-token`、`POST .../regenerate`、`DELETE ...` — 当前业务用户查看有效期与安全连接状态、生成一次性远程配置、撤销或轮换。服务端只存摘要；最近连接时间只由成功调用更新。本地 Connector 作为受管设备兼容模式保留。
- 🔐 `GET /api/v1/agent-calls/{call_id}`(+`/decision-items`) — Agent 调用记录与候选项。
- 🔐 `POST /api/v1/agent-gateway/tools/knowledge-search`、`GET /api/v1/agent-gateway/projects` — **provider 中立外部 Agent 网关**（WorkBuddy MCP 经此接入）。Bearer token 绑定唯一 KAP 用户，caller 仅由后端从绑定解析（不读客户端自报 user id）。
- 🔐 WorkBuddy 只读知识应用工具（全部经同一 `require_bound_caller`，不提供文件、下载或预览 URL）：
  - `GET /api/v1/agent-gateway/knowledge/personal`、`GET /knowledge` — 按标签、状态、时间、scope 和 offset/limit 列出绑定用户实时可见知识。
  - `GET /api/v1/agent-gateway/knowledge/{asset_id}` — 安全详情、摘要、标签与可用访问层。
  - `GET /api/v1/agent-gateway/knowledge/{asset_id}/content` — 每次实时执行 original 权限判断，从当前版本关联的受控源文件集中抽取文本；`max_chars` 上限 8000。响应通过有限 `content_status` 区分可读、真实空文本、源缺失、格式不支持、抽取失败及解析待处理/失败，不以空字符串冒充读取成功。
  - `GET /api/v1/agent-gateway/knowledge/tags` — 仅从调用人可见资产聚合标签。
  - `GET /api/v1/agent-gateway/todos` — 我的待办聚合（待我审核 / 我的原文申请 / 待我审批 / 待确认入库）。
  - `GET /api/v1/agent-gateway/knowledge/recent` — 我最近可见的知识资产（安全卡片）。
  - `GET /api/v1/agent-gateway/knowledge/{asset_id}/summary` — 单资产安全摘要（不可发现 → 404，不泄露存在性）。
  - `GET /api/v1/agent-gateway/projects/{project_id}/knowledge` — 项目内我可见的知识（先校验项目权限；无权项目与不存在项目统一 404，不可枚举存在性）。
  - `GET /api/v1/agent-gateway/projects/{project_id}/brief` — 项目安全概览（不含客户名 / 成员名单；无权与不存在统一 404）。
  - `GET /api/v1/agent-gateway/reviews/pending` — 我可处理 / 可见的待审核事项。
  - `GET /api/v1/agent-gateway/original-access/requests?box=mine|inbox` — 原文访问申请（只读）。
  - 仅服务器标记为 `is_self_service` 的自助 WorkBuddy 规则完全跟随绑定用户的实时 `decide()` 权限，不叠加 L2/A2 ceiling；该来源标记不在管理员 CRUD schema 中。管理员创建的 WorkBuddy 规则及其他 provider 仍保留 registry ceiling。响应为安全白名单字段，绝不含文件名 / storage·source ref / 下载·预览 URL / WeKnora id / provider 内部标识 / token。
- 🔐 **受控操作**：`/api/v1/agent-gateway/operations/*` 提供本人上传会话、入库预览与确认、审批决定等操作。仅显式启用 `qa_operations` 的自助凭证或 OAuth 授权可用；每次仍检查实时业务权限、用户明确同意声明和版本条件。旧只读凭证及受限注册凭证不因此获得写权限。文件字节通过 multipart 上传，不塞入 `/mcp` JSON。完整流程见 [MCP 操作接口](../mcp-operations.md)。
- 🔐 `POST /api/v1/dify/external-knowledge/retrieval`、`POST /api/v1/dify/tools/knowledge-search` — **Dify 兼容适配器（legacy）**，保留可用、不强删；新接入用 agent-gateway。
- 核心是 **provider 中立网关**；Agent **不**拥有独立权限，完全跟随调用人。

### 4.9 治理与管理后台（audit, alert, people, permissions, weknora_admin）
- 🛡️ 审计：`GET /api/v1/admin/audit`(+`/trace/{trace_id}`,`/{event_id}/mark-processed`)。
- 🛡️ 告警：`GET /api/v1/admin/alerts/{rules|notifications}`、`PATCH .../rules/{rule_id}`。
- 🛡️ 人员：`/api/v1/admin/people/...` 仅总经理 / 咨询总监可读。总经理可管理总经理 / 咨询总监 / 顾问；咨询总监可管理咨询总监 / 顾问，但不可修改总经理。总经理 / 咨询总监任命或撤销项目经理；项目经理独立管理本项目任意 active 用户的辅导老师与顾问关系。技术 `admin` 角色不提供浏览器维护路径；admin 仅保留审计与必要系统运行视图。
- 🛡️ 公司知识库：`GET|POST /api/v1/company/knowledge-base` 仅总经理 / 咨询总监可用；显式创建复用受控 WeKnora 适配层且幂等，响应只含安全名称、状态、创建时间与可用性。非 `active` 公司库不能用于公司范围入库。
- 🛡️ 权限规则：`/api/v1/admin/permissions/{rules|agent-whitelist}`。
- 🛡️ WeKnora 管理：`/api/v1/admin/weknora/{models|kb-configs|providers}`（模型经不可逆 `model_ref` 对前端暴露，内部 model id 不外泄）。
- 🛡️ 平台默认模型（PBC-38）：`GET|PUT /api/v1/admin/weknora/default-models`（读 admin / 治理角色，写仅 admin；只用 `model_ref`）。建库 / 入库选模型优先级：请求显式 `model_ref` > 平台默认（DB `weknora_default_models`）> fail-closed，不再用 `.env` 的 `WEKNORA_*_MODEL_ID` 兜底；默认模型变更不会自动迁移既有 KB；当前实现允许显式指定不同 embedding 模型时切换绑定，存量文档须随后重新解析以重新向量化，不能把切换配置当作重索引完成。
- 🛡️ KAP 内容生成模型（PBC-46）：`/api/v1/admin/generation/models` 支持管理员新增、编辑、启停、删除与安全连接测试，`PUT /api/v1/admin/generation/default-model` 保存平台默认；API 地址与 API key 使用 Fernet 密文落库，所有响应和审计只暴露安全 `model_ref` 与展示字段。业务侧 `GET /api/v1/generation/model-options` 只读安全选项。
- 🛡️ 外部 LLM 与 WeKnora 拆分（PBC-63）：`/api/v1/admin/model-connections` 是 KAP 外部 OpenAI-compatible Chat LLM 的兼容管理面，只读写加密的 KAP 连接，并设置内容生成/项目问答共用的业务默认模型；它不调用 WeKnora `/models`。WeKnora 的 embedding、rerank 和部署必需兼容 LLM 槽位继续由 `/api/v1/admin/weknora/default-models` 独立管理，既有知识库及索引绑定不迁移、不重建。
- 👤 模型选项（PBC-38，业务用户只读）：`GET /api/v1/weknora/model-options`（顾问入库 / 建库时查看可选模型、按 `type` 过滤；只回安全展示字段 + `is_default` + `default_missing`，无 CRUD、无真实 model id）。

---

## 5. 权限边界摘要

三层访问模型（敏感度递增 L1<L2<L3<L4<L5）：

- **发现层**：标题、类型、标签、scope、zone、阶段、脱敏简述。
- **摘要层**：safe/redacted summary，不含客户敏感数据。
- **原文层**：原始文件、原文 chunk、客户数据、预览、未脱敏上下文——**权限控制重点**。

关键规则：
- 无项目身份用户**也可**查看公司知识库中允许发现的知识摘要（无项目身份 ≠ 只能看个人知识）。
- 项目组人员对**所在项目**知识库拥有摘要与原文（含客户数据原文）权限，行为受审计、无需额外原文申请。
- 非项目成员的在职业务用户可发现其他项目 L1–L4 并查看受控摘要，原文需要逐资产授权；跨项目 L5 不可发现。公司职务不能替代 active 项目成员关系，也不自动开放项目问答或设置。
- 公司顾问可访问公司知识的发现层与安全摘要层；公司原文默认仅总经理 / 咨询总监可访问，并继续遵守保密级别与受控预览规则。
- 公司 L5 仅总经理 / 咨询总监可发现；个人库所有者和本项目 active 成员按其所属范围访问。纯 admin **不**自动发现任何业务知识。
- L3/L4 摘要必须是脱敏摘要，不得含客户敏感数据。L2 是内部一般资料，不强制脱敏，不比 L3/L4 更严格。
- `preview_type` 由保密等级 + 访问场景 + 调用人授权**共同**决定，不固定对应某一保密级别。
- Agent 跟随调用人权限：调用人能看摘要则 Agent 可用同范围摘要；调用人有原文授权则 Agent 同步具备该范围原文能力；调用人无权发现 L5，Agent 亦不能。只读 Agent 只能查询和推荐候选；启用操作权限后可按用户明确指令执行已开放的确认/审批接口，不能绕过证据要求、双席确认或自动授予自己权限。

---

## 6. 外部集成点

服务连接通过环境配置启用，平台默认模型和 KAP 生成模型在管理页面维护，敏感配置加密保存。未配置时按接口返回降级或不可用状态，不伪装成功；真实密钥不入仓库：

| 集成 | 作用 | 未配置时 |
|---|---|---|
| **WeKnora** | 知识底座 / 嵌入与索引 / 两阶段检索 | 跳过索引，检索降级 |
| **外部 LLM** | 入库内容处理（摘要/抽取/改写） | 降级为确定性草稿，上传不失败 |
| **企业微信（WeCom）** | OAuth 身份、治理通知 | OAuth 未启用，通知仅本地 in_app |
| **ONLYOFFICE** | 受控只读原文预览 | 预览安全降级，不泄露原文 URL |
| **本地持久卷 / WeKnora** | 受控上传字节存储 / 向量索引 | 当前字节存储使用 `LocalFileStorage`；S3/OSS/MinIO 适配未实现，不能通过配置直接启用 |

provider 内部标识（dataset/workflow/kb/model id、bucket、api_key 等）为 **server-only，绝不外泄前端**。

---

## 7. 安全输出边界

普通业务投影、日志、审计和报告不得包含以下内容。专用认证/配置接口按契约交付必要凭证；受控原文接口仅向当前获准调用人返回内容，不能把这些例外扩展到普通摘要或通知。

- 服务端密钥：上游 api_key、app_secret、jwt_secret、各类签名/HMAC 密钥。
- server-only 内部标识：WeKnora kb/doc/model id、Dify dataset/workflow/app id、对象存储 bucket / 受控存储引用、内部文件引用。
- 凭证派生物与认证材料：登录标识 / IP 的不可逆 hash、密码 hash、会话/CSRF/OAuth state token（专用认证响应除外，禁止写入业务日志）。
- 客户敏感数据：未脱敏原文 / chunk、原始业务文件名、原始 IP、原文下载 URL。
- L3/L4 摘要中的客户敏感数据；他人个人知识的发现 / 摘要。

> 契约层防回归：`scripts/export_openapi.py` 在导出时扫描**响应可达** schema 的字段名与
> 示例值，命中上述红线标识即报错并阻断（详见脚本头注释）。
