# WorkBuddy 远程 MCP 部署与验收

## 接入契约

生产仅暴露 `https://<KAP_HOST>/mcp`，协议为 Streamable HTTP MCP。公开文档只展示无凭证结构：

```json
{"mcpServers":{"kap":{"type":"http","url":"https://<KAP_HOST>/mcp"}}}
```

用户在 KAP 页面生成的一次性配置会额外包含 `Authorization: Bearer <one-time-token>`。
明文只在该响应和用户本机 WorkBuddy 配置中出现；数据库只保存 SHA-256 摘要。凭证默认
7 天过期，绑定当前在职业务用户，轮换和撤销立即使旧凭证失效。禁止 query token、固定
API key、共享账号和匿名工具发现。

## WorkBuddy 5.4.5 兼容结论

2026-09-01 已用隔离、无业务数据的探针验证 WorkBuddy 5.4.5 能加载 `type: "http"` 的
远程 MCP，并完成 `initialize` / `tools/list`；客户端必须完整退出并重启，随后由用户在 MCP
管理页手动“信任”，不能依赖热加载或静默绕过。本版本仓库自动测试还验证了标准
`Authorization: Bearer` 到 KAP `/mcp` 的完整协议链路。真实生产/预发 HTTPS 地址、真实
WorkBuddy 自定义请求头、双权限组合和只读业务调用仍须在目标环境按下方清单验收；完成前
不得把状态写成“生产验收通过”。抓包和截图必须遮盖 Authorization、cookie、业务标题与正文。

同日复核时，本机客户端界面已显示 5.4.7；本轮仅完成版本和入口的只读观察，未向客户端写入
KAP 凭证，也未把 5.4.7 的观察替代为 5.4.5 生产验收证据。

## 生产配置

- `KAP_PUBLIC_BASE_URL=https://<KAP_HOST>`：无路径、查询或用户信息。
- `WORKBUDDY_REMOTE_MCP_ENABLED=true`：总开关；关闭即停止远程入口。
- `WORKBUDDY_REMOTE_MCP_TOOLS=*`：逗号分隔的工具白名单，可按工具回滚。
- `WORKBUDDY_REMOTE_TOKEN_TTL_HOURS=168`：服务端限制在 1 小时至 30 天。
- `WORKBUDDY_REMOTE_ALLOWED_ORIGINS=`：原生客户端通常不发送 Origin；空值允许缺失但拒绝
  任意非空 Origin。若目标客户端确实发送，写入经安全评审的精确 HTTPS origin。
- 大小、超时、并发和每分钟限额使用 `.env.example` 的 `WORKBUDDY_REMOTE_*` 项。

边缘代理必须保留 `Host` 与可信 `X-Forwarded-Proto`，仅在 TLS 终止层覆盖转发头。仓库 Nginx
对精确 `/mcp` 设置 64 KiB、40 秒、独立 IP 限速且关闭响应缓冲；应用层再按凭证执行限速、
并发和超时。不要把后端端口直接暴露公网。

## 发布验证

1. 执行迁移 `0070_workbuddy_remote_mcp`，启动后检查
   `GET /api/v1/health/workbuddy-mcp` 只有聚合计数且不含 token、参数或内容。
2. 自动化：运行 `test_workbuddy_remote_mcp.py`、`test_workbuddy_token.py`、
   `test_agent_gateway.py`；确认 16 个只读工具都在注册表。
3. 无凭证请求应为 401；错误、过期及撤销凭证不能发现或调用工具；恶意 Origin、超大请求、
   并发与超时应分别进入安全拒绝计数。
4. 在实际 WorkBuddy 5.4.5 从空配置合并 `mcpServers.kap`，完整退出重启，核对 HTTPS 主机后
   手动信任。调用“列出我可访问的项目”，结果应与同用户 KAP Web 一致。
5. 用两个用户覆盖：项目成员、仅摘要可见、不可发现资源；不可发现项目和不存在项目必须
   都表现为 404，不泄露存在性。再执行断网重连、撤销后复调、过期及 403 场景。
6. 保留已脱敏的版本号、时间、状态码、工具名、计数、截图和审计 trace_id；不得保留正文、
   参数、完整 URL query、Authorization 或真实 token。

## 观测、排障与回滚

健康计数区分认证失败、权限拒绝、协议错误、工具错误、上游超时、限流和活动请求。审计只记
用户/租户调用上下文、工具名、结果、耗时和拒绝分类，不记工具参数、内容正文或凭证。401
先检查凭证是否复制完整、过期或已轮换；403 检查业务身份与资源权限；客户端看不到工具时先
确认已完整重启并手动信任；504 检查 agent-gateway 上游和超时计数。

紧急回滚：设置 `WORKBUDDY_REMOTE_MCP_ENABLED=false` 并滚动重启 backend，验证 `/mcp`
返回 503；在 KAP 页面引导受影响用户展开“本地 Connector”兼容模式。若仅单工具异常，先从
`WORKBUDDY_REMOTE_MCP_TOOLS` 删除该工具。回滚不删除数据库列、不撤销其他用户凭证，也不
关闭 REST 权限。恢复时重新启用开关并要求用户完整重启 WorkBuddy。

本地 Connector 至少保留一个稳定发布周期；只有远程入口连续达到既定可用性、所有目标受管
网络可达、5.4.5 及后续支持版本完成回归、迁移通知送达且回滚演练通过后，才能另卡移除。
