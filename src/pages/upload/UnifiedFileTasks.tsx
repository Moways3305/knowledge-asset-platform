import { useState } from "react";
import ConfirmDialog from "../../components/ConfirmDialog";
import PagePagination from "../../components/PagePagination";
import BatchTaskProgress from "./BatchTaskProgress";
import PendingBatchActions from "./PendingBatchActions";
import PendingSelectAll, {
  isPendingTaskActionable,
  pendingSelectionReason,
} from "./PendingSelectAll";
import { commandErrorMessage, retryIngestTask } from "./pendingBatchCommands";
import { formatFileSize, pendingStatusLabel } from "./uploadConstants";
import { PROCESSING_STAGE_LABELS, queueFailureReason } from "./uploadTaskLabels";
import type { UploadFlow } from "./useUploadFlow";
import type { LocalUploadQueueItem } from "./uploadIntake";
import type { PendingIngestItemDTO } from "../../types/ingest";
import { formatBeijingTime } from "../../utils/time";

type Row = { id: string; local?: LocalUploadQueueItem; task?: PendingIngestItemDTO };
type Filter = "all" | "active" | "ready" | "failed" | "completed" | "cancelled";

export function mergeFileTasks(
  local: LocalUploadQueueItem[],
  pending: PendingIngestItemDTO[],
): Row[] {
  const byTask = new Map(pending.map((task) => [task.id, task]));
  const seen = new Set<string>();
  const rows = local.map((item) => {
    const task = item.ingestTaskId ? byTask.get(item.ingestTaskId) : undefined;
    if (task) seen.add(task.id);
    return { id: item.id, local: item, task };
  });
  return [
    ...rows,
    ...pending.filter((task) => !seen.has(task.id)).map((task) => ({ id: task.id, task })),
  ];
}

function state(row: Row): Filter {
  if (row.local?.status === "cancelled") return "cancelled";
  if (row.local && ["completed", "duplicate_skipped"].includes(row.local.status))
    return "completed";
  if (row.task) {
    if (row.task.status === "failed") return "failed";
    if (row.task.status === "pending_confirmation") return "ready";
    return "active";
  }
  if (row.local?.status === "failed") return "failed";
  if (row.local?.status === "awaiting_confirmation") return "ready";
  return "active";
}

export default function UnifiedFileTasks({ flow }: { flow: UploadFlow }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [page, setPage] = useState(1);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const rows = mergeFileTasks(flow.localUploadQueue, flow.localPendingTasks);
  const filtered = rows.filter((row) => filter === "all" || state(row) === filter);
  const totalPages = Math.max(1, Math.ceil(filtered.length / 8));
  const currentPage = Math.min(page, totalPages);
  const visible = filtered.slice((currentPage - 1) * 8, currentPage * 8);
  const tasks = filtered.flatMap((row) =>
    row.task && !["completed", "cancelled"].includes(state(row)) ? [row.task] : [],
  );
  const perform = async (id: string, action: () => unknown | Promise<unknown>) => {
    if (busy) return;
    setBusy(id);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(commandErrorMessage(err, "操作未完成，请重试。"));
    } finally {
      setBusy(null);
    }
  };
  const retry = (row: Row) =>
    perform(row.id, async () => {
      if (row.local) await flow.retryLocalUpload(row.local.id);
      else if (row.task) {
        await retryIngestTask(row.task.id);
        await flow.loadLocalPending();
      }
    });
  return (
    <section className="upload77-wecom upload-file-tasks" aria-labelledby="local-pending-title">
      <div className="upload77-section-head">
        <div>
          <h2 id="local-pending-title">文件任务</h2>
          <p>上传、处理、确认入库在同一列表中查看；文件传完不代表已入库。</p>
        </div>
        <div className="upload77-section-actions">
          <button
            className="btn-secondary"
            onClick={() => void flow.loadLocalPending()}
            disabled={flow.localPendingLoading}
          >
            刷新
          </button>
          {flow.localUploadQueue.some((item) =>
            ["queued", "uploading", "processing"].includes(item.status),
          ) && (
            <button
              className="btn-secondary"
              onClick={() => setCancelOpen(true)}
              disabled={flow.isCancellingUpload}
            >
              取消本批上传
            </button>
          )}
          {rows.some((row) => state(row) === "failed" && row.local?.retryable !== false) && (
            <button
              className="btn-secondary"
              disabled={Boolean(busy)}
              onClick={() =>
                void perform("retry-all", async () => {
                  let failures = 0;
                  for (const row of rows.filter((entry) => state(entry) === "failed")) {
                    try {
                      if (row.local && row.local.retryable !== false)
                        await flow.retryLocalUpload(row.local.id);
                      else if (!row.local && row.task?.retryable)
                        await retryIngestTask(row.task.id);
                    } catch {
                      failures += 1;
                    }
                  }
                  await flow.loadLocalPending();
                  if (failures) setError(`${failures} 项重试请求未完成，其余文件已继续处理。`);
                })
              }
            >
              {busy === "retry-all" ? "正在重试失败项…" : "重试可恢复失败项"}
            </button>
          )}
          <PendingBatchActions tasks={tasks} flow={flow} />
          {flow.localUploadQueue.some((item) => item.status === "failed") && (
            <button
              className="btn-secondary"
              disabled={Boolean(busy)}
              onClick={() => void perform("remove-failed", flow.removeFailedLocalUploads)}
            >
              清理全部失败项
            </button>
          )}
          {pendingSelectionReason(tasks, flow) && (
            <span className="upload77-selection-reason">{pendingSelectionReason(tasks, flow)}</span>
          )}
        </div>
      </div>
      {flow.uploadSession && (
        <details className="upload-session-details">
          <summary>本次传输详情</summary>
          <p aria-label="上传会话进度">总数{flow.uploadSession.total_files}</p>
          <p>
            已上传 {flow.uploadSession.uploaded_files ?? 0}/{flow.uploadSession.total_files}，第{" "}
            {flow.uploadSession.uploaded_batches ?? 0}/{flow.uploadSession.total_batches} 批
          </p>
        </details>
      )}
      <div className="upload77-list-tools" aria-label="文件任务筛选">
        <div>
          {(
            [
              ["all", "全部"],
              ["active", "传输/处理中"],
              ["ready", "待确认"],
              ["failed", "失败"],
              ["completed", "已处理"],
              ["cancelled", "已取消"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              aria-pressed={filter === value}
              className={filter === value ? "is-active" : ""}
              onClick={() => {
                setFilter(value);
                setPage(1);
              }}
            >
              {label}{" "}
              {value === "all" ? rows.length : rows.filter((row) => state(row) === value).length}
            </button>
          ))}
        </div>
      </div>
      {(error || flow.localPendingError) && (
        <p role="alert" className="upload77-queue-error">
          {error || flow.localPendingError}
        </p>
      )}
      <div className="upload77-table-wrap">
        <table className="upload77-table upload-unified-table">
          <thead>
            <tr>
              <th>
                <PendingSelectAll tasks={tasks} flow={flow} />
              </th>
              <th>文件</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((row) => {
              const { task, local } = row;
              const rowState = state(row);
              const name = local?.fileName ?? task?.source_file_name ?? "文件";
              const stage = task?.processing_stage ?? local?.processingStage;
              const label =
                rowState === "cancelled"
                  ? "已取消"
                  : local?.status === "duplicate_skipped"
                    ? "因重复已跳过"
                    : rowState === "completed"
                      ? "处理已结束"
                      : rowState === "ready"
                        ? "待确认入库"
                        : rowState === "failed"
                          ? task || local?.ingestTaskId
                            ? "处理失败"
                            : "上传失败"
                          : stage && PROCESSING_STAGE_LABELS[stage]
                            ? PROCESSING_STAGE_LABELS[stage]
                            : task
                              ? (pendingStatusLabel[task.status] ?? "等待处理")
                              : local?.status === "uploading"
                                ? "上传中"
                                : local?.status === "queued"
                                  ? local.ingestTaskId
                                    ? "等待处理"
                                    : "等待上传"
                                  : "处理中";
              const canAct = task && !["completed", "cancelled"].includes(rowState);
              const size = task?.source_file_size ?? local?.fileSize;
              return (
                <tr key={row.id}>
                  <td>
                    {canAct && (
                      <input
                        type="checkbox"
                        aria-label={`选择 ${name}`}
                        checked={flow.batchSelection.includes(task.id)}
                        disabled={
                          !isPendingTaskActionable(task, flow) ||
                          flow.batchRejectRetryability?.[task.id] === false
                        }
                        onChange={() => flow.toggleBatchTask(task.id)}
                      />
                    )}
                  </td>
                  <td>
                    <button
                      className="upload77-task-select"
                      title={name}
                      disabled={!canAct || flow.batchBusy}
                      onClick={() => task && void flow.handleSelectPendingTask(task)}
                    >
                      {name}
                    </button>
                    <small className="upload77-pending-file-meta">
                      {name.split(".").pop()?.toUpperCase()} ·{" "}
                      {size == null ? "大小未提供" : formatFileSize(size)}
                    </small>
                    {local?.sameNameWarning && (
                      <span className="upload77-name-warning">同名，需确认</span>
                    )}
                  </td>
                  <td className="upload77-batch-result">
                    <span
                      className={`upload77-status upload77-status-${task?.status ?? local?.status}`}
                    >
                      {label}
                    </span>
                    {rowState === "failed" && (
                      <p className="upload77-queue-error">
                        {queueFailureReason(
                          task?.error_message ?? local?.error ?? null,
                          stage ?? undefined,
                          task?.error_type ?? local?.errorCode,
                        )}
                      </p>
                    )}
                    {task && flow.batchStatus[task.id] && (
                      <BatchTaskProgress
                        state={flow.batchStatus[task.id]}
                        actionLabel={flow.batchOperation === "reject" ? "批量拒绝" : "批量确认"}
                      />
                    )}
                    {task && flow.batchErrors[task.id] && (
                      <p className="upload77-queue-error">{flow.batchErrors[task.id]}</p>
                    )}
                    {task &&
                      flow.batchStatus[task.id] === "failed" &&
                      flow.batchRejectRetryability?.[task.id] !== false && (
                        <button
                          className="upload77-retry-link"
                          disabled={flow.batchBusy}
                          onClick={() => {
                            if (
                              flow.batchOperation === "reject" ||
                              flow.batchRejectRetryability?.[task.id] === true
                            )
                              void flow.handleBatchReject([task]);
                            else flow.setBatchTasksSelected([task.id], true);
                          }}
                        >
                          {flow.batchOperation === "reject" ||
                          flow.batchRejectRetryability?.[task.id] === true
                            ? "重试"
                            : "重新选择目标"}
                        </button>
                      )}
                  </td>
                  <td>
                    <div className="upload-file-row-actions">
                      {canAct && rowState === "ready" && (
                        <button
                          className="btn-primary"
                          disabled={flow.batchBusy}
                          onClick={() => void flow.handleSelectPendingTask(task)}
                        >
                          确认入库
                        </button>
                      )}
                      {rowState === "failed" &&
                        (local ? local.retryable !== false : task?.retryable) && (
                          <button
                            className="upload77-retry-link"
                            disabled={Boolean(busy)}
                            onClick={() => void retry(row)}
                          >
                            {busy === row.id ? "正在重试…" : "重试处理"}
                          </button>
                        )}
                      {local && rowState === "failed" && (
                        <button
                          className="upload77-retry-link"
                          disabled={Boolean(busy)}
                          onClick={() =>
                            void perform(row.id, () => flow.removeLocalUpload(local.id))
                          }
                        >
                          移除
                        </button>
                      )}
                      <details>
                        <summary>详情</summary>
                        <p
                          className="upload77-pending-truncate"
                          title={task?.suggested_title ?? undefined}
                        >
                          {task?.suggested_title || "暂无内容建议"}
                        </p>
                        {task && (
                          <p>
                            {task.suggestion_generation_status === "generated"
                              ? "建议已生成"
                              : task.suggestion_generation_status === "needs_manual_completion"
                                ? "需人工补全"
                                : "建议待校正"}
                          </p>
                        )}
                        <p>{task?.suggestion_generation_reason}</p>
                        {local?.transportBatchNumber && (
                          <p>传输第 {local.transportBatchNumber} 批</p>
                        )}
                        {task?.retry_count || local?.retryCount ? (
                          <p>第 {task?.retry_count ?? local?.retryCount} 次恢复</p>
                        ) : null}
                        <p>
                          {formatBeijingTime(
                            task?.last_progress_at ??
                              local?.lastAttemptAt ??
                              task?.updated_at ??
                              "",
                          )}
                        </p>
                      </details>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <div className="upload77-state">
            {flow.localPendingLoading ? "正在加载文件任务…" : "暂无文件任务，请先选择文件上传。"}
          </div>
        )}
      </div>
      {totalPages > 1 && (
        <PagePagination
          className="upload77-list-pager"
          ariaLabel="文件任务分页"
          page={currentPage}
          totalPages={totalPages}
          onPageChange={setPage}
          summary={`共 ${filtered.length} 项`}
        />
      )}
      <ConfirmDialog
        open={cancelOpen}
        title="取消本批上传？"
        description="停止尚未完成的上传和处理，已完成的文件不受影响。"
        busy={flow.isCancellingUpload}
        onCancel={() => setCancelOpen(false)}
        onConfirm={() =>
          void perform("cancel", async () => {
            await flow.cancelCurrentUpload();
            setCancelOpen(false);
          })
        }
        confirmText="确认取消"
        portal
      />
    </section>
  );
}
