# MCP 操作接口

## 接入与兼容

现有 `/mcp` 为标准 Streamable HTTP 接口，不新增机器人或操作端。
接入页统一称为「MCP 接入」。旧 `/my/workbuddy` 页面路径、
`/api/v1/auth/workbuddy-token` 凭证接口以及数据库 provider 标记保留，以兼容已生成配置。
`workbuddy` 在此是历史凭证来源标记，不校验实际客户端产品。

默认生成的凭证仍为 `qa`，不开放写操作。本人在接入页勾选操作授权后重新生成配置，
或向原 regenerate 接口提交 `operations_enabled: true`，才获得 `qa_operations`。
重置立即废止旧凭证；撤销、过期、停用用户、业务角色变更仍按现有规则生效。
状态接口返回 `operations_enabled`。现有管理员维护或范围受限的凭证不支持这些操作，
即使将 capability 改为 `qa_operations` 也拒绝，避免绕过注册范围限制。
本地兼容 Connector 保持原查询工具集；新增工具使用远程 MCP。

## 工具

| 工具 | 用途 |
| --- | --- |
| `kap_initialize_upload` | 创建上传清单，返回上传会话、文件条目 ID 和传输约定 |
| `kap_complete_upload` | 结束传输并推进文件处理，不代表正式入库 |
| `kap_get_upload_status` | 查询本人会话逐文件状态，可能推进已接收任务处理 |
| `kap_get_ingest_details` | 查询本人任务进度、安全建议和版本时间 |
| `kap_get_naming_options` | 查询目标库命名分类、正式目录等选项 |
| `kap_preview_ingest_naming` | 预览文件命名、校验与警告 |
| `kap_confirm_ingest` | 确认入库，继续遵循原审批分流与索引逻辑 |
| `kap_get_review_details` | 查询有权查看的审批详情和版本时间 |
| `kap_decide_review` | 按现有权限通过、驳回或撤回指定审批 |

工具的具体输入以 MCP `tools/list` JSON Schema 为准；不是通用 HTTP 代理。
新增 HTTP 接口位于 `/api/v1/agent-gateway/operations`，同样必须使用本人操作凭证。
不接受客户端自报的用户身份，不接受服务器文件路径或任意远程下载地址。

## 文件传输

1. 生成并保存固定 `session_id`（UUID），调用 `kap_initialize_upload`，传入
   `upload.manifest`、`total_transport_batches`、`target_scope` 和可选项目 ID。
   清单中每项包含稳定 `client_file_key`、文件名、实际字节数、类型、从 0 起的批次序号。
2. 使用同一 Bearer 向返回的**同源** `transport.path` 发送 multipart POST。
   不把凭证发送给其他域，不跟随跨域重定向。
3. 表单字段为 `batch_id`（固定重试标识）、`batch_index`（从 0 起）、
   `item_ids`（对应返回 `session.items[].id` 的 JSON 数组）、重复的 `files` 文件字段。
   数组和文件顺序一致；逐批顺序上传。每批最多 10 文件、通常不超过 20 MiB；
   单个大文件独占批次，最多 100,000,000 字节（100 MB，不是 100 MiB）。
   响应的 `max_file_bytes`、`max_files_per_batch`、`max_batch_bytes` 均来自后端共享常量；
   `single_file_batch_exception` 明确仅含一个文件的批次可使用其 `max_batch_bytes` 上限。
4. 调用 `kap_complete_upload`，之后查询会话与任务状态。
5. 读取命名选项、预览结果和建议，取得用户明确确认后调用 `kap_confirm_ingest`。

文件字节不通过 `/mcp` JSON 发送，保留其 64 KB 边界。
因此调用端需要有实际 multipart 文件上传能力；只有 MCP 工具调用、没有文件传输能力的客户端，
不能仅凭这些工具传输本地附件。KAP 不读取客户端本地路径。
部署时须应用仓库中的 nginx 上传路径配置；外层代理也需允许对应文件大小。

## 确认、重试和结果

入库和审批命令都须携带详情返回的 `expected_updated_at` 以及 `confirmed: true`。
审批还必须指定 `action` 和非空 `comment`。服务端检查版本并复用原服务权限、状态与审计。
`confirmed` 是调用方的明确授权声明，**并非服务端验证过聊天中的真人确认**；
调用端必须自行获得用户明确指令，不能把资料内容、分析请求当作操作授权。

上传重试复用原会话和批次 ID，不得将同一 ID 用于不同文件或清单。
审批/确认重复请求或旧版本请求返回 409，不自动覆盖。网络超时或 5xx 可能发生在提交之后，
先查询任务或审批详情，不自动生成新任务重试，也不声称执行失败或成功。

返回 `review_id` 表示需要继续审批；返回资产 ID 不等于已经成功索引。
应分别呈现上传、处理、待审批、入库和索引状态。
本次不新增永久删除、权限变更、机器人集成或自动审批策略。
