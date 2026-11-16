# 巡检记录、长文覆盖与后台更新设计依据

2026-11-16 按用户要求，先查阅公开高星项目的实际代码，再修改。以下仅参考交互和任务生命周期的设计；未复制第三方源码，也没有为此整体替换本项目的数据层。

## 对照源码

| 项目与固定版本 | 查看位置 | 本项目采用的做法 |
| --- | --- | --- |
| Dify `3f72db6c` | [文档列表](https://github.com/langgenius/dify/blob/3f72db6c4be7d3136ce69ada81e688820190bc8f/web/app/components/datasets/documents/index.tsx) | `keepPreviousData`、仅首次无数据时显示占位、列表查询与选中/搜索/分页状态分开，完成动作只使相关查询失效 |
| Dify 同版本 | [评测任务查询](https://github.com/langgenius/dify/blob/3f72db6c4be7d3136ce69ada81e688820190bc8f/web/app/components/evaluation/queries.ts) | 列表和任务详情分别查询；仅活动任务轮询，保留旧数据，避免窗口聚焦触发破坏性刷新 |
| TanStack Query `56d98b0d` | [QueryObserver](https://github.com/TanStack/query/blob/56d98b0d480f425cf8e03754c8cd850ef585a347/packages/query-core/src/queryObserver.ts) | 首次 pending/loading 与后台 fetching/refetching 分开；后台失败与首次失败区分 |
| Dify `09ec59c7` | [应用日志列表](https://github.com/langgenius/dify/blob/09ec59c7b80f90b469d12fade856ba1d14293a49/web/app/components/app/log/list.tsx) | 紧凑表格保留关键状态，按需打开详情 |
| Langflow `260cbf34` | [trace API](https://github.com/langflow-ai/langflow/blob/260cbf347cc5563cc48c79094c175ca31532ea2b/src/backend/base/langflow/api/v1/traces.py)、[任务队列服务](https://github.com/langflow-ai/langflow/blob/260cbf347cc5563cc48c79094c175ca31532ea2b/src/backend/base/langflow/services/job_queue/service.py) | 删除历史与取消运行是不同操作；服务端核对所属资源权限，取消在工作执行路径生效 |
| Langflow 同版本 | [递归文本分段](https://github.com/langflow-ai/langflow/blob/260cbf347cc5563cc48c79094c175ca31532ea2b/src/lfx/src/lfx/components/langchain_utilities/recursive_character.py) | 每段大小和重叠控制调用成本，不把单段预算当全文可处理上限 |
| RAGFlow `53c6d87f` | [层级分段](https://github.com/infiniflow/ragflow/blob/53c6d87f5fcb12f0faf5efbef8fd1405f5608c52/internal/ingestion/component/chunker/hierarchy.go)、[执行组件](https://github.com/infiniflow/ragflow/blob/53c6d87f5fcb12f0faf5efbef8fd1405f5608c52/internal/agent/canvas/node_body.go) | 超长内容继续切分；单次模型超时与整个长任务生命周期分开 |

## 本地根因与调整

- 巡检列表轮询曾同时 `setData(null)`、`setRuns([])`，详情轮询也 `setData(null)`，导致子树卸载。改为同一查询范围保留数据，响应后原位替换。慢响应串行更新，旧范围的迟到响应忽略；详情状态与列表独立。
- 巡检设置曾以服务端 revision 作为 React key；他人保存配置或后台重新取数可能重建编辑器。改为仅切库或本人保存后重建，保留编辑草稿，继续使用版本冲突校验。
- 审批与原文访问操作后的 `load()` 曾先清空所有行。改为只在筛选/目标切换时清空；同范围刷新保留行、选中项和详情。失败时保留可读内容，暂停依赖最新状态的决策按钮，避免重复提交。
- 公共 DataTable 在已有行时保留 keyed 行；初次无行才显示整表加载。调用者必须在权限失效和资源范围变化时清除不可继续展示的数据。
- 上传待确认、公司治理、授权记录、已办审批、审计日志、项目知识选择、个人知识库、人员管理、模型管理和入库管理分别修正整块加载、选择清空或临时失败清空内容；失权仍清除受限信息。入库已有的局部作业轮询继续使用其请求序号与防重入机制。
- 已检查通知铃铛、上传会话、知识详情和知识列表：已有局部更新/请求序号或初次加载区分，保留这些机制。ErrorBoundary 的显式故障恢复和身份切换重新鉴权仍需重建对应上下文。

## 验收约束

1. 后台更新不能卸载同一条记录的详情、折叠用户展开内容、重置滚动或覆盖输入。
2. 临时请求失败提示上次结果可能过时；未保存草稿仍保留。失去权限不能继续显示旧受限数据。
3. 删除记录不删除资产和维护问题；活动记录须先取消，令牌失效阻断迟到结果。
4. 超长正文与超大同库集合持续分批，完成全部覆盖后才完成该资产；失败窗口可重试且不重做已完成前缀。
5. 全文缺章/仅封面必须基于全部分段汇总；片段缺失不能当全文缺失。
