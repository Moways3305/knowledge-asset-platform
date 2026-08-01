import { RefreshCw } from "lucide-react";
import { formatBeijingTime } from "../../utils/time";
import { pendingStatusLabel } from "./uploadConstants";
import BatchTaskProgress from "./BatchTaskProgress";
import PendingBatchActions from "./PendingBatchActions";
import PendingSelectAll, {
  isPendingTaskActionable,
  pendingSelectionReason,
} from "./PendingSelectAll";
import type { UploadFlow } from "./useUploadFlow";

export default function UploadStepA({ flow }: { flow: UploadFlow }) {
  const {
    pendingTasks,
    pendingLoading,
    pendingError,
    loadPending,
    handleSelectPendingTask,
    taskId,
    flowState,
    batchSelection,
    batchStatus,
    batchBusy,
    batchOperation,
    batchErrors,
    toggleBatchTask,
    setBatchTasksSelected,
    handleBatchReject,
  } = flow;

  return (
    <section className="upload77-wecom" aria-labelledby="wecom-pending-title">
      <div className="upload77-section-head">
        <div>
          <h2 id="wecom-pending-title">企微微盘待确认</h2>
          <p>选择一项待确认资料，进入同一核对与入库流程。</p>
        </div>
        <button
          className="btn-secondary upload77-icon-button"
          onClick={() => void loadPending()}
          disabled={pendingLoading}
          type="button"
        >
          <RefreshCw size={15} aria-hidden="true" />
          {pendingLoading ? "刷新中" : "刷新"}
        </button>
        <PendingBatchActions tasks={pendingTasks} flow={flow} />
        {pendingSelectionReason(pendingTasks, flow) && (
          <span className="upload77-selection-reason" role="status">
            {pendingSelectionReason(pendingTasks, flow)}
          </span>
        )}
      </div>

      {pendingLoading ? (
        <div className="upload77-state" role="status">
          正在加载待确认资料…
        </div>
      ) : pendingError ? (
        <div className="upload77-state upload77-state-error" role="alert">
          <span>{pendingError}</span>
          <button className="btn-secondary" onClick={() => void loadPending()} type="button">
            重试
          </button>
        </div>
      ) : pendingTasks.length === 0 ? (
        <div className="upload77-state">
          <strong>暂无待确认资料</strong>
          <span>当前没有需要你处理的企微微盘文件。</span>
        </div>
      ) : (
        <div className="upload77-table-wrap">
          <table className="upload77-table">
            <thead>
              <tr>
                <th className="upload77-batch-col">
                  <PendingSelectAll tasks={pendingTasks} flow={flow} />
                </th>
                <th>文件</th>
                <th>状态</th>
                <th>建议标题</th>
                <th>建议生成状态</th>
                <th>时间</th>
              </tr>
            </thead>
            <tbody>
              {pendingTasks.map((task) => {
                const selected = taskId === task.id;
                const loadingThis = selected && flowState === "processing";
                const itemStatus = batchStatus[task.id];
                return (
                  <tr key={task.id} className={selected ? "is-selected" : ""}>
                    <td className="upload77-batch-col">
                      <input
                        aria-label={`选择 ${task.source_file_name}`}
                        checked={batchSelection.includes(task.id)}
                        disabled={!isPendingTaskActionable(task, flow)}
                        onChange={() => toggleBatchTask(task.id)}
                        type="checkbox"
                      />
                      {itemStatus && (
                        <BatchTaskProgress
                          state={itemStatus}
                          actionLabel={
                            batchOperation === "reject" || batchErrors[task.id]
                              ? "批量拒绝"
                              : "批量确认"
                          }
                        />
                      )}
                      {batchErrors[task.id] && (
                        <span className="upload77-queue-error">{batchErrors[task.id]}</span>
                      )}
                      {itemStatus === "failed" && (
                        <button
                          className="upload77-retry-link"
                          disabled={batchBusy}
                          onClick={() => {
                            if (batchOperation === "reject" || batchErrors[task.id]) {
                              void handleBatchReject([task]);
                            } else {
                              setBatchTasksSelected([task.id], true);
                            }
                          }}
                          type="button"
                        >
                          {batchOperation === "reject" || batchErrors[task.id]
                            ? "重试"
                            : "重新选择目标"}
                        </button>
                      )}
                    </td>
                    <td>
                      <button
                        className="upload77-task-select"
                        onClick={() => {
                          if (!loadingThis && !batchBusy) void handleSelectPendingTask(task);
                        }}
                        disabled={loadingThis || batchBusy}
                        type="button"
                      >
                        {task.source_file_name}
                      </button>
                    </td>
                    <td>
                      <span className={`upload77-status upload77-status-${task.status}`}>
                        {pendingStatusLabel[task.status] ?? "待处理"}
                      </span>
                    </td>
                    <td>{task.suggested_title || "—"}</td>
                    <td title={task.suggestion_generation_reason}>
                      {task.suggestion_generation_status === "generated"
                        ? "建议已生成"
                        : task.suggestion_generation_status === "needs_manual_completion"
                          ? "需人工补全"
                          : "建议待校正"}
                    </td>
                    <td>{task.created_at ? formatBeijingTime(task.created_at) : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
