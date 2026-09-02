# 入库上传韧性生产验收

本验收仅使用命令、数据库断言和文本输出；不要在 `docs/claude_tasks/evidence` 或其他仓库目录保存截图、视频、二进制样本。

## 部署顺序

1. 备份数据库，并确认当前 Alembic head。
2. 构建后端、worker、beat 和前端镜像。
3. 先执行数据库迁移，再滚动重启 backend、worker、beat；不得只重启 API。
4. 确认 worker 注册 `ingest.process_upload` 和 `ingest.recover_stale_uploads`，beat 每 60 秒调度回收任务。

```bash
docker compose exec backend sh -lc 'cd /app/backend && alembic current && alembic upgrade head && alembic current'
docker compose up -d --build backend worker beat frontend
docker compose exec worker celery -A app.worker.celery_app.celery_app inspect registered
docker compose exec worker celery -A app.worker.celery_app.celery_app inspect ping
docker compose logs --since=10m beat worker | grep -E 'ingest.recover_stale_uploads|ingest.process_upload'
```

预期 Alembic head 为 `0069_ingest_processing_heartbeat`，worker ping 成功且两个任务均已注册。

## 协议与文件级断言

使用测试账号取得正常的 cookie/CSRF 后，分别提交 10、100、500、1000 项 manifest；每个可上传项的 `transport_batch_index=floor(ordinal/10)`，`total_transport_batches=ceil(count/10)`。逐批上传时每批不超过 10 文件和 20 MiB，并在最后调用 `/complete`。

断言：

- `/init` 对 1000 项返回 200，响应有 1000 个稳定 item id；422 时前端只显示白名单字段摘要。
- 任一批网络中断后，之前批次仍成功，当前批仅影响其 item，后续可逐文件补传并继续。
- 空文件、损坏文件、扩展名伪装、加密 PDF/Office、解压膨胀或结构超限均形成文件级安全错误；响应、日志、审计中没有密码、原始异常、存储引用或文件正文。
- 平台从不提供密码输入，也不要求用户提交密码；操作建议只要求在本地解除保护后重新上传。

## 停滞恢复断言

以下查询用于观察，不修改业务数据：

```sql
SELECT id, status, processing_stage, retry_count, max_retries,
       processing_heartbeat_at, updated_at, error_type
FROM ingest_tasks
WHERE status = 'processing'
ORDER BY processing_heartbeat_at NULLS FIRST, created_at;
```

抽取任务由 worker 在阶段边界刷新 `processing_heartbeat_at`。单次 Celery 作业有 120 秒软时限和 135 秒硬时限；心跳超过 180 秒或任务已接收后始终没有心跳时，beat 在下一次 60 秒扫描中受控重投，避免与仍在终止中的 worker 重叠。达到 `max_retries` 后收口为 `failed / processing_abandoned`。因此正常调度下，从最后心跳到自动重试或失败收口的目标上界为 240 秒（不含 broker/数据库完全不可用的时间）。

重复执行观察查询并断言：

- 同一任务的 `retry_count` 单调增加且不超过 `max_retries`。
- 重投任务获得新心跳，或最终成为 `failed / processing_abandoned`，不长期停留在 `processing`。
- `result_asset_id` 不因重复投递产生多个资产；同一 `ingest_task_id` 的 AI 结果和衍生文件唯一约束仍成立。

## 回滚说明

应用回滚到旧版本前，先停止新版本 beat 和 worker。数据库 downgrade 会删除 `processing_heartbeat_at`；只有在确认不再依赖新回收任务时才执行。生产优先采用应用前滚修复，不建议对已有处理任务直接 downgrade。
