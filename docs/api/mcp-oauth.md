# MCP：凭证与 OAuth 两种接入

同一套工具支持两条认证路径，不针对任何用户、姓名、角色或客户端硬编码。

- WorkBuddy／Codex 继续使用已有 Bearer 配置。OAuth 不覆盖或重置自助凭证。
- 云端 OAuth 入口填写平台 MCP 地址，选择 OAuth，通过 KAP 登录并明确同意授权。
- 不开放匿名知识查询；认证发现元信息可以公开，但不含账号、资料或凭证。

## 授权协议

使用 MCP Python SDK 的授权端点、DCR 动态客户端注册、授权码、S256 PKCE 和回调校验。
公开客户端使用 token_endpoint_auth_method=none；保密客户端支持
client_secret_post／client_secret_basic，SDK 处理客户端认证。
不实现外部身份提供商代理，不抓取任意客户端元信息 URL，不支持 CIMD。
客户端使用发现元信息中的动态注册端点（DCR）。

授权请求必须指定当前平台 /mcp 的完整 resource。
注册回调必须为 HTTPS 或 HTTP loopback，禁止用户信息、片段及脚本协议。
应用名称由客户端自行提供，用户确认页同时展示回调域名，不把名称当作认证标识。

- qa：查询权限范围内的知识、项目及待办。
- qa_operations：允许调用上传、入库确认和审批接口，必须同时申请 qa，
  用户必须明确勾选；每次业务操作仍需授权，并受现有业务权限约束。
- 仅有效业务用户可以同意授权；每次调用与刷新重新检查用户状态和业务权限。
- 授权请求 10 分钟有效，授权码 5 分钟有效且只能使用一次。
- 客户端注册及注册密钥最长一年有效，到期需重新注册客户端。
- 访问令牌 1 小时有效，授权及刷新链最长 30 天；到期重新授权。
- 每次刷新轮换两种令牌；旧刷新令牌重放会撤销整个授权。
- 授权状态持久化到数据库，跨进程、重启仍有效。授权码、刷新令牌、访问令牌只存哈希；
  注册客户端密钥使用独立 Fernet 密钥加密保存。
- 用户在「MCP 接入 → 已授权应用」撤销本人授权；SDK /revoke 也支持 OAuth 撤销。
- 用户确认和撤销 API 沿用网页登录及 CSRF 保护，无 Cookie 的协议端点不依赖浏览器会话。

## 生产部署

默认关闭新 OAuth，保留凭证接入。备份数据库并迁移至 0078_mcp_oauth，
在受保护的 backend/.env 配置：

    MCP_OAUTH_ENABLED=true
    MCP_OAUTH_CLIENT_ENCRYPTION_KEY=<独立生成的 Fernet 密钥>

可在服务器执行以下命令生成密钥，不要把结果发到聊天、提交 Git 或截图：

    docker compose -p kap -f docker-compose.yml -f docker-compose.prod.yml exec -T backend python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'

所有后端实例使用同一个稳定密钥，不复用内容模型密钥，不在升级时自动重新生成。
备份时同时保护配置密钥，否则客户端密钥密文不能恢复。
开启 OAuth 但缺少有效密钥时启动失败，不降级明文存储。
生产 KAP_PUBLIC_BASE_URL 必须为真实 HTTPS origin。
通过现有发布脚本构建、迁移、更新并登记版本，不绕过发布身份流程。

前端 Nginx 已新增以下代理路径，不能回退到 index.html：

    /.well-known/oauth-protected-resource/mcp
    /.well-known/oauth-authorization-server
    /authorize
    /register
    /token
    /revoke

宿主机 Nginx 也必须让这些路径进入平台前端代理。
若有覆盖这些路径的自定义 location，需为上述确切路径单独转发，
不要修改其他站点或 ACME 验证路径。升级后检查内容，不能仅看 HTTP 200。
协议请求最多 64 KiB、查询参数最多 8 KiB、读取超时 10 秒；应用层和 Nginx 有频率限制。

## 验收

1. 两个发现地址返回 JSON，issuer 和协议端点与公开 origin 一致。
2. 真实 ChatGPT 选择 OAuth，可进入 KAP 登录与授权页，再返回原客户端。
3. 写权限不默认勾选；拒绝授权返回 access_denied，不发令牌。
4. 重复授权码、错误 PKCE、非法回调、错误 resource、越权撤销被拒。
5. 刷新后旧访问令牌失效，旧刷新令牌重放撤销授权。
6. 用户停用或失去业务身份后，调用和刷新被拒。
7. 权限范围外的知识不可读；只读授权无法写入。
8. 原 WorkBuddy／Codex Bearer 仍可用，不被 OAuth 重置。
9. 不粘贴 Token、client secret、授权码、刷新令牌或带敏感查询串的日志。

本地 SDK 测试不等同于真实 ChatGPT 账号和生产代理验收。

## 上传提交结果不明确的恢复

任务构造、flush、审计等提交前失败可以回滚并清理本次字节。
一旦开始 COMMIT，异常可能只是确认丢失，必须保留字节，
并记录 ingest_upload_commit_outcome_unknown 及任务 ID。
当前连接回滚不能证明服务器未提交，不能据此删除文件。

已提交但未入队的 processing/upload_saved 任务纳入现有有限重试扫描。
若数据库没有对应任务，保留文件可能是孤立对象；本次不盲删，
应由受控存储对账确认无引用后再清理。
遇到上传结果不明确时先查询本人任务，不立即重复上传。
