# 独立并发验收

此配置只用于测试：独立 PostgreSQL、Redis、上传卷，无对外端口，不读取生产 `.env`，
不挂载生产数据。不要改成生产数据库或 broker 地址。探针会校验测试地址后才创建数据。

## 执行

从仓库根目录运行（需要 Docker Compose）：

```sh
docker compose -f deploy/compose.concurrency-test.yml up -d --build --wait postgres redis api heavy light llm
docker compose -f deploy/compose.concurrency-test.yml run --rm --build probe
docker compose -f deploy/compose.concurrency-test.yml stats --no-stream
docker compose -f deploy/compose.concurrency-test.yml logs --tail=100 api heavy light
```

探针非零退出即失败。最后输出 JSON 验收结果，不要仅凭容器启动成功判断验收通过。
建议在干净的测试环境执行一次；重新验收前按下文清理，避免前次任务影响计数与时延。

## 覆盖范围

- 真实 PostgreSQL + Redis/Celery：4 个 prefork 进程争抢 1 个重处理名额，必须仅 1 个获准。
- 对账认领：4 个进程读取同一版本快照并同时认领，必须仅 1 个成功。
- 队列隔离：4 个重型任务占满 `ocr` worker 时，`default` worker 的轻型任务仍能执行。
- 批量预览：2 个 API 进程，4 并发、40 个请求，每个请求 25 项，检查全部可提交，输出 P95。
- 上传至入库：3 个用户、5 并发、15 个合成 TXT/DOCX/PPTX/XLSX/PDF 文件，
  走实际 HTTP 上传、Celery 处理、状态查询和人工确认接口。
- 会话分批上传：3 个用户各上传 10 个 TXT 文件，每批 5 个，顺序发送两个批次；
  每个批次同时发送两个相同请求，检查幂等、任务 ID 一致、文件计数不翻倍，
  最终通过会话轮询和最多 5 并发确认将 30 个文件全部入库。
- 上述三类 HTTP 工作负载同时执行，延迟包含接口互相竞争带来的影响。

LLM 是隔离环境内的确定性替身；不调用真实模型，不连接 WeKnora，不使用客户资料。
此测试不代表生产模型/WeKnora 延迟，不覆盖扫描件 OCR、旧 DOC/PPT/XLS 转换或大文件峰值。
数据库按当前模型创建，不替代 Alembic 迁移回归。
生产吞吐上限仍需在与生产相同 CPU/内存配额下，用授权的代表性文件另行测量。

## 清理

以下命令只删除本配置所属测试容器、网络、测试上传卷，以及 tmpfs 中的合成数据库数据；
这些合成数据不会保留，生产 Docker 卷不受影响。

```sh
docker compose -f deploy/compose.concurrency-test.yml down --volumes
```

不要用 `docker system prune` 或手工删除 Docker 数据目录代替上述清理。
