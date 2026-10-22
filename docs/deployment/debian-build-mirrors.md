# Debian 构建软件源

适用于 Debian CDN 部分节点超时导致后端镜像构建失败。只影响新镜像构建，
不修改宿主机 APT、运行容器网络、数据库或 WeKnora。

默认两个参数为空，保留基础镜像的软件源。确需切换时，在执行既有
`scripts/deploy_release.py` 发布流程的同一个 shell 导出：

```bash
export KAP_DEBIAN_MIRROR="https://mirrors.ustc.edu.cn/debian"
export KAP_DEBIAN_SECURITY_MIRROR="https://mirrors.ustc.edu.cn/debian-security"
```

也可由管理员写入项目根目录未被 Git 跟踪的 `.env`；不是 `backend/.env`。
两个值必须成对提供，仅接受无凭据、无查询参数的 HTTPS 仓库地址。
Compose 为 backend、worker、ocr_worker、beat、migrate 统一传入构建参数。
发布脚本原有版本身份、备份确认、迁移与健康检查流程不变。

仅替换基础镜像 deb822 文件的 `URIs`，保留发行版、更新分支、组件和
`Signed-By`；不添加 `trusted=yes`，不关闭 TLS 或 Debian 签名校验。
基础镜像仓库结构不符合预期时停止构建，要求重新检查，不静默漏掉安全源。
APT 下载使用 30 秒网络超时和最多两次重试；这不是整个构建的总时限。

验证分三层：仓库索引可读、真实 Docker 构建安装成功、发布后版本及服务健康。
前两者不能互相替代，短时 TCP 连通也不能证明大文件下载稳定。
镜像站说明：https://mirrors.ustc.edu.cn/help/debian.html

恢复默认时清除 shell 与根 `.env` 的两个覆盖值，再进行正常版本化构建。
不要写死 CDN IP，不要修改防火墙、删除缓存或停止生产服务来绕过下载失败。
