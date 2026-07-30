import { useState } from "react";
import ConfirmDialog from "../../components/ConfirmDialog";
import type { PendingIngestItemDTO } from "../../types/ingest";
import type { UploadFlow } from "./useUploadFlow";
import { isPendingTaskActionable } from "./PendingSelectAll";
import type { TargetLibrary } from "./uploadConstants";

export default function PendingBatchActions({
  tasks,
  flow,
}: {
  tasks: PendingIngestItemDTO[];
  flow: UploadFlow;
}) {
  const [rejectOpen, setRejectOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [targetLibrary, setTargetLibrary] = useState<TargetLibrary>("");
  const [targetProjectId, setTargetProjectId] = useState("");
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
          onClick={() => {
            setTargetLibrary("");
            setTargetProjectId("");
            setConfirmOpen(true);
          }}
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
        open={confirmOpen}
        title={`确认入库 ${selectedTasks.length} 项资料`}
        description={
          targetLibrary
            ? `将把 ${selectedTasks.length} 项资料入库到同一个目标；来源规则锁定项仍由服务端逐项校验。`
            : "请选择一个明确的目标知识库；取消不会创建资产或改变任务状态。"
        }
        confirmText="确认批量入库"
        busyText="正在逐条确认"
        busy={flow.batchBusy && flow.batchOperation === "confirm"}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => {
          if (!targetLibrary || (targetLibrary === "project" && !targetProjectId)) return;
          setConfirmOpen(false);
          void flow.handleBatchConfirm(
            selectedTasks,
            targetLibrary as Exclude<TargetLibrary, "">,
            targetProjectId || undefined,
          );
        }}
      >
        <label className="upload77-field">
          <span>目标知识库</span>
          <select
            aria-label="批量入库目标知识库"
            value={targetLibrary}
            onChange={(event) => {
              setTargetLibrary(event.target.value as TargetLibrary);
              setTargetProjectId("");
            }}
          >
            <option value="">请选择目标知识库</option>
            <option value="personal">个人知识库</option>
            {(flow.projects ?? []).length > 0 && <option value="project">项目知识库</option>}
            {flow.canUseCompanyTarget && <option value="company">公司知识库</option>}
          </select>
        </label>
        {targetLibrary === "project" && (
          <label className="upload77-field">
            <span>具体项目</span>
            <select
              aria-label="批量入库目标项目"
              value={targetProjectId}
              onChange={(event) => setTargetProjectId(event.target.value)}
            >
              <option value="">请选择目标项目</option>
              {(flow.projects ?? []).map((project) => (
                <option key={project.projectId} value={project.projectId}>
                  {project.projectName}
                </option>
              ))}
            </select>
          </label>
        )}
      </ConfirmDialog>
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
