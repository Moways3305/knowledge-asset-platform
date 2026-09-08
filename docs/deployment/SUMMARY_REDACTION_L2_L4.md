# L2–L4 摘要脱敏上线说明

公司上传适用对象默认“通用”，可编辑；密级建议按业务 L1–L5 标准判断，低置信度仍需人工选择，不默认 L2。

摘要展示采用统一策略：L1 普通摘要；L2–L4 仅脱敏摘要，未经脱敏的知识点不展示；L5 原权限及展示策略不变。
不修改原文件、原始摘要、原文授权与原文片段处理规则。此策略覆盖列表、详情、检索卡片、工作台摘要、重复文件比较。
无脱敏摘要时返回空值，不退回普通摘要。历史 L2 摘要在回填完成前可能为空。

## 历史摘要回填

先备份数据库、部署同版本后端和 worker，再在 Ubuntu 服务器执行只读预检：

```bash
cd /data/kap/repo
dc() { docker compose -p kap -f docker-compose.yml -f docker-compose.prod.yml "$@"; }
dc exec -T backend python -m app.commands.backfill_authorized_summaries
```

确认统计后再执行写入（更新当前版本的脱敏摘要，不改变原文或密级）：

```bash
dc exec -T backend python -m app.commands.backfill_authorized_summaries --apply
dc exec -T backend python -m app.commands.backfill_authorized_summaries
```

重复预检应无新的待更新项；`pending` 表示原始摘要缺失或处理失败，需要进一步检查，不能当作已完成。
目前回填一次加载全部目标摘要，大库先在维护窗口评估内存，不与大量入库并行执行。

## 验收与边界

用合成联系人、带角色的人名、人民币/外币/中文大写金额检查 L2–L4 列表、详情和检索卡片；
普通摘要和原文件仍需保持原内容。L1 公开摘要不变，L5 不增加任何可见性。
正则只覆盖已定义的实体表达，不是通用人名识别；无称谓姓名等仍可能漏识别。
“（脱敏）”前缀不是完整脱敏保证，真实样本仍需人工验收；不能用规则脱敏替代权限控制。
