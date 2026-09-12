# DOC/PPT 与 100 MB 上传部署

单文件上限为 **100,000,000 字节（100 MB）**。普通请求保持 20 MiB / 10 文件批次，
超过 20 MiB 的文件单独传输。前端、API、存储及宿主机/容器 Nginx 必须同版本更新；
Nginx 为 multipart 留有开销空间，设置 110m，不代表应用接受 110 MiB 文件。

DOC/PPT 使用 LibreOffice 的 headless 转换接口，独立配置目录禁用不可信宏，
输出 DOCX/PPTX 后继续结构检查和正文提取。原件不会覆盖或改名。
参考：[LibreOffice 启动参数](https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html)。

限制：纯图片 DOC/PPT 目前不会自动转换到 PDF 再 OCR；无可提取文字时返回空正文，
可另存为 PDF 后上传走 OCR。加密或转换不兼容返回转换失败，不尝试破解密码。
100 MB 是接收上限，不是解析成功保证；解压大小、页面复杂度、内存和超时保护继续生效。
旧版 XLS 不在本次支持范围内。

## 发布后操作（Ubuntu）

在确认 PR 已合并、数据库备份和正常发布检查完成后执行：

```bash
cd /data/kap/repo
dc() { docker compose -p kap -f docker-compose.yml -f docker-compose.prod.yml "$@"; }
git pull --ff-only
dc build backend worker ocr_worker beat frontend
dc up -d --no-deps backend worker ocr_worker beat frontend
dc ps
dc exec -T ocr_worker libreoffice --version
dc exec -T backend python -c 'from app.services.storage import MAX_UPLOAD_BYTES; print(MAX_UPLOAD_BYTES)'
```

最后一行应为 `100000000`。所有处理镜像都需重建，不能漏掉 `ocr_worker`。
DOC/PPT 初次处理和故障恢复都投递到单并发 OCR/重型队列；不会提高普通 worker 并发。
本次无需数据库迁移。容器重建前应等待正在执行的任务完成，避免中断用户任务。

宿主机 Nginx 不会随 Docker 更新：按现有站点域名和路径设置
`deploy/install-host-nginx.sh` 要求的环境变量，先运行 `--check`，
再运行 `--install` 和 `--verify`；遵循主部署手册，不替换完整站点配置。
确认两层上传 location 都为 `client_max_body_size 110m`。

验收：上传带文字的真实 DOC、PPT（确认中文正文），上传一个 25–100 MB 文件，
验证大文件独立请求；100000001 字节应被明确拒绝。
Linux CI 安装相同的转换运行时，执行 `tests/test_legacy_office.py` 的真实格式往返测试。
本地无 LibreOffice 时该真实引擎测试会跳过，其余协议/错误测试不依赖安装。

若 WeKnora 仍配置 50 MB，该限制是独立的：本次只调整 KAP 上传，未修改 WeKnora。
需要提交原件给知识底座的路径仍应单独核对底座限制。
