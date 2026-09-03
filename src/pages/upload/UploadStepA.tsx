import { RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";
import { formatBeijingTime } from "../../utils/time";
import { formatFileSize, pendingStatusLabel } from "./uploadConstants";
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
    batchRejectRetryability = {},
    toggleBatchTask,
    setBatchTasksSelected,
    handleBatchReject,
  } = flow;
  const [filter, setFilter] = useState<"all" | "actionable" | "processing" | "failed">("all");
  const [page, setPage] = useState(0);
  const filteredTasks = useMemo(
    () =>
      pendingTasks.filter((task) => {
        if (filter === "actionable") return task.can_batch_confirm || task.can_batch_reject;
        if (filter === "processing") return task.status === "processing";
        if (filter === "failed") return task.status === "failed";
        return true;
      }),
    [filter, pendingTasks],
  );
  const pageSize = 8;
  const safePage = Math.min(page, Math.max(0, Math.ceil(filteredTasks.length / pageSize) - 1));
  const visibleTasks = filteredTasks.slice(safePage * pageSize, (safePage + 1) * pageSize);

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
        <>
          <div className="upload77-list-tools" aria-label="待确认资料筛选">
            <div>
              {[
                ["all", "全部"],
                ["actionable", "可处理"],
                ["processing", "处理中"],
                ["failed", "失败"],
              ].map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  className={filter === value ? "is-active" : ""}
                  aria-pressed={filter === value}
                  onClick={() => {
                    setFilter(value as "all" | "actionable" | "processing" | "failed");
                    setPage(0);
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
            <span>{filteredTasks.length} 项</span>
          </div>
          <div className="upload77-table-wrap">
            <table className="upload77-table upload77-pending-table">
              <colgroup>
                <col className="upload77-pending-col-select" />
                <col className="upload77-pending-col-result" />
                <col className="upload77-pending-col-file" />
                <col className="upload77-pending-col-status" />
                <col className="upload77-pending-col-subject" />
                <col className="upload77-pending-col-generation" />
                <col className="upload77-pending-col-time" />
              </colgroup>
              <thead>
                <tr>
                  <th className="upload77-batch-col">
                    <PendingSelectAll tasks={pendingTasks} flow={flow} />
                  </th>
                  <th>处理结果</th>
                  <th>文件</th>
                  <th>状态</th>
                  <th>建议主题</th>
                  <th>建议生成状态</th>
                  <th>时间</th>
                </tr>
              </thead>
              <tbody>
                {visibleTasks.map((task) => {
                  const selected = taskId === task.id;
                  const loadingThis = selected && flowState === "processing";
                  const itemStatus = batchStatus[task.id];
                  const rejectFailure = Object.prototype.hasOwnProperty.call(
                    batchRejectRetryability,
                    task.id,
                  );
                  return (
                    <tr key={task.id} className={selected ? "is-selected" : ""}>
                      <td className="upload77-batch-col">
                        <input
                          aria-label={`选择 ${task.source_file_name}`}
                          checked={batchSelection.includes(task.id)}
                          disabled={
                            !isPendingTaskActionable(task, flow) ||
                            (rejectFailure && !batchRejectRetryability[task.id])
                          }
                          onChange={() => toggleBatchTask(task.id)}
                          type="checkbox"
                        />
                      </td>
                      <td className="upload77-batch-result">
                        {itemStatus && (
                          <BatchTaskProgress
                            state={itemStatus}
                            actionLabel={
                              batchOperation === "reject" || rejectFailure ? "批量拒绝" : "批量确认"
                            }
                          />
                        )}
                        {batchErrors[task.id] && (
                          <span className="upload77-queue-error">{batchErrors[task.id]}</span>
                        )}
                        {itemStatus === "failed" &&
                          (!rejectFailure || batchRejectRetryability[task.id]) && (
                            <button
                              className="upload77-retry-link"
                              disabled={batchBusy}
                              onClick={() => {
                                if (batchOperation === "reject" || rejectFailure) {
                                  void handleBatchReject([task]);
                                } else {
                                  setBatchTasksSelected([task.id], true);
                                }
                              }}
                              type="button"
                            >
                              {batchOperation === "reject" || rejectFailure
                                ? "重试"
                                : "重新选择目标"}
                            </button>
                          )}
                      </td>
                      <td>
                        <button
                          className="upload77-task-select"
                          title={task.source_file_name}
                          onClick={() => {
                            if (!loadingThis && !batchBusy) void handleSelectPendingTask(task);
                          }}
                          disabled={loadingThis || batchBusy}
                          type="button"
                        >
                          {task.source_file_name}
                        </button>
                        <small className="upload77-pending-file-meta">
                          {task.source_file_name.split(".").pop()?.toUpperCase() ?? "未知类型"} ·{" "}
                          {task.source_file_size == null
                            ? "大小未提供"
                            : formatFileSize(task.source_file_size)}
                        </small>
                      </td>
                      <td>
                        <span className={`upload77-status upload77-status-${task.status}`}>
                          {pendingStatusLabel[task.status] ?? "待处理"}
                        </span>
                      </td>
                      <td>
                        <span
                          className="upload77-pending-truncate"
                          title={task.suggested_title ?? undefined}
                        >
                          {task.suggested_title || "—"}
                        </span>
                      </td>
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
            {filteredTasks.length === 0 && <div className="upload77-state">当前筛选下没有资料</div>}
            {filteredTasks.length > pageSize && (
              <div className="upload77-list-pager" aria-label="企微待确认分页">
                <span>
                  显示 {safePage * pageSize + 1}–
                  {Math.min((safePage + 1) * pageSize, filteredTasks.length)} /{" "}
                  {filteredTasks.length}
                </span>
                <div>
                  <button
                    type="button"
                    disabled={safePage === 0}
                    onClick={() => setPage((current) => Math.max(0, current - 1))}
                  >
                    上一页
                  </button>
                  <button
                    type="button"
                    disabled={(safePage + 1) * pageSize >= filteredTasks.length}
                    onClick={() => setPage((current) => current + 1)}
                  >
                    下一页
                  </button>
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );
}
