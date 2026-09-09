# 历史安全摘要补齐

适用于详情显示“安全摘要待处理”，且当前版本已有 `one_liner` / `detailed`、缺少安全摘要的 L2–L4 资产。

先部署包含本次修复的 backend / worker 镜像。仅刷新前端不会补齐数据库；无需重新上传原文件。

Ubuntu 服务器中执行（默认只读预演，输出计数与长度，不输出摘要正文）：

```bash
cd /data/kap/repo
dc() { docker compose -p kap -f docker-compose.yml -f docker-compose.prod.yml "$@"; }

dc exec -T backend python -m app.commands.backfill_authorized_summaries \
  --asset-id 201c754d-5387-4204-bbb8-90e4b70d0af8
```

确认 `scanned=1` 且可补齐后执行：

```bash
dc exec -T backend python -m app.commands.backfill_authorized_summaries \
  --asset-id 201c754d-5387-4204-bbb8-90e4b70d0af8 --apply
```

再执行一次不带 `--apply` 的命令应显示 `regenerated=0`。刷新详情，安全摘要应可见，权限不变。

省略 `--asset-id` 可检查所有 L2–L4 资产；全量修复前先备份数据库并预演，只运行一个补齐实例。仅处理当前版本，保留普通摘要和原文件。脱敏失败或源摘要缺失时保留待处理标记，不用原始摘要兜底，也不伪造内容。

接口的 `summary.status` 区分 `ready`、`safe_pending`、`generation_pending`；没有摘要查看权限时 `summary` 仍为 null。安全摘要就绪不代表获得原文权限。
