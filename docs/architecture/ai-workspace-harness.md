# AI 工作空间：共享 Harness 与知识维护 Agent

KAP 在同源独立工作空间 `/ai-workspace` 中提供通用助手与业务 Agent，复用平台登录、模型注册表、知识权限和审计。知识维护 Agent 默认进入连续任务会话；会话顶部不设业务导航；问题明细、巡检记录和配置从输入框旁的智能体选项按需打开侧栏，旧通知深链仍能定位相应知识库和问题。旧巡检整页已移除。

工作空间使用平铺会话和线性列表：依靠文字层级、留白与细分隔线组织内容，不使用卡片容器。执行确认、工具回执和辅助管理页沿用这一规则；输入框、菜单及必要确认弹窗仍使用标准交互控件。

## 架构边界

| 层 | 责任 |
| --- | --- |
| 工作空间 | 同一会话中交代、补充、停止、继续任务，展示真实工具动作与结果，右侧预览、编辑私有报告 |
| Agent 定义与工具注册 | 职责、提示、可用工具及参数约束；模型只能选择当前 Agent 注册的工具 |
| 通用运行器 | 模型→工具→观察循环、持久检查点、运行租约、用户补充、等待恢复、具体动作确认与幂等 |
| KAP 业务服务 | 当前资料与版本、权限、巡检覆盖、问题责任、通知 Outbox、换版跟踪及复检关闭 |

固定巡检流水线作为确定性业务工具保留。模型根据用户目标选择盘点、检索、核对资料、调查问题、启动巡检、观察结果或请求复检；不把整个业务工作流硬编码成另一套 Agent 执行器。通用助手没有知识维护的修改工具。

## DeepSeek Harness 代码参考

固定参考 [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) 提交 `4b399c39a6d1479cd84ca591b4d7c88e24d38a96`：

- [agent-loop/src/agent.ts](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/core/agent-loop/src/agent.ts#L576-L587)：执行模型选择的工具，将结果送入下一轮。
- [tools](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/core/tools/README.md)：工具声明、参数与输出、执行守卫和失败结果；KAP 的工具必须在后端重新核对业务权限。
- [session](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/core/session/README.md)：按事件恢复上下文；其核心内存会话需要另配持久化。KAP 使用现有 SQLAlchemy 数据库。
- [approval](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/docs/subsystems/approval.md)：确认绑定到具体动作，拒绝与取消有可观察结果。
- [architecture](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/docs/architecture.md)：通用底座、业务能力和产品入口分层组合。
- [journal-stream.ts](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/api/gateway/src/client/journal-stream.ts)、[ConversationMainPanel.tsx](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/client/ui-conversation/src/client/skeleton/ConversationMainPanel.tsx)、[SidebarRight.tsx](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/packages/client/ui-sidebar-right/src/client/shell/SidebarRight.tsx)：增量事件、加载状态与预览状态分开，后台更新不重置阅读和编辑。

上游采用 [MIT License](https://github.com/deepseek-ai/deepseek-harness/blob/4b399c39a6d1479cd84ca591b4d7c88e24d38a96/LICENSE)，Copyright © 2026 DeepSeek。本次为依据上述执行与交互原则的独立 Python/React 实现，未复制其 Node/Cordis 运行时，不引入任意 Shell、文件系统或自定义 URL 执行能力。

## 状态与确认

会话绑定用户及当前工作身份，并记录 Agent 类型。运行持久保存步骤、工具意图、脱敏观察结果和用户补充；工具业务写入、动作回执与检查点在同一受租约保护的事务提交。停止、删除会话或旧租约失效后，迟到工作不得继续写入。

长巡检使用等待句柄，由现有扫描 worker 分批处理，通用运行器观察进度后继续；不通过连续空转模型调用来等待。需要用户决定的动作保存具体参数和影响说明，确认后再检查当前权限、资料版本和问题状态。用户拒绝会产生工具观察结果，模型可以调整后续行动。

任务执行结束不等于维护问题解决。模型不能调用任意“关闭问题”操作；换版后未解决事项继续跟进，复检仍使用当前版本和原有业务规则。失败、未覆盖、取消或权限变化不得算作复检通过。

## 权限、隐私与产物

- 每次执行及恢复重新获取身份、项目关系、模型可用性和知识权限。Agent 工具不能授予额外权限；个人知识库不参与维护巡检。
- 普通知识检索仅返回调用者有权查看的摘要及来源。维护证据按维护权限与原文授权投影；敏感检测原值不进入普通会话、工具观察、报告、通知或日志。
- 工具输入、观察、标题、模型回复和报告统一脱敏；执行事件与错误使用安全文案，不持久化原始供应商异常。
- 来源绑定资产、当前版本与可见投影。重放、继续、预览、编辑前重新验证，资料撤回或权限变化后隐藏受影响的派生内容。
- 报告和修订建议是私有草稿，不冒充已修改知识原文。实际业务动作有独立回执，模型文字不决定业务状态。
- 对话中断、暂时轮询失败和预览切换不清空用户草稿；会话正文不写入 localStorage。

## 旧实现清理与上线

移除 `KnowledgeTaskWorkspace` 一次性表单、旧 `/maintenance-agent/libraries/{library_key}/tasks` API、`knowledge_tasks` 独立运行器及恢复调度。资料搜索、已采纳版本核对与证据能力归入共享工具；不保留第二套模型决策循环。

迁移 `0097_agent_runtime` 增加 Agent 类型、运行检查点和动作表。`0098_legacy_agent_sessions` 分页导入旧私有任务：保留用户与角色隔离、脱敏指令和历史时间，未完成旧任务不会自动重放；旧推荐不冒充经过本次核验的结果。旧数据库表仅保留为回退材料，没有生产读写代码。数据迁移重放不覆盖用户后续对话；降级不会删除已经继续使用的会话。

升级须同步更新 API、worker、beat 与前端，先执行 Alembic 迁移。模型仍使用平台现有注册配置；本次不会自动开启定时巡检或扩大正文授权。

验收覆盖模型选择不同工具后的反馈循环、长任务等待恢复、重复确认与通知幂等、运行中补充、停止后的迟到结果、权限撤销、版本更替、复检通过关闭、历史迁移、脱敏和响应式会话预览。自动化测试使用合成资料与可控模型替身，不发送真实公司内容。
