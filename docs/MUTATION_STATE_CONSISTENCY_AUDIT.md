# 写操作状态收敛审计

本表记录页面写操作完成后，浏览器状态如何回到 KAP 服务端事实。工作台运行概览仅查询安全聚合数据；它不扫描微盘或文件，也不触发索引、解析、初始化重试。

| 页面 / 操作 | 服务端终态来源 | 收敛方式 | 停止条件 | 主要测试 |
| --- | --- | --- | --- | --- |
| `/upload` 上传 | 入库任务状态接口 | 上传受理后标记 `processing`，有限轮询任务状态；进入 `awaiting_confirmation` 或 `failed` 后停止 | 终态、尝试上限、来源切换、卸载 | `useUploadFlow.test.ts` |
| `/upload` 单条重试 | 新入库任务及任务状态接口 | 本地立即改为排队，随后复用上传与状态轮询 | 同上传 | `useUploadFlow.test.ts` |
| `/upload` 单条/批量确认 | 确认接口响应、待确认列表 | 成功项立即从待确认列表和本次上传队列移除，再重新获取当前来源列表；失败项保留 | 每项响应、批次结束、来源切换、卸载 | `useUploadFlow.test.ts`、`UploadStepB.test.tsx` |
| `/upload` 单条/批量拒绝删除 | 删除接口响应、待确认列表 | 仅成功后从两处本地列表立即移除，再重新获取；失败保留并显示安全提示 | 每项响应、批次结束、来源切换、卸载 | `useUploadFlow.test.ts`、`UploadStepB.test.tsx` |
| `/admin/ingest` 批量重试、重新解析、单条重试 | 索引作业列表、索引统计、健康接口、入库概览 | 提交后刷新四项摘要；存在 `queued/running` 时单实例有限轮询作业，终态后刷新其余摘要 | 全部作业终态、20 次查询、页面隐藏期间暂停查询、权限/请求失败、卸载 | `AdminIngestPage.test.tsx` |
| `/admin/wecom-scan` 创建/编辑 | 扫描配置接口响应 | 将服务端返回配置合并到当前列表；失败不覆盖旧配置 | 单次请求完成 | `AdminWecomScanPage.test.tsx` |
| `/admin/wecom-scan` 启停 | 更新配置接口响应 | 用服务端 DTO 替换对应配置 | 单次请求完成、403 转只读 | `AdminWecomScanPage.test.tsx` |
| `/admin/wecom-scan` 立即扫描 | 扫描记录接口 | 写入返回记录并重新获取该配置的运行记录 | 扫描请求完成、403 转只读 | `AdminWecomScanPage.test.tsx`、后端扫描测试 |
| `/admin/company-kb` 创建/初始化重试 | 公司 KB 状态接口响应 | 直接使用服务端返回状态；删除后重新获取 | 单次请求完成 | `AdminCompanyKbPage.test.tsx` |
| `/my/knowledge` 个人 KB 创建/初始化重试、资产写操作 | 个人 KB/资产列表接口 | 使用服务端返回 KB 状态；资产操作完成后重新获取列表和 KB 状态 | 单次请求完成 | `MyKnowledgePage.test.tsx` |
| 项目页 KB 创建/初始化重试 | 项目概览/设置接口 | 使用服务端响应或重新获取项目数据 | 单次请求完成、项目切换、卸载 | 项目概览与设置页测试 |
| `/review` 审核决定 | 审核列表接口 | 写操作成功后重新获取当前筛选列表，请求序号阻止旧响应覆盖 | 单次请求完成、筛选变化、卸载 | `ReviewPage.test.tsx` |
| `/original-access` 审批 | 原文申请列表接口 | 写操作成功后重新获取当前箱体，请求序号阻止旧响应覆盖 | 单次请求完成、箱体变化、卸载 | `OriginalAccessPage.test.tsx` |
| 项目成员管理 | 项目成员、候选人和权限接口 | 写操作成功后重新获取成员/当前用户权限；删除项目后导航离开 | 单次请求完成、项目切换、卸载 | `ProjectSettingsPage.test.tsx`、`AdminPeoplePage.test.tsx` |

## 工作台运行信号下钻

- `index_failed`、`parse_failed`：进入 `/admin/ingest`，由索引维护页展示安全计数并提供显式操作。
- `kb_init_failed`：按公司、个人和具体项目拆成独立安全卡片。公司治理角色进入 `/admin/company-kb`；个人失败进入 `/my/knowledge`；对应项目经理进入受后端项目范围过滤的 `/admin/weknora-models`，普通项目成员只进入项目状态页。跨 scope 失败不再误导到公司 KB。
- 原文申请类信号：进入 `/original-access`。
- 生命周期治理信号：进入现有知识治理页面。

所有下钻仅使用已注册的 KAP 页面路由；浏览器不持有 WeKnora KB ID、模型内部 ID、存储引用、密钥或上游错误正文，后端权限仍是最终裁决。
