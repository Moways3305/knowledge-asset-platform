# WorkBuddy Connector 发布与部署（兼容模式）

> 新接入默认使用 KAP 远程 HTTPS MCP。本文只维护无法直连远程端点的受管设备兼容路径；
> 淘汰条件与回滚口径见 [`WORKBUDDY_REMOTE_MCP.md`](./WORKBUDDY_REMOTE_MCP.md)。

KAP WorkBuddy Connector 是共享安装程序，不包含用户身份或凭证。个人 `KAP_AGENT_TOKEN`
只在用户主动生成配置的那一次响应中出现，并由用户导入自己的 WorkBuddy 配置。

## 构建目标

发布工作流必须同时产生：

| 平台 | 架构 | 安装形式 |
| --- | --- | --- |
| Windows 10/11 | x64 | Inno Setup 安装程序 |
| macOS | Apple Silicon / arm64 | PKG |
| macOS | Intel / x64 | PKG |

可执行程序由 PyInstaller 打包，包含 Python 运行时、`workbuddy_mcp` 与依赖。最终用户不需要
安装 Python、pip 或 MCP 包。

## 发布渠道

在 GitHub Actions 手动运行 `WorkBuddy Connector Release`，输入语义化版本号并选择渠道：

- `internal`：生成未签名企业内部版。只有生产管理员显式开启服务器级开关后，KAP 才允许
  向在职业务用户分发；页面会明确提示仅限公司授权设备，操作系统可能要求确认来源。
- `production`：任何目标缺失、Windows 签名失败、macOS Developer ID 签名失败、
  notarization 失败或 ticket 无法 staple 时，工作流失败且不生成生产清单。

生产发布所需 secrets：

- Windows：`WINDOWS_SIGNING_PFX_BASE64`、`WINDOWS_SIGNING_PFX_PASSWORD`
- macOS 证书：`APPLE_CERTIFICATES_P12_BASE64`、`APPLE_CERTIFICATES_PASSWORD`、
  `APPLE_KEYCHAIN_PASSWORD`
- macOS 身份：`APPLE_DEVELOPER_ID_APPLICATION`、`APPLE_DEVELOPER_ID_INSTALLER`
- Apple 公证：`APPLE_ID`、`APPLE_TEAM_ID`、`APPLE_APP_PASSWORD`

工作流不得输出这些值。macOS 使用 hardened runtime、`notarytool --wait`、ticket stapling、
`spctl` 与 `pkgutil` 校验；Windows 使用 Authenticode 时间戳签名和 `signtool verify`。
生产签名作业只上传中间产物，不自行签发可信声明。固定引用 `@main` 的独立 reusable
trusted builder 会在隔离 job 中重新对安装包本体执行 `signtool`、`pkgutil`、`stapler`
和 `spctl`；复验成功后才通过 GitHub Sigstore 为安装包签发 attestation，并为完整生产
manifest 签发 attestation。清单中的 `signed`、`notarized` 字段只是展示与一致性元数据，
不能替代 attestation。生产仓库必须对 `main` 和 trusted builder 文件启用强制审查与分支
保护；发布 workflow 的候选分支不能替换受信 builder，也不能自行签发部署端接受的证明。
生产渠道只能从 `refs/heads/main` 运行；部署校验同时固定 reusable workflow 路径、其
`@refs/heads/main` 证书身份、发布源分支和 GitHub-hosted runner。

## 部署到 KAP

### 公网连接 origin

后端必须由部署配置显式注入 `KAP_PUBLIC_BASE_URL`。该值只允许是规范 origin，例如
`https://knowledge.example.com`：不得包含用户名、密码、path、query 或 fragment，尾部 `/`
会被移除。生产 `APP_ENV=prod` 下缺失或不是 HTTPS 时，WorkBuddy 配置生成返回安全的 503，
且不会创建或轮换 token。配置生成不读取客户端 `Host`、`Forwarded`、
`X-Forwarded-Proto` 或 `request.base_url`。

```bash
KAP_PUBLIC_BASE_URL=https://<public-kap-host>
```

连接器默认拒绝重定向；HTTP 降级、跨域跳转、HTML 错误页、无效 JSON、TLS 与网络异常均收口
为稳定的 MCP 错误对象，不把 URL、响应正文或连接细节写入 stdio 协议。

生产 Compose 必须同时使用基础文件和生产覆盖文件：

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.prod.yml config --services
```

不要输出完整的 `docker compose config`，它会展开 `env_file` 中的敏感值。覆盖文件只给
`backend` 增加以下边界：

- 宿主机 `/data/kap/workbuddy-connectors` 挂载到容器
  `/data/workbuddy-connectors:ro`；
- `WORKBUDDY_CONNECTOR_ARTIFACT_ROOT=/data/workbuddy-connectors`；
- `WORKBUDDY_CONNECTOR_ALLOW_INTERNAL` 默认 `false`；选择企业内部分发时才由生产管理员
  在受控服务器环境中显式设为 `true`；
- `worker`、`beat`、`frontend`、`postgres`、`redis` 均不可访问该目录；
- 基础文件中的 `upload_storage`、网络和其他服务配置继续生效。

### 上线前校验

从 GitHub Actions 下载 `WorkBuddy Connector Release` 最终的聚合 artifact，在与
`/data/kap` 相同的文件系统中解压到新的、不可变的版本目录。不要直接覆盖当前正在提供
下载的目录，也不要把下载凭证、签名证书或 CI 元数据放进制品目录。

先完成公共准备，不要直接覆盖当前正在提供下载的目录：

```bash
sudo install -d -m 0755 /data/kap/workbuddy-connectors-releases
RELEASE_DIR=/data/kap/workbuddy-connectors-releases/<version>
sudo install -d -m 0755 "$RELEASE_DIR"
# 将聚合 artifact 只解压到 "$RELEASE_DIR"
```

然后只能选择以下一条渠道路径。

#### 企业内部版

1. 在 GitHub Actions 运行 `channel=internal`，下载对应聚合 artifact。
2. 管理员在受控服务器环境中显式设置
   `WORKBUDDY_CONNECTOR_ALLOW_INTERNAL=true`。该开关在所有环境默认关闭；未设置、空值及
   其他非真值都会保持拒绝。
3. 使用显式参数校验未签名内部制品：

   ```bash
   python scripts/verify_workbuddy_connector_artifacts.py \
     --root "$RELEASE_DIR" \
     --allow-internal
   ```

该路径要求三个目标、版本、文件名边界、SHA-256 和目录内容完整，并要求全部安装包明确
`signed=false`、`notarized=false`；它不会伪造或要求 production attestation。Windows
或 macOS 安装时可能显示未知来源、安全保护或确认来源提示，只能在公司授权设备安装。
关闭服务器开关后，KAP 会以安全的 503 拒绝内部版清单和下载。

#### 正式版

运行 `channel=production`。不要使用 `--allow-internal` 替代任何正式版验证：

```bash
# gh 必须能读取本仓库 attestation；凭据只通过 GH_TOKEN 或 gh auth 注入，不打印值
python scripts/verify_workbuddy_connector_artifacts.py --root "$RELEASE_DIR"
```

校验器固定信任
`Moways3305/knowledge-asset-platform/.github/workflows/workbuddy-connector-trusted-builder.yml`，
通过 `gh attestation verify` 校验 GitHub OIDC/Sigstore 签名、制品摘要、仓库与 workflow
身份以及签名验证 predicate。目录中还必须恰好只有三个安装包和 `manifest.json`，并检查：

1. manifest 具有受信工作流签发的完整生产 attestation，且清单
   `channel=production`；
2. Windows x64、macOS arm64、macOS x64 三个目标完整且不重复；
3. 文件名不能越出制品目录，实际 SHA-256 与清单一致；
4. Windows 安装包具有 Authenticode 已验证 attestation；macOS 安装包具有 Developer ID
   签名及 stapled notarization 已验证 attestation；清单布尔值不能单独通过校验；
5. 不存在额外文件或目录。

任一渠道的校验失败都必须停止部署。校验通过后统一执行权限收口：

```bash
sudo chown -R root:root "$RELEASE_DIR"
sudo chmod -R a-w "$RELEASE_DIR"
```

### 原子替换

用符号链接在同一文件系统内原子切换固定宿主机路径，并只重新创建 `backend`，使 Docker
重新解析链接目标：

```bash
NEXT_LINK=/data/kap/.workbuddy-connectors.next
sudo ln -sfn "$RELEASE_DIR" "$NEXT_LINK"
sudo mv -Tf "$NEXT_LINK" /data/kap/workbuddy-connectors
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  up -d --no-deps --force-recreate backend
```

首次上线前确认 `/data/kap/workbuddy-connectors` 不存在或是可替换的符号链接，不能是承载
其他数据的真实目录。保留上一版本目录；回滚时对上一版本重新执行校验，原子切回链接并按
上述命令重新创建 `backend`。确认新版本稳定后再按运维保留策略清理旧版本。

### 上线后烟测

准备两个短期会话：一个在职业务用户，以及一个无业务权限的已登录用户。会话值只通过受控
环境变量注入，不写入命令参数、日志或发布单：

```bash
export KAP_SMOKE_SESSION_COOKIE='<business-session>'
export KAP_SMOKE_UNAUTHORIZED_SESSION_COOKIE='<non-business-session>'
python scripts/workbuddy_connector_smoke.py \
  --base-url https://<kap-production-host> \
  --platform windows \
  --architecture x64 \
  --expected-channel production
unset KAP_SMOKE_SESSION_COOKIE KAP_SMOKE_UNAUTHORIZED_SESSION_COOKIE
```

企业内部版烟测把最后一个参数改为 `--expected-channel internal`。烟测必须确认：未登录
请求被拒绝、无业务权限用户返回 403、业务用户获得恰好三个所选渠道目标、任选一个安装包
下载成功且 SHA-256 与清单一致。脚本只输出状态码、渠道、目标和校验布尔值，不输出
cookie、文件内容或存储路径。

缺失和篡改的 fail-closed 验证必须在测试目录运行，不得修改生产目录：

```bash
python -m pytest backend/tests/test_workbuddy_token.py \
  backend/tests/test_workbuddy_connector_deployment.py -q
```

KAP 在每次清单或下载请求时仍会重新校验渠道开关和制品；任一条件不满足时下载 fail closed。
下载接口还会校验 KAP 登录身份为在职业务用户。安装包、下载 URL、服务日志和清单都不得
包含 token、token hash、Authorization、cookie、用户 ID、内部存储引用或私有上游 URL。

## 用户升级

旧的本地 Python 配置不会因打开向导、选择平台或下载安装包而失效。用户先安装连接器，
然后主动生成对应平台的新配置；只有此动作会轮换 token。新配置导入并完成一次真实 KAP
工具调用后，向导显示后端记录的最近连接时间，此时再删除旧配置。
