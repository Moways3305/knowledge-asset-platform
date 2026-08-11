# Live Smoke Checklist

> 上线后对**已部署的真实实例**做最小验证：健康、鉴权、CSRF、密码/企微登录、上传→索引→搜索、权限边界、WeCom 扫描配置、ONLYOFFICE 预览。
>
> 配套：部署步骤 → [`PRODUCTION_DEPLOYMENT_RUNBOOK.md`](./PRODUCTION_DEPLOYMENT_RUNBOOK.md)；配置项名 → [`PRODUCTION_SECRET_CHECKLIST.md`](./PRODUCTION_SECRET_CHECKLIST.md)。
>
> **安全红线**：每一步的请求 / 响应 / 日志 / 截图都**绝不**包含 secret / token / cookie / session token / OAuth state / CSRF token、`DATABASE_URL` / `REDIS_URL` / broker URL、对象存储签名 URL、WeKnora kb/doc/model id、原文 / chunk / 业务文件名。下文「不应出现」列逐步标注。

---

## A. 自动安全烟测脚本

```powershell
python scripts/production_smoke.py --base-url <prod-url> --expect-prod-ready --json
```

- **覆盖**：`/health`（活性）、`/health/ready`（DB/Redis 就绪）、`/health/config`（白名单安全字段）、前端入口 `/`（HTML+200）、未登录 `/admin/ops/summary`（期望 401/403）。
- **exit code**：
  - `0` = health + ready 通过且无需阻断 / 无 blockers；
  - `1` = health 或 ready 不通过，或 `--expect-prod-ready`（= `--fail-on-production-blockers`）且 `/health/config` 存在 production blockers。
- **为什么输出不含 secrets**：脚本纯标准库、只读探活；`/health/config` 仅摘取白名单字段（项名 / 布尔 / provider 名 / `production_ready` / `blockers` / `warnings` / `missing_config`），其余正文一律不回显；绝不打印响应正文 / `Authorization` / `Cookie` / api_key / 连接串。逻辑由 `backend/tests/test_pbc17_production_smoke.py` 单测锁定（含 redaction 断言）。
- **不应出现**：响应正文、cookie、`Authorization` 头、任何 `*_KEY` / `*_SECRET`、连接串。

---

## B. 手工 / 半自动核心流

> 表示法：每步给出 **操作人角色 / 预期结果 / 可观察审计或日志 / 不应出现的敏感字段**。请求可用浏览器（真实前端）或 `curl`/`Invoke-WebRequest`（注意 CSRF 与 cookie 行为）。

### B1. 未登录访问 admin ops → 鉴权生效
- 操作人：匿名（未登录）
- 步骤：`GET <prod-url>/admin/ops/summary`
- 预期：`401` 或 `403`
- 可观察：HTTP 状态；无业务数据返回
- 不应出现：任何运营计数 / 业务标题 / 用户清单

### B2. 密码登录成功 + 登出需 CSRF
- 操作人：业务用户（已设密码）
- 步骤：
  1. `POST /api/v1/auth/login`（`email` + `password`）→ 预期 `200`，下发 httpOnly 会话 cookie；`login_method=password`。
  2. `GET /api/v1/auth/csrf` → 取 `csrf_token`。
  3. `POST /api/v1/auth/logout` **带** `X-CSRF-Token` → 预期 `200`；**不带** → 预期 `403`（CSRF fail-closed）。
- 可观察审计：`login.success`（登录）、`login.logout`（登出，记录真实 `login_method`）
- 不应出现：响应体 / 日志中的明文 password、session token、cookie 值、CSRF token、`token_hash`、PBKDF2 摘要
- 失败口径：错误密码 / 未知账号 / 锁定一律 `401` + 「邮箱或密码错误，请稍后再试」，不区分（不暴露账号是否存在 / 是否锁定）

### B3. 企微 OAuth 配置检查（无需真实走完授权）
- 操作人：业务用户（企微成员）
- 步骤：`GET /api/v1/auth/wecom/start` → 预期返回授权跳转（企微未配置时 fail-closed 安全错误，非伪装成功）
- 检查：`WECOM_REDIRECT_URI` 与企微后台可信回调域名一致；callback = `GET /api/v1/auth/wecom/callback`（GET，不受 CSRF 拦截，state 校验不变）
- 可观察审计：成功走完时 `login.success`（`login_method=wecom_oauth`）；成员失效时 fail-closed（不建会话）
- 不应出现：`wecom_user_id`、通讯录档案字段、access_token、OAuth code/state、上游 errmsg

### B4. admin ops 可达 / 业务用户不可达 admin ops
- 操作人：admin（系统管理） vs 普通业务用户
- 步骤：分别以总经理 / 咨询总监调用 `GET /admin/people`；以 pure admin 调用该接口；普通业务用户访问 `/admin/ops/*`
- 预期：admin / 治理角色 `200`；普通业务用户 `403`
- 可观察：HTTP 状态；pure admin 返回 403，治理角色列表仅含安全人员/角色元数据
- 不应出现：`token_hash` / session token / OAuth / 存储引用 / 业务原文；注意 **纯 admin `title_visible=false`**，admin 不应看到业务知识标题/原文

### B5. 上传 Path B：upload → AI result → confirm
- 操作人：业务用户（有上传权限）
- 步骤：
  1. 上传文件（Path B，写真实字节到受控存储，server-only ref 不进响应）。
  2. 轮询 `GET /api/v1/ingest/{id}/ai-result` 直到 AI 结果就绪（异步 worker 真实抽取 + 外部 LLM 内容建议）。
  3. `POST /api/v1/ingest/{id}/confirm`（带 CSRF）→ 入库，标题按平台命名标准。
- 预期：confirm 成功；空标题 / 空摘要 / 仍在处理时 confirm 被拒
- 可观察审计：`ingest.ai_extracted`（成功）/ `ingest.failed`（失败），同一 `trace_id` 贯穿 HTTP→worker
- 不应出现：响应 / 日志中的 `source_file_ref`、存储路径、对象存储 URL、WeKnora id

### B6. confirm 后索引状态可见
- 操作人：admin / 运维角色
- 步骤：`GET /admin/ops/indexing`（或 `/admin/ingest` 运营面板）查看该资产 `index_status`
- 预期：`indexed`（成功）或显式失败态（`index_failed` / `skipped`），失败可见且可发起 retry-index / reparse
- 可观察：安全索引状态聚合；后台作业 `indexing_operation_jobs` 安全统计
- 不应出现：WeKnora kb/doc id、原始 upstream error.code、存储引用、原文

### B7. search 召回 indexed 资产
- 操作人：有发现权限的业务用户
- 步骤：`POST /api/v1/knowledge/search`（语义检索）
- 预期：能召回 B5 已 `indexed` 的资产；结果经权限裁剪 + 脱敏；展示 cards / answer / citations / 原文层状态 + `trace_id`
- 可观察：搜索结果由后端权限网关执行（不在前端本地过滤）
- 不应出现：他人个人知识、越权命中、`dataset_id`/`workflow_id`/`kb_id`/`doc_id`、原文敏感数据

### B8. index_failed / skipped 不被召回
- 操作人：同 B7
- 步骤：对一个 `index_failed` 或 `skipped` 的资产做检索
- 预期：**不**出现在召回结果（检索只映射/使用 active 版本 `index_status=indexed` 的文档）
- 可观察：召回集不含失败/跳过资产
- 不应出现：失败资产的原文 / chunk

### B9. 原文权限边界：无授权不可看，有授权可看
- 操作人：跨项目范围业务用户（对项目 L1-L4 原文）/ 公司范围业务用户（对公司 L3/L4 原文）
- 步骤：
  1. 无授权访问原文层（知识详情原文 / 预览 / 原文取件）→ 预期按「需申请」拒绝（`original_requires_request`）。
  2. 发起原文访问申请 → 审批通过生成 active `access_grant` → 再访问 → 预期放行。
  3. 撤销 / 过期后 → 立即失效。
- 可观察审计：`access.original_*`（申请/审批/拒绝/撤销）
- 不应出现：拒绝态下的原文 / chunk / 存储引用；项目组成员看本项目原文为设计内（审计但不需额外申请）

### B10. WeCom scan config 配置页可打开且安全显示
- 操作人：admin（启停/触发） / boss / 咨询总监（读配置/记录）
- 步骤：打开 `/admin/wecom-scan`，查看 `GET /configs`、`GET /configs/{id}/records`
- 预期：配置页可打开；未配企微租户时按提示安全降级（前端已接 ≠ 真实租户可用）
- 可观察：仅安全运营元数据
- 不应出现：WeCom 文件 id、download URL、access_token、`WECOM_APP_SECRET`、扫描到的业务文件名

### B11. ONLYOFFICE 预览（启用时）
- 操作人：有原文层权限的业务用户
- 配置职责：`ONLYOFFICE_DOCUMENT_SERVER_URL` 是浏览器可访问的 Document Server origin；`ONLYOFFICE_ORIGIN` 是前端 CSP 放行的同一个精确 origin；`ONLYOFFICE_INTERNAL_BASE_URL` 是 Document Server 回取 KAP 受控文件端点时可访问的基址。前两项必须同源，浏览器地址不得使用 Docker DNS。
- 步骤：
  1. 先看 `/health/config` 的 `integrations.onlyoffice_config`，四个布尔状态均应为 `true`，且无 `ONLYOFFICE_*` blocker。响应只记录布尔和配置项名。
  2. 用有原文权限的账号打开一个受支持的 `.md` 或 `.docx`，浏览器 DevTools Network 只确认 `api.js`、编辑器 iframe 和受控 `/file?ft=...` 请求的 HTTP 结果；Console 只记录错误类别（CSP / 网络 / 编辑器），不得复制完整消息或地址。
  3. 成功场景应在文档就绪后移除“正在打开”；预览保持只读，关闭后编辑器实例被销毁。
  4. 在测试/生产等价环境临时阻断 Document Server（或用浏览器 DevTools Request blocking 阻断 `api.js`），确认有限时间内显示安全失败和“重新打开预览”，不永久加载。完成后立即恢复阻断。
- 预期：启用且三项配置匹配时预览可打开；脚本、CSP、编辑器或回取失败时进入可重试失败态，不降级为下载或直接文件链接。
- 可观察：只记录 HTTP 状态和 `script_load_failed` / `editor_failed` / `preview_timeout` 等类别；走集中权限 + 预览凭证 + 审计（L5 强审计）。
- 不应出现：完整 `/file?ft=`、fetch token、JWT、Document Server/KAP 完整 URL、容器地址、`storage_ref`、对象存储位置、credential/asset/WeKnora id、Console 原始错误正文。

### B12. `/health/config` 无 production blockers
- 操作人：运维
- 步骤：`GET <prod-url>/health/config`
- 预期：`production_ready=true`、`production_blockers=[]`；warnings 按集成启用情况确认
- 可观察：只回布尔 / provider 名 / 项名（安全可贴）
- 不应出现：任何值 / 密钥 / URL / 连接串 / 内部 id

---

## 通过判定

- A 脚本 exit code 符合预期（live 不可达 / unhealthy 时为非 0，且报告说明原因）。
- B1–B12 预期结果全部满足，且全程无敏感字段泄露。
- 任一步失败 → 按 [`PRODUCTION_DEPLOYMENT_RUNBOOK.md`](./PRODUCTION_DEPLOYMENT_RUNBOOK.md) §5 排障 / 回滚。
