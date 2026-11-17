# 个人通知中心

## 产品行为

- 铃铛统计收件箱中含未看新事件的分组；打开中心仅将当时快照之前的收件箱消息设为已看，不自动已读。
- 未读按分组显示，详情保留每条事件。业务待办由任务中心自己的业务事实追踪；通知的已读、归档、删除、恢复不完成审批或维护任务。
- 收件箱、未读、已归档、回收站均有独立视图。删除为个人软删除，不删除业务或审计数据；恢复回到收件箱，不重新亮新提醒角标。恢复已读历史后重新计算保留时间。
- 选择全部、全部已读、归档已读均由后端跨分页处理。历史清理包含收件箱及归档，可按北京时间日期限定，移入回收站。确认时使用打开清理面板时的快照，后台新消息保留。
- 同一任务或资产按目标聚合，上传批次按上传会话聚合。每条事件先重新授权，再计数和聚合；无权限事件不参与列表、角标或批次统计。
- 已展开的详情、设置草稿、勾选与滚动位置不会因轮询重新挂载。轮询使用当前阅读快照，新提醒通过按钮显式载入。权限撤销的项目会从当前内容移除。
- 分类型设置对新产生的消息生效；关闭企业微信还会拦截未发送的旧队列消息。企业微信通道依赖现有平台配置。每小时摘要在整点到期，由现有通知工作队列发送，可能有队列调度延迟。
- 可选择 30/90/180 天自动归档，默认关闭。读取中心时整理已读且已结束的普通消息；未读、待处理、运行中、失败、部分失败和拒绝结果不会自动归档。回收站与业务审计不自动清空。

## 实现边界

迁移 `0092_notification_inbox` 增加个人状态、摘要关联和通知偏好，不改业务模型。旧接口保留；新界面使用 `/api/v1/notifications/inbox`、`/inbox/events`、`/inbox/actions`、`/preferences`。

`notification_reader` 只读授权投影，旧接口和聚合收件箱共用。领域通知仍经过原 Outbox 和 recipient/event 幂等键，清理不删除幂等凭据，因此重投历史事件不会让消息复活。

批量接口要求明确的分组选择或全部匹配范围，不能隐式全选；按用户行串行化个人修改，再按数据库创建时间不晚于快照的条件筛选。清理只改变调用者自己的状态，不需要重新获得原业务操作权限；因此权限已失效的旧消息也能清掉。列表与详情始终重新授权。

摘要成员先以 `digest_pending` 排队，整点到期后短事务用 `SKIP LOCKED` 分配到摘要信封。提交后沿用既有发送租约、重试上限、退避与审计；重试时重新授权成员并忽略已读/清理的消息。对同一目标只统计一次当前状态。站内不显示摘要信封。外部发送仍是有界至少一次，网络成功但回写失败时可能重发，不能宣称精确一次。

## 参考依据

这些资料用于行为对照，没有复制第三方界面或源码：

| 产品 | 采用的经验 |
| --- | --- |
| [Linear](https://linear.app/docs/inbox) | 批量整理、已读与清除 |
| [Notion](https://www.notion.com/help/updates-and-notifications) | 已读与归档分离、按对象聚合 |
| [ClickUp](https://help.clickup.com/hc/en-us/articles/33947959867543-What-is-the-Inbox) | 分组消息、清除后恢复 |
| [Asana](https://help.asana.com/s/article/inbox) | 紧凑收件箱、归档历史 |
| [Slack](https://slack.com/intl/en-gb/help/articles/46751260742035-Introducing-the-new-Activity-view-in-Slack) | 消息整理与历史检索 |
| [GitHub](https://docs.github.com/en/subscriptions-and-notifications/how-tos/viewing-and-triaging-notifications/managing-notifications-from-your-inbox) | 整理通知不关闭业务对象 |
| [Teams](https://support.microsoft.com/en-us/teams/notifications-settings/explore-the-activity-feed-in-microsoft-teams) | 全部已读和筛选 |
| [monday](https://support.monday.com/hc/en-us/articles/360015535060-Bell-Notifications) | 新提醒角标与未读分离 |
| [Atlassian](https://support.atlassian.com/atlassian-cloud/kb/overview-of-in-app-notifications-in-atlassian-cloud-products/) | 未看与未读分离 |
| [Trello](https://support.atlassian.com/trello/docs/receiving-trello-notifications/) | 已读抑制外部提醒、摘要频率 |
| [飞书](https://www.feishu.cn/hc/zh-CN/articles/360045255773-即时消息常见问题) | 会话层级清理未读（仅核对公开摘要） |
| [腾讯云](https://cloud.tencent.com/document/product/1263/71892) | 类型、渠道、日期筛选和订阅 |

## 验收

后端覆盖千条历史清理、新消息保留、重复操作、恢复、目标权限撤销、上传批次明细、渠道偏好、摘要和保留策略。PostgreSQL 测试覆盖并发清理和并发摘要认领。前端测试覆盖跨页范围、设置草稿、详情保持、失败重试、目标导航；浏览器脚本覆盖 320/390/1024/1440/1920 像素和清理后刷新、回收站恢复。
