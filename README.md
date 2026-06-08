# 知识资产平台

Vite + React + TypeScript 前端原型，面向咨询公司知识资产管理场景。

## 启动

```bash
npm install
npm run dev
```

开发服务器默认地址：http://localhost:5173

## 构建

```bash
npm run build
npm run preview
```

## 当前可访问路由

| 路由 | 页面 | 说明 |
|------|------|------|
| `/` | — | 自动跳转到 `/knowledge` |
| `/knowledge` | 知识首页 | 三层知识库切换、搜索、筛选、"包含归档"开关（默认不展示归档资产）、资产状态 badge（活跃/待更新/已废弃/已归档）、归档资产弱化展示（归档原因 + 最后调用时间）、资产卡片列表、洞察侧栏 |
| `/knowledge/:id` | 知识详情 | 三层摘要（一句话/详细/关键知识点）、可咨询专家、来源追溯、复用判断、权限治理、保密分级与 AI 调用边界（L1-L5 / A1-A4 + 调用边界说明）、Agent 调用边界（A1-A4 策略 + 权限网关 + 只推荐不越权）、资产生命周期（状态/最后调用时间/维护人/归档说明 + 生命周期治理动作：发起归档建议/确认归档/查看事件）、访问申请与权限深度说明、原文预览（按原文层权限签发受控预览凭证，预览类型由保密等级+场景+授权共同决定、非固定保密级映射；返回凭证指纹与平台受控入口、不返回完整 token；审计留痕） |
| `/upload` | 资产化确认工作台 | 业务侧统一确认入口：路径A（企微微盘 Agent）/ 路径B（本地上传）共享 AI 预览、人工校正、目标库确认、项目分区适用规则（zone 仅项目库适用）、命名规范与保密分级（L1-L5 / A1-A4）、提交入库 |
| `/admin/ingest` | 入库管理 | 运营/管理侧队列监控：路径A Agent 状态面板、来源渠道筛选、目标库类型与分区标签、命名状态（合规/异常）、保密级别（L1-L5）、AI 调用级别（A1-A4）、任务列表、V4 错误处理原则（5 类）、目标库与分区规则说明、命名与保密运营提示、职责边界、操作边界 |
| `/admin/wecom-scan` | 微盘扫描 | Path A 上游配置：企微微盘扫描目录、启用/停用、手动扫描、扫描历史与异常、扫描目标与分区规则（默认资料区） |
| `/review` | 升级审核 | 三类审核（个人→项目/项目→公司/生命周期变更）、触发来源（内部分享/客户验证/项目经理确认/跨项目达标）、候选列表、治理机制 |
| `/project/:id/knowledge` | 项目看板 | 项目概览、生命周期路线（route_A/B/C）与阶段标签、同库 zone 标签分区（资料区/资产区）、Q&A（区分引用来源、可按阶段标签缩小范围、Agent 问答边界说明）、模型选择、风险提醒 |
| `/project/:id/settings` | 项目设置 | 项目基础信息、项目生命周期路线（route_A/B/C）与阶段标签、项目人员与角色（coach/project_manager/consultant）、入库策略、企微群绑定 |
| `/admin/audit` | 审计日志 | 操作日志（含归档/重新启用/归档预警、原文预览凭证签发、Agent 问答调用/网关拒绝/A4 原文降级记录）、异常日志、登录日志、trace_id 追踪、标记已处理 |
| `/admin/alert-settings` | 告警设置 | 三级告警规则、通知渠道、防重复策略、接收人管理 |
| `/my/knowledge` | 个人知识 | 个人知识管理（默认私密不参与他人检索）、主动提交项目资料/内部分享/客户验证、提交建议 |
| `/admin/permissions` | 权限规则 | 真实 `permission_rules` 配置中心（PBC-03）：个人默认私密、本人主动提交、项目资产验证路径、项目升格组合信号、访问申请策略、归档阈值（730 天不活跃 + 30 天预警期，归档扫描运行时阈值以 alert_rules 为准）、外部 Agent 接入注册 / Agent Registry（provider 中立兼容接口）、Agent 调用边界（权限网关 + 角色/项目/保密/AI调用级别约束 + 只推荐不越权 + 审计留痕）；Boss/咨询总监可改、admin 只读 |
| `/admin/people` | 人员权限 | 真实人员 / 公司角色 / 项目成员关系 API（PBC-02）：用户列表、平台角色（含咨询总监）、项目人员关系、权限边界、企微 OAuth 绑定状态 |

## Demo 走查顺序

推荐按以下顺序演示，完整讲述知识资产从产生到复用的全链路，以及平台治理与审计能力。每个页面附讨论重点，便于评审时聚焦核心设计决策。

### 1. 知识首页 `/knowledge`

**定位**：公司级知识资产平台的核心入口，信息聚合与检索起点。

讨论重点：
- 三层知识库切换（公司 / 项目 / 个人）如何体现知识的分层治理
- KPI 统计条（总资产 / 可复用 / 需关注）是否覆盖运营人员的关键关注点
- 搜索 + 多维筛选（项目、客户、业务阶段、资料类型、可见性）的组合能力
- 资产卡片信息密度：标题、摘要、标签、来源、置信度、更新时间
- 洞察侧栏的运营价值：推荐复用、低置信度预警、升级候选
- "包含归档"开关：默认隐藏已归档资产，打开后灰化展示归档资产（归档原因 + 最后调用时间）

### 2. 知识详情 `/knowledge/ka-001`

**定位**：单个知识资产的全貌视图，面向查阅者和咨询总监。

讨论重点：
- 三层摘要（一句话摘要、详细摘要、关键知识点）的信息层次设计
- 可咨询专家模块：复杂判断场景下顾问或 Agent 可联系专家复核
- 来源追溯区（文件、项目、客户、业务阶段、创建时间）是否覆盖咨询项目需要的上下文
- 复用判断三卡片（可复用性、置信度、适用范围）的实用性
- 三种可见性（公开 / 项目内 / 机密）的权限文案与治理规则
- 保密分级与 AI 调用边界：L1-L5 保密级别、A1-A4 AI 调用级别、调用边界说明、L4/L5 边界警告
- 访问申请与权限深度：两阶段返回策略、跨项目 7 天授权窗口、超时自动通过（机密除外）
- 原文预览：由后端受控预览凭证驱动；签发以**原文层权限**为准，而非按保密级别固定映射（预览类型由保密等级 + 访问场景 + 授权共同决定，非硬编码 L1-L5 映射）；前端仅拿到凭证指纹与平台受控预览入口，不返回完整 token / 对象存储 URL；ONLYOFFICE 只读预览已接入，未配置时安全降级且不泄露原文 URL
- Agent 调用边界：A1-A4 调用策略、权限网关说明、Agent 不获得预览 token、Agent 只推荐不越权
- 资产生命周期区域：asset_status（active/needs_update/deprecated/archived）、last_called_at、维护人；归档为「发起候选 + 人工确认」两步真实流程（已接后端）；重新启用后端生命周期已支持，详情页暂未开放入口、引导联系维护人
- 操作区按钮（申请原文权限 / 推荐升级 / 编辑可见性 / 导出摘要）的业务价值

### 3. 资产化确认工作台 `/upload`

**定位**：业务侧统一资产化确认入口，路径A 和路径B 共享相同的下游确认流程。

路径A — 企微微盘自动检测（真实链路，PBC-07）：
- 页面展示企微微盘扫描（R6）创建的**真实待确认任务**（`GET /api/v1/ingest/pending?source=path_a_wecom`），仅显示当前用户有权确认的任务；含 loading / error / empty / success 四态，空态指向 `/admin/wecom-scan` 配置/手动扫描
- 选择一条任务后拉取真实 AI 建议（与 Path B 同一 `ai-result` 接口），下方显示 AI 预览 + 人工校正 + AI 建议目标知识库 + 提交入库（复用 Path B 同一 `confirm` 链路）
- 来源渠道标记为"企微微盘"

路径B — 本地上传资产化（真实链路）：
- 本地文件选择 → 上传至平台受控存储 → worker 异步抽取文本 → 外部 LLM 生成命名规范化标题、三层摘要、标签、分类草稿（LLM 不可用时 fail-closed 降级为确定性建议并提示人工校正）→ 人工校正 → 提交入库
- 文件存储边界：Path B 将选中文件的字节上传至平台受控本地开发存储；后端只返回安全元数据，不返回存储路径 / `source_file_ref` / 对象 URL / 内部引用；文本抽取与外部 LLM 内容处理已真实接入。**入库前实体级规则脱敏已实现（PBC-13）**：抽取成功后先做确定性规则脱敏（邮箱 / 手机号 / 固话 / 身份证 / 银行卡 / 长账号 / 金额 / 联系人 / 客户字段），平台侧外部 LLM 内容建议仅使用脱敏后文本；不可抽取文本则无法做文本级前置脱敏、平台侧 LLM 降级不接触原文。**WeKnora 底座及其 LLM 是老板确认的受信任底座处理方，按该信任边界仍可接触原始文件/原文做索引**，索引链路不因规则脱敏缺失而阻断。未实现：OCR / 扫描件识别、结构保持式文件重写、Ollama/LLM 脱敏、历史资产全量重索引
- 来源渠道标记为"本地上传"

命名规范与保密分级区：
- 平台文件命名格式：【一级类-二级类】主题_对象/客户_日期_V版本_L保密级别
- 合规示例展示
- 当前文件命名解析结果（真实 `naming_parsed_fields`）：规范化标题 + 一级类/二级类/主题/对象或客户/日期/版本/保密级别（L1-L5）/AI 调用级别（A1-A4）；对 AI 推断或默认字段标「AI 推断」、对缺乏依据字段标「待人工校正」
- 命名异常处理原则：不阻止入队，但标记异常并进入人工审核
- 阶段标签参考说明（平台规则提示）：列出可选业务阶段，由顾问/项目经理在「人工校正 · 业务阶段」确认后写入；非固定 AI 建议
- L1-L5 保密级别与 A1-A4 AI 调用级别参考卡片
- L4/L5 文件不得进入开放式 AI 调用

共享确认区：
- AI 生成预览卡片（标题、摘要、标签、置信度、来源）
- 人工校正区（标题 / 摘要 / 标签 / 可见性 / 业务阶段均可编辑）
- AI 建议目标知识库（个人 / 项目 / 公司）+ 推荐理由 + 分流说明
- 项目分区适用规则面板：根据目标库展示 zone 是否适用、推荐分区、规则说明和后续动作
- 单一主操作：提交入库

目标库与 zone 适用规则：
- 个人知识库：项目分区不适用，仅本人可见，不显示 zone
- 项目知识库：默认资料区（zone = material），资产区需验证 + 项目经理确认
- 公司知识库候选：项目分区不适用，需公司级审核

讨论重点：
- "AI 建议 + 人工确认/修正"模式是否符合顾问工作习惯
- 目标知识库分流逻辑（置信度、敏感级别、项目策略）
- zone 分区仅适用于项目知识库的设计合理性
- 路径A 与路径B 共享确认流程的信息架构合理性

### 4. 入库管理 `/admin/ingest`

**定位**：运营/管理侧队列监控与异常处理。业务侧确认在资产化确认工作台（`/upload`）完成；本页用于运营监控与异常处理。

讨论重点：
- 职责边界：业务确认在资产化确认工作台完成，本页只做运营队列监控与异常处理
- Admin 权限边界：可处理系统异常但不默认拥有业务原文访问权
- Boss / 咨询总监负责公司级治理与高风险入库策略
- 路径A（企微微盘 Agent）状态面板：Agent 运行状态、监控目录、新检测文件
- 来源渠道筛选：区分 Agent 自动检测与本地上传来源
- 目标库类型列：每条任务展示推荐目标知识库（个人/项目/公司候选），项目库任务额外展示 zone = material
- 命名状态列：合规 / 命名异常，异常任务高亮提示
- 保密级别列（L1-L5）与 AI 调用级别列（A1-A4）：badge 展示
- 命名与保密运营提示：命名异常处理原则、L4/L5 保密边界、AI 调用级别推导说明
- 目标库与分区规则说明：只有项目知识库任务才有 zone 分区标签；个人知识库不展示分区；公司候选不直接入库
- 四种处理状态（处理中 / 待审核 / 已完成 / 失败）的队列管理
- V4 错误处理原则：脱敏失败、AI 提取失败（3 次重试）、WeKnora 写入失败（回滚）、哈希重复、AI 置信度低
- 操作边界：重试回队列、驳回需原因、公司库目标须 Boss / 咨询总监审核
- 质量风险提示：自动审核分流、失败重试上限、机密资产审核周期

### 5. 微盘扫描 `/admin/wecom-scan`

**定位**：Path A 上游配置页，管理企微微盘扫描目录，控制哪些文件源会自动生成待确认资产化任务。

讨论重点：
- 公司级 vs 项目级目录配置的区分与管理
- 目录启用/停用控制 Path A 数据源的开关
- 手动触发扫描：运维排查场景
- 扫描历史与异常摘要：权限异常、文件重复等
- 扫描目标与分区规则：推荐项目知识库时默认资料区（zone = material）；个人知识库无分区；公司候选不使用 zone
- 扫描发现文件后的下游流向：`/upload` 确认 → `/admin/ingest` 入队

### 6. 升级审核 `/review`

**定位**：知识从个人到公司的价值沉淀治理工作台。

讨论重点：
- 三类审核类型：个人 → 项目、项目 → 公司、生命周期状态变更（待更新/停用/归档）
- 个人→项目触发来源：内部分享、客户验证、项目经理确认（由本人主动提交触发）
- 项目→公司触发来源：跨项目调用达标、责任人确认
- 证据登记：内部分享候选展示分享证据类型（会议纪要/企微群记录等），客户验证候选展示验证证据（验收单/客户确认邮件等）
- 四种审核状态：待顾问确认、待老板审核、已通过、已拒绝
- 三角色职责分工：顾问主动提交并确认内容、项目经理确认资产区与可见性、Boss / 咨询总监审核公司级标准
- Agent 边界：Agent 只推荐候选，不自动改变资产状态，不自动认定内部分享或客户验证完成
- 公司库升格必须人工审核；生命周期变更由责任人确认，不允许系统静默停用或归档
- "本人主动提交 + 证据登记 + 项目经理确认 + 人工审核"机制为什么优于全自动升级

### 7. 项目看板 `/project/:id/knowledge`

**定位**：知识如何嵌入咨询项目生命周期的驾驶舱视图，项目知识库分为资料区和资产区。

讨论重点：
- 生命周期路线驱动的阶段列表（route_A：售前 → 诊断 → 启动共识 → 定题 → 目标计划 → 行动辅导 → 阶段评估 → 年度复盘）可点击切换
- 同一项目知识库通过 zone 标签（material/asset）分为资料区和资产区，资料转资产是状态变化而非搬迁
- 资产区内容展示验证来源：内部分享或客户验证
- 阶段 Q&A 区分引用来源：来自资产区的引用已验证可优先引用，来自资料区的引用需谨慎确认；Agent 问答边界说明（检索范围限当前项目、个人知识不命中、L4/L5/A4 不进入、必须展示引用来源、权限网关审计）
- 问答模型选择器：系统默认 / DeepSeek-R1 内网版 / 通义千问企业版
- 风险/缺失提醒随阶段联动，治理提示覆盖资料与资产区的治理规则

### 8. 项目设置 `/project/:id/settings`

**定位**：单项目的人员管理、角色配置与入库策略工作台，与全局人员权限页形成职责互补。

讨论重点：
- 项目生命周期路线（route_A 完整路线 / route_B 年度辅导循环 / route_C 专项诊断）的选择与阶段列表
- 当前阶段标签展示与路线覆盖的阶段可视化
- 三类项目内角色（coach / project_manager / consultant）的边界清晰度
- `force_review_on_ingest` 策略开关对 `/upload` 资产化确认的影响
- 人员来源区分：手动添加 vs 企微同步
- 项目设置 vs 全局人员权限的职责分界
- 项目内角色可本地调整，讨论"谁有权限调整角色"

### 9. 审计日志 `/admin/audit`

**定位**：平台所有关键动作可追踪、异常可处理、登录安全可审计。

讨论重点：
- 三类日志 tab 切换：操作日志、异常日志、登录日志
- 操作日志展示 action、operator、role、target、变更前后、trace_id，含生命周期记录（归档预警 / 归档候选 / 确认归档 / 重新启用——本阶段不实现定时扫描或静默自动归档，归档与重新启用均需人工确认）、原文预览相关记录（签发预览凭证、拒绝原文预览）和 Agent 调用相关记录（Agent 问答调用、Agent 调用被权限网关拒绝、A4 原文降级）
- 异常日志按 severity（Critical / Error / Warning）和处理状态（已处理 / 未处理）筛选
- 异常日志支持"标记已处理"，KPI 实时更新
- 登录日志展示用户、结果、IP、设备、trace_id
- trace_id 说明：已实现的 API 与审计 / 生命周期 / Agent 记录均携带 trace_id，可关联本地后端已实现的调用链；经 Celery / WeKnora / 向量存储的真实跨服务传播为延后项、尚未实现

### 10. 告警设置 `/admin/alert-settings`

**定位**：告警规则与通知策略的配置中心，确保异常事件及时触达责任人。

讨论重点：
- 六条告警规则覆盖：脱敏失败、WeKnora 超时、队列积压、API P99、入库失败率、登录失败
- 规则可按级别（Critical / Error / Warning）和启用状态筛选
- 启用/停用开关实时更新 KPI
- 阈值可通过 number input 直接调整
- 通知接收人卡片可启用/停用
- 通知策略说明：Critical 立即双通道、Error 企微 5 分钟不重复、Warning 汇总日报、防重复策略

### 11. 个人知识 `/my/knowledge`

**定位**：个人知识的私有工作台，个人知识默认不参与他人检索，只有本人主动提交才进入项目侧。

讨论重点：
- 个人知识默认私密，项目经理和其他顾问无法搜索到你的个人知识
- 主动提交模型：提交项目资料 / 发起内部分享候选 / 登记客户验证候选
- 五种状态：私密、已提交项目资料、内部分享候选、客户验证候选、已转项目资产
- 提交到项目资料区不等于项目资产，资产需经内部分享或客户验证路径确认
- 证据模型：内部分享/客户验证是真实业务事件，系统只登记证据（会议纪要/企微记录/验收单/客户邮件/交付采纳），不替代真实会议或客户确认
- 候选状态提示：内部分享候选需补充分享证据并由项目经理确认；客户验证候选需补充验证证据并由项目经理确认
- 提交建议：系统可建议提交，但最终由本人决定
- 三级摘要详情面板：一句话摘要、详细摘要、关键知识点

### 12. 权限规则 `/admin/permissions`

**定位**：真实 `permission_rules` 配置中心（PBC-03）的可视化管理页，展示知识流转规则、访问策略与外部 Agent 接入注册（Agent Registry）配置。读写经后端 `GET/PATCH /api/v1/admin/permissions/rules`。

讨论重点：
- 四组规则分类：个人知识流转、项目知识升格、访问申请、资产生命周期（含归档阈值 asset_archive_inactive_days=730 天 + asset_archive_notice_days=30 天）
- 个人知识流转：个人知识默认私密（不参与他人检索）、本人主动提交才进入项目、项目资产需验证路径（内部分享/客户验证）
- 验证路径与证据登记：project_asset_validation_paths 代表验证路径，不代表系统自动验证；内部分享和客户验证必须有证据登记（会议纪要/企微记录/验收单等），并由项目经理确认后才能 zone: material → asset
- 项目知识升格：跨项目来源阈值（3 个项目，复用广度）+ 跨项目调用次数阈值（10 次，复用强度）+ 信号统计窗口（90 天），组合判断公司库候选
- 知识流转模型说明：个人知识不参与他人检索，项目资产升格用组合信号判断
- 规则值展示：业务规则（默认私密/本人确认/验证路径）使用业务语言展示，不暴露布尔数字值；数字阈值规则才用数字编辑
- 规则类型标签：每条规则标注类型（数字阈值/开关规则/固定路径），便于区分可编辑范围
- 数字阈值可本地编辑，讨论"这些阈值是否合理"
- 外部 Agent 接入注册 / Agent Registry（provider 中立兼容接口 `/admin/permissions/agent-whitelist`，admin 管理）控制哪些外部 Agent 可调用知识库，含调用范围与风险提示；不暴露 token / provider 内部标识
- Agent 调用边界：Agent 通过平台后端权限网关调用，受平台身份/项目角色/知识库类型/zone/保密级别/AI调用级别约束；不读取个人知识（除非本人提交）；不读取 L4/L5 原文；只生成建议不执行治理动作；调用审计留痕
- AI/Agent 边界：AI 或 Agent 不得自动将资料标记为资产区，不自动认定内部分享或客户验证完成
- 规则影响预览：修改规则会影响哪些下游页面
- 可修改角色限定（Boss / 咨询总监），admin 只读；修改写入审计日志（`config.permission_rule_updated`）
- 运行时边界：PBC-03 落配置中心；PBC-06 已接入原文申请 / 审批 / 授权 / 撤销与 active `access_grant` 运行时放行（`access_grant_duration_days` 为默认有效期来源）。**PBC-11E 已把指定规则接入真实权限运行时**：L1/L2 原文默认放行开关（`cross_project_l1_l2_original_for_business_user` / `company_l1_l2_original_for_business_user`，经 `load_access_policy()` 注入 `decide()`）与原文访问申请超时自动通过（`access_request_timeout_hours`，仅 L1/L2 生效、L3-L5 不自动通过）。`DEFAULT_POLICY` 仅作规则缺失时的出厂回退（禁用/取值非法 fail-closed）。其余 `permission_rules`（个人流转、升格阈值、`review_timeout_hours`、生命周期 / 归档阈值等）仍只是治理配置视图，不驱动运行时；归档扫描运行时阈值仍以 `alert_rules` 为准

### 13. 人员权限 `/admin/people`

**定位**：真实人员 / 公司角色 / 项目成员关系管理页（PBC-02），数据来自 `/api/v1/admin/people`；企微 OAuth 已接入，绑定状态来自后端。

讨论重点：
- 五种平台角色权限边界卡片：Admin / Boss / 咨询总监 / 项目经理 / 顾问
- 咨询总监：公司库审核、知识流转阈值配置、跨项目知识治理
- **同人多项目多角色**：平台身份不是单项目权限；同一人可在不同项目中担任不同项目内角色（coach / project_manager / consultant，如张明在华润项目是辅导老师，在美的项目是项目经理，在恒瑞项目是顾问）；进入不同项目时，系统按当前项目内角色展示视角
- 项目人员关系表：辅导老师、项目经理、顾问、可见性规则的项目级视角
- 筛选与详情交互：按平台角色 / 状态筛选，点击查看用户详情面板；公司角色 / 项目成员关系写动作经后端权限校验与审计
- 真实后端：角色与人员关系来自 `users` / `user_company_roles` / `project_members`；admin 不因系统身份获得业务原文权

## 当前产品边界

前端已对接后端生产化链路（IMPLEMENT-00~14 + R1-R8 + PBC-01~09）：身份 / 知识资产 / 权限判断 / 知识读 API / 入库（Path A + Path B）/ 语义检索 / 审核 / 预览凭证 / 外部 Agent 网关 / 审计 / 生命周期归档与告警 / 人员治理 / 权限规则配置中心 / 项目设置 / 个人知识写动作 / 原文访问授权均已实现。页面主数据均由真实后端 API 驱动；仅余少数明确标注的治理增强与规划项未接。边界如下：

- 已集成真实后端 API 的页面：`/knowledge`（含 `POST /api/v1/knowledge/search` 语义检索，PBC-08）、`/knowledge/:id`、`/my/knowledge`、`/upload`（Path A + Path B）、`/review`、`/project/:id/knowledge`（项目 Q&A）、`/project/:id/settings`、`/original-access`、`/admin/people`、`/admin/permissions`、`/admin/audit`、`/admin/alert-settings`、`/admin/ingest`（运营列表 `GET /api/v1/admin/ingest`，仅安全运营元数据）、`/admin/wecom-scan`（R6 微盘扫描 `GET/PATCH /configs`、`POST /configs/{id}/scan`、`GET /configs/{id}/records`）、顶栏企微 OAuth 登录入口（`GET /api/v1/auth/wecom/start` → 跳转授权，会话由后端 httpOnly cookie 控制）
- 关于 `/admin/wecom-scan`：前端已接后端 API；**真实企微租户连接由后端 env（`WECOM_*`）配置控制**，未配置时后端 fail-closed 返回安全错误，前端按提示处理（前端已接 ≠ 真实租户已可用）。读配置/记录为 admin/boss/咨询总监，启停与手动触发为 admin。
- **已从 mock 收口为真实后端**：
  - `/admin/people`（PBC-02）：真实人员、公司角色、项目成员关系 API（`/api/v1/admin/people`），读为 admin/Boss/咨询总监，写经后端权限校验与审计；不再是前端静态 demo。
  - `/admin/permissions`（PBC-03）：真实 `permission_rules` 读写 API（`GET/PATCH /api/v1/admin/permissions/rules`），Boss/咨询总监可改、admin 只读、顾问无权，写入 `config.permission_rule_updated` 审计；Agent Registry 区块接 provider 中立后端兼容接口 `/admin/permissions/agent-whitelist`；不再是纯 UI 演示。
  - `/admin/audit` 登录 tab（Batch C1）：展示真实 `login.success` / `login.failed` / `login.logout` 审计事件（本地会话登录 + R6 企微 OAuth 写入），不再是占位。
  - `/project/:id/settings`（PBC-04）：真实项目设置 / 成员 API（`/api/v1/projects/{id}/settings`、`/members`），不再是静态 demo。
  - `/my/knowledge` 写动作（PBC-05）：本人资产确认、提交项目资料、内部分享 / 客户验证候选已接真实后端（生成审核任务 / 证据记录）。
  - 原文访问申请 / 授权（PBC-06）：`/knowledge/:id` 可发起原文访问申请，`/original-access` 提供审批 / 拒绝 / 撤销；审批通过生成 active `access_grant`，运行时原文层（知识详情 / 预览 / 原文取件 / 外部 Agent 检索）统一叠加 active grant 放行，过期 / 撤销立即失效。
  - `/upload` Path A（PBC-07）：企微微盘扫描创建的 `path_a_wecom` 待确认任务接 `GET /api/v1/ingest/pending`，按权限只显示可确认任务，复用 Path B `confirm` 链路入库；不再是静态 `agentFiles` 演示列表。
  - `/knowledge` 语义检索（PBC-08）：搜索框接 `POST /api/v1/knowledge/search`（WeKnora 召回 + 意图路由 + 权限裁剪 + 脱敏），展示后端 cards / answer / citations / 原文层状态与 trace_id；不再是本地列表过滤。
- **已实现（PBC-13）**：入库前实体级**规则脱敏**——抽取成功后确定性规则擦洗常见敏感实体，平台侧外部 LLM 内容建议仅用脱敏文本；WeKnora 底座按老板确认信任边界仍可接触原文索引。未实现：OCR、结构保持式文件重写、Ollama/LLM 脱敏、历史资产全量重索引
- **已接入运行时（PBC-11E）**：原文访问申请超时自动通过（`access_request_timeout_hours`，仅 L1/L2）、L1/L2 原文默认放行开关规则化（`cross_project_l1_l2_original_for_business_user` / `company_l1_l2_original_for_business_user` 经 `load_access_policy()` 驱动 `decide()`，`DEFAULT_POLICY` 仅作规则缺失回退）
- **已实现（PBC-15）**：索引**批量 retry-index** + **显式 reparse** + **后台队列化运维**——`/admin/ingest` 运维面板可对筛选出的失败 / 跳过 / 未索引资产发起批量重试，对已进底座但解析异常的资产发起受控重传式 reparse；批量动作进入后台作业（`indexing_operation_jobs`），面板展示作业安全统计与最近作业列表；`refresh-parse` 仍是只读对账。响应 / 审计 / 前端不泄露 WeKnora kb·doc id / 存储引用 / 原文
- **已实现（PBC-16）**：`/knowledge` **运营洞察 API**（`GET /api/v1/knowledge/ops-insights`）——右侧洞察面板改由真实后端安全聚合驱动（索引失败/解析异常/KB 初始化失败、最近索引运维作业、原文申请待处理/超时/自动通过、归档候选/升格推荐），按角色范围裁剪：纯 admin 系统运维聚合且 `title_visible=false`、业务治理角色公司/跨项目治理摘要、项目角色/普通业务用户限本人+所在项目；不绕过发现权限、不泄露 WeKnora id/存储引用/原文/文件名
- **仍为后续治理增强 / 规划（非 mock，后端尚无该能力）**：OCR / 扫描件识别、结构保持式文件重写、Ollama/LLM 脱敏、历史资产全量重索引
- 注：上述区分依据 `docs/reviews/PRODUCT_MOCK_DEMO_STUB_AUDIT.md`（历史审计报告，非当前口径）；「真实能力已实现但前端未接」不等于「后端是 mock」。
- 身份：**真实会话**（服务端会话表 + httpOnly cookie）+ **密码凭证登录（PBC-12）**（`POST /api/v1/auth/login` 提供 `email + password` → 所有环境真实校验密码 PBKDF2，`login_method=password`）+ **企微 OAuth（R6）**（`/api/v1/auth/wecom/start`+`/callback`，state 校验、按 `users.wecom_user_id` 解析、`login_method=wecom_oauth`，不自动建用户）；明文 token 只在 httpOnly cookie。不提供密码时，仅 local/dev/test 走 email-only 无凭证开发适配器（`login_method=dev_local`），prod 拒绝（`auth_password_required`）；无会话时仅 local/dev/test 回退 `X-Dev-User-Id`
- **企微微盘 Path A 扫描（R6）**已实现：`/api/v1/admin/wecom-scan/*` 配置/触发/记录，扫描经平台后端下载字节落受控存储 → 建 `path_a_wecom` 入库任务 → 复用入库处理链；需人工 `/upload` 确认才成资产
- 检索 / 问答经 **WeKnora（R1）+ 外部 LLM（R2/R3）** 真实链路 + 集中权限网关 + 输出脱敏（`POST /api/v1/knowledge/search`）。**外部 Agent / 工作流网关为 provider 中立核心（PBC-01）**：权限 / 检索 / 审计 / 无泄露逻辑与具体 provider 无关；**Dify 外部知识库 / HTTP Tool（R4）是其兼容适配器**（临时集成面，未来可加 Coze / 自研适配器），复用同一权限网关；底层 kb_id/doc_id/chunk_id/dataset_id/workflow_id/app_id/api_key 绝不外泄。真实 WeKnora / LLM 端点经 env 启用，未配置则降级
- `/upload` Path B 写真实字节到受控存储（server-only ref，不入响应）；生产对象存储（S3/OSS）经可插拔 `StorageBackend` 平替（本仓库默认本地存储）
- **Celery 异步（R5）**：入库处理 / 解析对账 / 归档扫描 / 复用推荐 / 通知下发经 worker+beat（`CELERY_TASK_ALWAYS_EAGER=false`）；归档与重新启用仍需人工确认
- **ONLYOFFICE 只读预览（R7）**已实现：`GET /api/v1/preview/{id}` 返回真实只读编辑器配置 + 平台受控取件 URL（Document Server 凭短时 token 经平台存储回取字节）；走集中权限 + 预览凭证 + 审计 + L5 强审计，不暴露 storage_ref/对象存储 URL/完整 token/jwt 密钥/WeKnora id；生产需配置 `ONLYOFFICE_*`，未配置则安全降级不泄露原文 URL
- **企微通知真实下发（R7）**：受 `WECOM_NOTIFY_ENABLED` fail-closed 总开关控制（默认关=仅本地 in_app）
- 页面主数据均经真实后端权限判断执行（集中权限服务）；上方列出的后续治理增强 / 规划项（OCR / 文件重写 / LLM 脱敏 / 历史全量重索引等）后端尚无该能力，前端按准确边界展示（明确标注「规划 / 待接入」），不伪装成功、不放可点击的假写按钮、不用本地静态数据冒充后端
- **原文授权（PBC-06）已落地**：`access_grants` / `original_access_requests` 真实表；跨项目 / 公司 L3/L4 原文无授权时按"需申请"拒绝（`original_requires_request`），经申请→审批→生成 active `access_grant` 后运行时放行原文层（`decide(has_original_grant=…)`，source=`access_grant`，需审计），过期 / 撤销立即失效；`access_grant_duration_days`（权限规则）为 grant 默认有效期运行时来源。**PBC-11E 后**：原文申请超时自动通过（`access_request_timeout_hours`，仅 L1/L2）与 L1/L2 原文默认放行开关均已接入运行时（经 `load_access_policy()`，`DEFAULT_POLICY` 仅作规则缺失回退）
- 已集成的后端流程会持久化到本地开发数据库（含会话表）；仅 mock 的前端页面 / 本地 UI 交互不落为真实后端业务数据。凭证校验现状：**密码登录已实现（PBC-12）**——所有环境按 `email + password` 真实校验（PBKDF2），`local/dev/test` 保留 email-only 便利登录（`login_method=dev_local`）、`prod` 必须提供密码；**企微 OAuth 已实现**（`/api/v1/auth/wecom/start` + 后端 `/callback` 建会话，顶栏「企微登录」入口已接入），真实可用性取决于 `WECOM_*` env 配置，未配置时后端 fail-closed 返回安全错误。仍为后续增强：MFA、找回密码、账户锁定、CSRF 全站改造、多设备会话管理
- 顶部栏项目下拉为用户**真实项目成员关系**（来自 `/auth/me`）：切换仅改变顶栏显示的项目内角色 / 视角提示，权限拦截始终以后端会话身份为准（前端选择器不参与鉴权）
- 顾问、项目经理和辅导老师不是全局互斥身份，同一人可在不同项目中担任不同项目内角色（coach / project_manager / consultant）

## 部署（Docker，R8 / PBC-10G）

后端 + Postgres + Redis + Celery worker/beat + **前端 nginx** 一键编排（`docker-compose.yml`，本地非密凭证）：

```powershell
docker compose build
docker compose up -d   # postgres/redis 起后，一次性 migrate 服务自动跑 alembic upgrade head，backend/worker/beat/frontend 随后启动
docker compose exec backend python -m app.seed.dev_seed   # 可选 seed（仅 dev/test）
```

**入口与端口**：
- **本地开发**：`npm run dev`（Vite dev server），`vite.config.ts` 代理 `/api` 到 `http://127.0.0.1:8001`。
- **单机生产**：`docker compose up -d frontend ...`，**用户入口走 frontend nginx → `http://<host>:8080/`**。nginx 同源托管 `dist/` 并反代后端：`/api/v1/`、`/health`、`/health/ready`、`/health/config`、`/admin/ops/` → `backend:8000`（Docker DNS）；SPA 路由 fallback 到 `index.html`。前端 bundle 用同源相对路径（不烙后端内网 URL）。
- 后端宿主端口 **8001** 仅供**调试**（容器内 8000），生产正式访问不走它；如需收紧可在生产移除该映射。
- 前端镜像（`Dockerfile.frontend` + `deploy/nginx.conf`）多阶段构建：Node 阶段 `npm ci && npm run build`，nginx 阶段托管 `dist/`；**不复制 `backend/.env`、不烙任何密钥**（见根 `.dockerignore`，已整目录排除 `backend/` 与所有 `.env`）。
- 迁移由专设 `migrate` 服务执行，backend/worker/beat 依赖其成功完成后启动——无需手动 `alembic upgrade`、不并发迁移。
- 冒烟：`GET /health`（活性）、`GET /health/ready`（DB/Redis 就绪）、`GET /health/config`（安全配置诊断，无密钥）、`GET /admin/ops/summary`（admin 运营计数）。
- **安全烟测脚本（PBC-17）**：`python scripts/production_smoke.py --base-url http://<host>:<port> [--fail-on-production-blockers] [--json]`。纯标准库、**不读 `.env`、不调 `docker compose config`**；只打印端点名 / HTTP status / `/health/config` 白名单安全字段（`production_ready` / `production_blockers` / `missing_config` 项名），绝不打印响应正文 / cookie / 密钥 / 连接串。`/health/config` 的 `production_ready` 为 true 仅表示「`APP_ENV=prod` 且无代码级硬阻断项（如 eager worker、insecure cookie、缺关键配置项名）」。
- **生产 cookie（PBC-17）**：`APP_ENV=prod` 时会话 / OAuth state cookie 强制 `Secure`（HTTPS-only）；故必须经真实 HTTPS/TLS 反代访问，纯 http 入口下 cookie 不回送。
- **登录失败风控（PBC-18）**：密码登录失败按不可逆 `identifier_hash` / `ip_hash` 短时锁定 / 限流，达阈值后不再消耗 PBKDF2；用户态错误统一为「邮箱或密码错误」，不区分账号是否存在 / 锁定。`APP_ENV=prod` 必须配置 `AUTH_ATTEMPT_HASH_SECRET`（缺失 → `/health/config` blocker）；阈值见 `backend/.env.example`。审计 / attempts 只含不可逆 hash 前缀 + 计数 + 原因码，**不含 raw email / password / token / 原始 IP**。
- **企微身份生命周期同步（PBC-22）**：企微 OAuth 登录在建平台会话前核验企微成员有效性——成员被禁用 / 删除 / 未激活时 fail-closed（不建会话、停用平台用户、撤销会话、安全审计）；上游故障 fail-closed 但不误改状态。admin-only `POST /admin/ops/wecom-identity/reconcile`（CSRF 保护）可对账绑定用户并停用失效成员；`/admin/people` 详情提供「企微身份对账」按钮。仅安全计数 / 归一状态，不暴露 wecom_user_id / 通讯录档案 / token / 上游 errmsg。复用现有企微凭证，无新配置。**未做** 自动建用户 / 组织树同步 / 通讯录展示。
- **会话撤销（PBC-21）**：账号停用、改密、或 admin 强制下线时，平台会话（`kap_session`）会被撤销（标记 `user_sessions.revoked_at`，不删行）。admin-only `GET/POST /admin/ops/sessions/users/{id}[/revoke]` 可查看安全会话元数据（仅 `session_id`/login_method/时间/撤销态，无 token/cookie/IP/device）并强制下线；`POST /admin/people/{id}/status` 停用用户联动撤销其会话。撤销 POST 受 PBC-19 CSRF 保护。**未做** MFA / 找回密码 / 设备管理 UI / 多设备会话产品。
- **登录风控运维（PBC-20）**：admin-only `/admin/auth-security` 面板（`GET/POST /admin/ops/auth-security[/unlock]`）展示近期 failed/locked/rate_limited/success 安全聚合（仅不可逆 hash 前缀 + 安全用户元数据,无 raw email/IP/hash/token）,并可手动解除某账号的 identifier 短时锁定（写 `unlocked` reset anchor + `auth.lockout_unlocked` 审计,不绕过密码、不建会话、不重置 IP 限流）。解锁 POST 受 PBC-19 CSRF 保护。boss/director/consultant/pm 一律 403。
- **CSRF 防护（PBC-19）**：cookie 会话下的 unsafe 请求（POST/PUT/PATCH/DELETE）须带 `X-CSRF-Token`（经 `GET /api/v1/auth/csrf` 获取，签名+过期+绑定 session 的无状态 token）；缺/无效/过期 → 安全 403，在业务 handler 前 fail-closed。dev `X-Dev-User-Id`、`Authorization: Bearer`（外部 Agent/Dify）、OAuth callback（GET）不受影响；`/auth/login` 豁免、`/auth/logout` 受保护。`APP_ENV=prod` 必须配置 `CSRF_TOKEN_SECRET`（缺失 → `/health/config` blocker）。前端自动获取/缓存（仅内存）/附带/失败重试一次。CSRF 失败不写审计（依赖 HTTP logs/metrics）。**未做** MFA / 找回密码 / 密码轮换 / 多设备会话。
- 真实外部集成（WeKnora / LLM / 企微 / ONLYOFFICE）经 env 注入启用，**真实密钥不入仓库**；字段清单见 `backend/.env.example` 与 `backend/README.md` §R8 / §PBC-17。
- **PBC-17 仅关闭代码级守卫 / 烟测 / trace 回归**；真实域名、HTTPS/TLS 证书、WeCom trusted callback domain、真实 secret 注入、镜像重建、DNS/反代、对象存储 / 指标系统等仍需运维实际执行。**未做** K8s/Helm/云密钥管理/真实公网部署。
- **部署执行文档（PBC-23）**：上线前的可执行手册 / 安全配置清单 / live smoke 清单见 `docs/deployment/`：
  - [`PRODUCTION_DEPLOYMENT_RUNBOOK.md`](docs/deployment/PRODUCTION_DEPLOYMENT_RUNBOOK.md) — 上线前准备 → 部署顺序 → 域名/TLS → 验证 → 回滚排障；
  - [`PRODUCTION_SECRET_CHECKLIST.md`](docs/deployment/PRODUCTION_SECRET_CHECKLIST.md) — **只列配置项名 + blocker/warning 归类**，无任何值；
  - [`LIVE_SMOKE_CHECKLIST.md`](docs/deployment/LIVE_SMOKE_CHECKLIST.md) — 健康/鉴权/CSRF/上传/索引/搜索/权限/WeCom/ONLYOFFICE 最小验证。
  - **边界**：PBC-23 交付的是 **repo 内的部署文档 + live smoke 清单 + 安全配置清单**；真实公网域名、TLS 证书、云密钥注入、DNS、对象存储、云监控、镜像推送仍是实际运维动作，**本仓库不声称已完成真实公网部署**。

### ⚠️ `docker compose config` 会展开 `.env` 密钥——勿贴完整输出

`backend`/`worker`/`beat`/`migrate` 通过 `env_file: ./backend/.env` 加载环境（本地联调需要它，**不要移除**）。但 `docker compose config` 会把 `env_file` 的值（含 `WEKNORA_API_KEY` / `LLM_API_KEY` / `WECOM_APP_SECRET` / `ONLYOFFICE_JWT_SECRET` 等）**明文展开**到输出里。

- 含真实密钥时，**不要**把 `docker compose config` 的完整输出贴进 issue / 完成报告 / 截图 / 聊天。
- 验证 compose **结构**（服务 / 卷 / 存储挂载）时，优先用下方脱敏方式，或临时换一份示例 `.env`（占位值）再跑。

**安全验证存储结构（不展开 `.env`、不打印任何 `*_KEY`/`*_SECRET`/token/连接串）**：

```powershell
# STORAGE_ROOT 与共享卷挂载都写在 docker-compose.yml（YAML 锚点 / volumes），不在 .env——
# 直接读 compose 文件即可验证，无需 `docker compose config`、不触碰密钥。
# 1) backend 与 worker 是否都挂载共享卷 upload_storage:/data/uploads（应命中两行：backend + worker）
Select-String -Path docker-compose.yml -Pattern 'upload_storage:/data/uploads'
# 2) 共享运行时是否把 STORAGE_ROOT 指向 /data/uploads（来自 &backend-env 锚点，backend/worker 共用）
Select-String -Path docker-compose.yml -Pattern 'STORAGE_ROOT:\s*/data/uploads'
# 3) 仅看服务名 / 卷名（这两个子命令不展开 env_file 值）
docker compose config --services
docker compose config --volumes
```

上述命令只匹配 `upload_storage:/data/uploads` 与 `STORAGE_ROOT: /data/uploads` 两个存储标记，绝不会打印任何密钥；`--services` / `--volumes` 只列名称，不展开环境变量。

## DDD V3 对齐点

以下功能点对齐 DDD V3 设计文档：

- **路径A / 路径B 资产化模型**：`/upload` 统一入口，企微微盘 Agent 自动检测（路径A）与本地上传（路径B）共享 AI 提取 → 人工校正 → 入库/审核分流
- **AI 建议 + 人工确认**：AI 推荐目标知识库、可见性、置信度；人工确认或修正后提交
- **个人/项目/公司知识库分层**：目标知识库三选一，分流逻辑基于置信度、敏感级别与项目策略
- **项目/公司审核分流**：项目知识可直接入库或进项目审核；公司知识进入公司级审核
- **P6 模型切换**：项目看板 Q&A 支持顾问切换问答模型，体现"模型选择 + 来源引用 + 可追溯"叙事
- **审计日志** `/admin/audit`：操作/异常/登录三类日志，trace_id 串联调用链，异常可标记处理
- **告警设置** `/admin/alert-settings`：三级告警规则、通知渠道、防重复策略、接收人管理
- **trace_id 审计追踪**：已实现 API 与审计 / 生命周期 / Agent 记录携带 trace_id，可关联本地后端已实现的调用链；经 Celery / WeKnora / 向量存储的真实跨服务传播为延后项、尚未实现
- **人员/多角色/项目人员模型** `/admin/people`：五角色权限边界、多角色行为、项目人员关系
- **Q&A 模型选择器**：项目看板支持系统默认 / DeepSeek-R1 / 通义千问切换

## 设计规范

- 品牌色系：`--color-primary` #1F2D75 / `--color-accent-1` #4A6FA5 / `--color-gold` #C9A962
- 所有颜色通过 CSS 自定义属性（Design Tokens）管理，业务样式中不使用裸 hex 值
- 状态色：success（绿）/ warning（金）/ danger（红）/ info（蓝）各有前景和背景两个 token
- 页面布局：topbar + sidebar + main content，sidebar 可容纳 8+ 导航项
- 交互页面使用 useState/useMemo/useCallback 管理本地状态，不引入状态管理库

## 目录结构

```
src/
  main.tsx            # 入口
  App.tsx             # 路由配置
  layouts/
    AppLayout.tsx     # 应用壳：顶部栏 + 侧边栏（业务功能 / 管理后台分组）+ 主内容区
    AppLayout.css     # 全局样式 + 页面样式（Design Tokens 管理）
  pages/              # 各路由页面（13 个核心页面）
  api/
    client.ts         # 后端 API client（fetch 封装 + DTO→VM 转换；页面主数据来自真实后端）
  types/              # 后端 DTO / 前端 VM 类型定义
```
