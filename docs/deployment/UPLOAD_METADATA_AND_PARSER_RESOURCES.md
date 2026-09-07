# 原文件命名、修改日期与解析资源修复验收

## 行为约定

- 规范名正文来自原文件名（去扩展名）；AI 主题只作为内容建议。正式目录、版本、密级及其余命名格式保持既有规则。
- 上传清单逐项传递浏览器 `File.lastModified` 对应的本地日期，经后端校验后保存到 `suggested_formed_on`。确认页显示“文件最后修改日期”；不以 AI 正文日期、文件名日期或服务器落盘时间兜底。历史未保存的日期需人工选择或重新选择原文件，不能无损推断。
- 老版本已有日期没有保存来源标识，可能来自文件名；此修复不批量改写历史数据。历史待确认文件的日期应与本地文件属性复核，不能把现存值当作已经验证的修改时间。
- 密级仅采用有可靠来源的 AI 内容建议或人工选择。AI 缺失、低置信度、旧记录无来源时留空；目录切换不得覆盖人工或 AI 密级。没有可靠密级的个人资料需要进入单文件确认页选择，不能直接批量默认入库。
- 普通 worker 默认并发 1、预取 1，最多处理 20 个任务或子进程 RSS 超过 512 MiB 后回收（任务结束后生效，不是实时硬限制）。容器内存默认 4 GiB；解析子进程仍保留独立的内存、CPU、墙钟时限及解压复杂度限制。
- 子进程非零退出使用 `extraction_process_terminated`，不推断所有 SIGKILL 都是 OOM；明确 `MemoryError` 使用 `extraction_memory_limit`。两者保留原件并允许受权人工重试，不误报文件损坏。

## 部署注意

这次修改不增加数据库迁移。先按主部署手册备份、更新代码并完成现有迁移，再部署同版本 frontend/backend/worker。不要只更新前端。

在 Ubuntu 新 SSH 会话中先定义：

```bash
cd /data/kap/repo
dc() { docker compose -p kap -f docker-compose.yml -f docker-compose.prod.yml "$@"; }
```

`INGEST_WORKER_CONCURRENCY` 和 `INGEST_WORKER_MEMORY_LIMIT` 是根目录 `.env` 的 Compose 插值参数，不是 `backend/.env`。未配置时分别为 `1` 和 `4G`；如有旧覆盖须核实。`docker update` 的临时设置不会替代 Compose 配置。

```bash
dc build backend worker frontend
dc up -d --no-deps --force-recreate backend worker frontend
dc ps
docker inspect kap-worker-1 --format 'memory={{.HostConfig.Memory}} command={{json .Config.Cmd}}'
dc exec -T worker celery -A app.worker.celery_app.celery_app inspect ping
docker stats --no-stream kap-worker-1
```

默认 memory 应为 `4294967296`，启动命令包含 `--concurrency=1`。在低峰部署，保留 beat/ocr_worker 等现有服务，不清队列、不删除上传任务。

## 生产验证

1. 新上传一个原名与正文主题不同的文件；检查单文件与批量预览、确认后的原件与 Markdown 名称均能对应原文件名。
2. 文件最后修改日期设置为与正文日期不同的日期；确认页应显示原文件修改日期。缺失元数据不自动补今天或 AI 日期。
3. 可靠 AI 密级正常展示；低置信度需人工选择。人工选 L4 后切换正式目录，仍应为 L4。
4. 依次重试事故中的两份 PPT，再用小批量观察 worker 内存及内核 OOM 日志。源文件哈希应不变。命令配置正确不等于已完成真实生产压测。
5. 人为终止解析进程的测试仅在隔离测试环境进行；不在生产杀 worker 或制造 OOM。
