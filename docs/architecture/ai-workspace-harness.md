# AI 工作空间：通用会话与 Agent 边界

KAP 的「AI 工作空间」在同源新标签页打开 `/ai-workspace`，使用现有登录会话、身份权限和模型配置。它有独立的导航、会话区和文档预览区。`/agents` 兼容入口转到工作空间的 Agent 页；已有知识维护 Agent 的深链保留。

## 分层

| 层 | 责任 |
| --- | --- |
| 工作空间 | 会话历史、多轮输入、模型和上下文选择、执行进度、停止与重试、文档预览与编辑 |
| 运行服务 | 私有会话、每会话单个活动任务、幂等请求、执行租约、有序事件、失败恢复 |
| 通用工具 | 查找选定知识库中可访问的摘要、读取当前会话文档、生成私有文档草稿 |
| Agent | 业务专用流程；知识巡检、通知维护人、跟进问题、复检关闭属于知识维护 Agent |

工作空间不会自行发送维护通知或更改知识资产。草稿保存只修改当前会话中的私有文档。知识维护入口继续进入已有功能；其计划和调度不搬入通用会话服务。

## DeepSeek Harness 参考

参考官方仓库 [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)，固定版本 `4b399c39a6d1479cd84ca591b4d7c88e24d38a96`。本实现沿用 KAP 的 React/FastAPI/SQLAlchemy/Celery 栈，根据下列源码中的设计组织会话、事件和预览状态，并未嵌入 DSH 的 Node Host 或使用其 owner-token 部署方式。

- [journal-stream.ts](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/api/gateway/src/client/journal-stream.ts)：按游标追加、去重、断线恢复保留已呈现内容。KAP 通过有限分页的 HTTP 增量读取实现执行事件更新，当前不提供模型 token 流式输出。
- [AppFrame.tsx](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/client/ui-layout/src/client/AppFrame.tsx)：优先保护对话区域，窄屏侧栏切换为抽屉，预览切换为独立覆盖区域。
- [SidebarRight.tsx](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/client/ui-sidebar-right/src/client/shell/SidebarRight.tsx)：预览展开与折叠不清除每个会话的编辑状态。
- [ConversationMainPanel.tsx](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/client/ui-conversation/src/client/skeleton/ConversationMainPanel.tsx)：区分加载历史与空白会话，避免界面反复回到欢迎态。
- [持久化说明](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/docs/subsystems/persistence.zh.md)：追加事件记录执行过程，中断有明确终态；历史不会因新任务开始而清空。

上游采用 [MIT License](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/LICENSE)，Copyright © 2026 DeepSeek。本次为基于架构与交互原则的独立实现，未复制上游运行时源代码。

## 权限与隐私

- 会话绑定用户和当前工作身份。不能凭会话 ID 访问他人内容，切换身份后重新核验。
- 复用平台模型注册表，不返回供应商凭证，不新增模型密钥输入。
- 输入、模型结果、文档和标题使用平台脱敏服务；错误和执行事件仅使用服务端定义的安全文案。
- 知识工具复用目录检索和详情权限投影，不读取原文，不绕过原文授权。摘要不是完整文件；结果注明摘要及截断状态。
- 保存来源资产、版本和摘要投影指纹；展示、续写和编辑时核对来源，防止撤权或版本变更后继续返回旧派生内容。
- 通用运行器只执行服务端登记工具，不提供任意终端、代码执行或模型自定义 URL 请求。
- 浏览器缓存只用于当前页面状态；不将模型凭证或会话正文写入 localStorage。

## 运行与验收

新表通过 Alembic 迁移建立。升级时需要同步更新 API、worker 和前端；先执行迁移，再启动新版服务。不要将已有生产库回滚为旧备份来测试这项功能。

验收覆盖：新建和继续会话、不同用户/身份隔离、模型不可用、重复提交、增量事件游标、停止后迟到响应、失败重试、文档编辑冲突、权限撤回、脱敏、窄屏布局和阅读位置保留。测试模型使用可控替身，不在自动化验收中发送真实公司资料。
