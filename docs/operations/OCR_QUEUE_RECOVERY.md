# OCR 队列与事故恢复运行手册

生产 OCR worker 固定消费 `ocr` 队列，使用 `prefork`；2 GiB 容器的默认预算是
`concurrency=1`、`prefetch_multiplier=1`、`max_tasks_per_child=4`、
`max_memory_per_child=700000 KiB`。普通 worker 只消费 `default`，因此 OCR 积压不会阻塞
通知、扫描、对账和恢复扫描。并发与容器内存必须一起压测，禁止只提高并发。

任务被 OOM、SIGKILL 或容器重启打断后，beat 每分钟在 `default` 队列触发业务租约扫描。
扫描以物理文件 `stat().st_size` 为准：非零文件有限指数退避恢复；缺失或 0B 进入
`source_unavailable`；超过恢复上限进入 `worker_lost_recovery_exhausted`。这些转换均有安全审计，
不记录存储引用、路径或正文。OCR 每页完成后提交页状态与 server-only 页文本，重跑跳过成功页。

事故遗留任务先执行 dry-run：

```bash
python -m app.commands.recover_ocr_incident
```

若事故任务 UUID 清单已导出，应为每条追加 `--task-id <UUID>`（最多 31 条）；这样 dry-run
也会单独统计已成功、已非 processing 的任务，不会把后来已完成的任务再次入队。

只有 `docker compose config` 能看到上述限流、单份 PDF 冒烟通过，且 cgroup `oom_kill`
没有增长后，才允许每批 3 份低速恢复：

```bash
python -m app.commands.recover_ocr_incident --apply --confirm-ocr-ready \
  --memory-events-path /sys/fs/cgroup/memory.events
```

命令最多处理 31 条、默认批间隔 15 秒；若检测到新的 `oom_kill` 会停止后续批次。恢复期间同时
观察 `docker stats`、`memory.events`、Redis `ocr` 队列长度、成功率、单页/整份 OCR 时延和安全错误码。
