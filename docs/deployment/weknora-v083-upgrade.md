# WeKnora v0.7.1 → v0.8.3：兼容适配与升级门禁

本说明只覆盖 KAP 接入及已有 WeKnora 数据的升级，不是可直接粘贴执行的生产部署脚本。
当前尚未完成新版容器实测、旧数据隔离恢复或生产升级；协议 mock 测试不替代这些验收。

## 固定的核对基线

- 现有部署：WeKnora app / UI / DocReader v0.7.1；ParadeDB v0.22.2-pg17；Redis 7.0-alpine。
- 目标稳定版：v0.8.3，2026-10-14 发布，源码提交
  `3e22822c1d2397be730c458c7539d0eb8c113a24`。
- 官方目标 Compose 的 ParadeDB 为 v0.25.11-pg17。PG 主版本仍为 17，不改为 PG18。
- 镜像部署必须使用明确版本并记录实际 digest，不使用浮动 `latest`。
- 现有服务地址、租户、库/资料映射、embedding 模型和向量维度保持不变。

## KAP 兼容矩阵

| 调用 | 适配/核对结果 | 升级后的验收要求 |
| --- | --- | --- |
| POST `/knowledge-search` | v0.8.3 用 `query`、`knowledge_base_ids`、`knowledge_ids`、`match_count`；KAP 不再发送 `top_k` | 相同请求的实际候选、指定资料过滤、空范围、拒绝访问 |
| POST `/knowledge-bases/:id/hybrid-search` | 用 `query_text`、`match_count`；两个已核对版本均注册 POST，保留阈值 0 的语义 | 指定库、关键词/向量阈值、错误不降级为更宽范围 |
| 建库、上传、查询/删除资料、分页 | 已检查的主要路由与字段仍存在，未据此宣称运行通过 | 新建隔离测试库、上传、索引完成、分页、重试/重复文件、清理测试资料 |
| 初始化、KB 模型配置 | 必填初始化对象仍为 `llm`、`embedding`、`documentSplitting`；更新仍要求 `llmModelId` | 使用测试库验证；不得重初始化或更换真实资料 embedding |
| 模型与密钥管理 | 路由仍在，凭据仍由专用 PUT 子资源管理；需核验 API key 实际能力与库范围 | 只读、配置和测试模型操作分别验证，不因 403 自动扩大权限 |
| 响应解析 | 核心 `data`、`knowledge_id`、`content`、`score` 等仍在；新增 `meta` 不直接传给业务响应 | 权限过滤、脱敏、引用、结果去重和排名样本重新验收 |

v0.7.1 的 `/knowledge-search` 请求结构没有逐请求数量字段。
它会忽略 `match_count` 并继续使用自身检索配置。因此：

- KAP 适配可提前部署，但不能宣称旧底座已按 100 个候选执行。
- 不做错误重试到无范围搜索，也不把所有查询改为遍历资料列表。
- 不加入特定资料 ID、账号、题目或业务同义词的硬编码。
- 不将扩大候选数量等同于提高正确率；口语题与无依据拒答仍需实测。

## 升级前必须具备的材料

1. 确认 WeKnora 自己的 Compose 工作目录、覆盖文件、启用 profiles、端口、网络及数据卷。
   不能把 KAP 的 `/data/kap/repo` 或 `-p kap` 当作 WeKnora 的部署参数。
2. 确认 WeKnora 的真实迁移版本、PG 版本、已安装扩展与可用扩展版本，以及其他写入方。
   只收集必要状态；不把环境变量、API key、模型密钥或完整 inspect 输出贴入日志。
3. 单独备份 WeKnora 数据库、角色、文档文件/对象存储，以及恢复所需配置和加密材料。
   KAP 的数据库备份不能代替 WeKnora 的备份。备份保存在数据卷之外，限制权限。
4. 记录现有镜像 digest、卷、配置和必要的基线计数、代表性检索结果。
5. 确认隔离演练环境。未获环境确认前，不自行创建服务器、恢复数据库或启动生产迁移。

## 隔离演练顺序

1. 将 WeKnora 自己的备份恢复到独立卷/数据库；复制必要文件，使用独立网络及端口。
   禁止把测试 app 指向生产 DB、文件目录、Redis 队列或可写的生产对象存储。
2. 关闭隔离环境外部同步、定时导入及真实通知等写入来源。
3. 按官方顺序升级数据库镜像和扩展，再使用固定版本 app / UI / DocReader。
   不直接用新版 Compose 覆盖原配置，不自动启用沙箱、MCP、数据源等无关服务。
4. 对照迁移状态和基线计数，验证已有库、资料、模型关联、文件取件、关键词和向量检索。
5. 通过 KAP 验证上传 → 解析 → 索引 → 检索 → 问答引用与权限隔离；保留无依据拒答测试。
   测试只使用虚构验收资料，不更改真实用户角色或真实业务资料。
6. 实际演练恢复旧备份到另一个独立卷并配合旧镜像启动，核对检索与文件读取。
7. 保存结果、耗时、磁盘需求、失败点后，才制定针对真实服务器的升级脚本和维护窗口。

## ParadeDB 的特殊风险

官方 v0.8.3 提供 0.22.x → 0.25.11（PG17）的存量升级说明。
镜像中的扩展二进制与数据库中的扩展 catalog 必须一致；不一致可能造成数据库进程崩溃。
安装新镜像后，不能假设已经执行过的应用迁移会自动重新执行扩展更新。
其他装有扩展的数据库也需要按实际情况核对，不能只检查 WeKnora 主库。

保留原卷不等于保留可回滚副本。扩展 SQL 及 WAL 格式变更后，
**仅把镜像切回 v0.22.2 不能作为回滚方案**。必须用升级前备份/快照恢复到独立卷，
再配合旧镜像。禁止 `down -v`、删除原数据卷或覆盖生产库来做演练。

## 交付与当前限制

- 本批 KAP 代码只改客户端检索协议和空范围保护，不升级任何服务或依赖，不改权限规则。
- 单元测试使用 httpx MockTransport，断言实际 HTTP 方法、字段、范围、错误及响应规整。
- 关联回归和全量回归必须记录实际结果，不能把未执行的 Docker/PG 测试记为通过。
- 未完成隔离升级和回滚前，不提供一条直接替换生产镜像的快捷命令。

### 2026-10-21 本地验证记录

- 分支：`codex/weknora-083-compat`，独立于原文授权管理 PR。
- 24 项 HTTP 协议用例通过；与检索 API、失效资料过滤、脱敏合计 97 项关联回归通过。
- 后端全量 `pytest tests -q` 终态退出码为 0，无失败；真实 PostgreSQL 行锁用例因
  缺少专用 `KAP_TEST_POSTGRES_URL` 跳过，不计通过。运行期间补充的两个测试只改测试文件，
  已包含在上述 24 / 97 项单独回归中，业务代码在全量启动后未再修改。
- Ruff 全库检查通过，451 个 Python 文件格式检查通过。
- mypy 按 Linux 部署目标检查 302 个源文件通过；Windows 默认平台检查有既有
  `resource.setrlimit` / `os.killpg` 等平台接口错误，未修改这些无关代码来掩盖错误。
- 发布说明 JSON 可解析，`git diff --check` 通过。本节记录提交前验证，不代表已部署。
- 后续补验版本替代、维护复核、上传持久化与流式上传四模块，72 项通过；核对了过期基线
  拒绝后当前资料不被归档、提交结果不明保留文件并可恢复、到期提醒去重且不自动归档。
  这些仍是本地隔离测试，不替代真实 PG 锁语义及线上跨身份验收。
- 本机 Docker Linux 引擎不可用；用户选择先完成本地适配、暂缓隔离演练。
  真实 v0.8.3 API、迁移、回滚及口语检索效果均仍未验收。

## 上游依据（固定版本）

- [v0.8.3 发布](https://github.com/Tencent/WeKnora/releases/tag/v0.8.3)
- [搜索请求](https://github.com/Tencent/WeKnora/blob/v0.8.3/internal/handler/session/types.go)
- [混合检索参数](https://github.com/Tencent/WeKnora/blob/v0.8.3/internal/types/search.go)
- [知识库路由](https://github.com/Tencent/WeKnora/blob/v0.8.3/internal/router/routes_knowledge.go)
- [模型与初始化路由](https://github.com/Tencent/WeKnora/blob/v0.8.3/internal/router/routes_infra.go)
- [ParadeDB 存量升级与回滚](https://github.com/Tencent/WeKnora/blob/v0.8.3/website-docs/01-getting-started/06-paradedb-upgrade.md)
