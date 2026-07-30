import { useState } from "react";
import ConfirmDialog from "../../components/ConfirmDialog";
import type { PendingIngestItemDTO } from "../../types/ingest";
import type { UploadFlow } from "./useUploadFlow";
import { isPendingTaskActionable } from "./PendingSelectAll";

export default function PendingBatchActions({
  tasks,
  flow,
}: {
  tasks: PendingIngestItemDTO[];
  flow: UploadFlow;
}) {
  const [rejectOpen, setRejectOpen] = useState(false);
  const selectedTasks = tasks.filter(
    (task) => flow.batchSelection.includes(task.id) && isPendingTaskActionable(task, flow),
  );
  if (selectedTasks.length === 0) return null;

  return (
    <>
      <div className="upload77-batch-actions">
        <button
          className="btn-primary"
          disabled={flow.batchBusy}
          onClick={() => void flow.handleBatchConfirm(selectedTasks)}
          type="button"
        >
          {flow.batchBusy && flow.batchOperation === "confirm"
            ? "正在逐条确认"
            : `批量确认入库（${selectedTasks.length}）`}
        </button>
        <button
          className="btn-secondary upload77-batch-reject"
          disabled={flow.batchBusy}
          onClick={() => setRejectOpen(true)}
          type="button"
        >
          批量拒绝入库（{selectedTasks.length}）
        </button>
      </div>
      <ConfirmDialog
        open={rejectOpen}
        title={`永久拒绝选中的 ${selectedTasks.length} 条待确认任务？`}
        description={`确认后将严格逐条删除这 ${selectedTasks.length} 条待确认任务，操作不可恢复，且不会创建知识资产。`}
        confirmText="确认永久拒绝"
        busyText="正在逐条拒绝"
        busy={flow.batchBusy && flow.batchOperation === "reject"}
        danger
        onCancel={() => setRejectOpen(false)}
        onConfirm={() => {
          setRejectOpen(false);
          void flow.handleBatchReject(selectedTasks);
        }}
      />
    </>
  );
}
