import { RefreshCw } from "lucide-react";
import { formatBeijingTime } from "../../utils/time";
import { pendingStatusLabel } from "./uploadConstants";
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
                <th>文件</th>
                <th>状态</th>
                <th>建议标题</th>
                <th>置信度</th>
                <th>时间</th>
              </tr>
            </thead>
            <tbody>
              {pendingTasks.map((task) => {
                const selected = taskId === task.id;
                const loadingThis = selected && flowState === "processing";
                return (
                  <tr key={task.id} className={selected ? "is-selected" : ""}>
                    <td>
                      <button
                        className="upload77-task-select"
                        onClick={() => {
                          if (!loadingThis) void handleSelectPendingTask(task);
                        }}
                        disabled={loadingThis}
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
                    <td>
                      {task.confidence == null ? "—" : `${Math.round(task.confidence * 100)}%`}
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
