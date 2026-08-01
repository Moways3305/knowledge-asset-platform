import { useEffect, useMemo, useRef } from "react";
import type { PendingIngestItemDTO } from "../../types/ingest";
import type { UploadFlow } from "./useUploadFlow";

export function isPendingTaskActionable(task: PendingIngestItemDTO, flow: UploadFlow): boolean {
  return task.status === "pending_confirmation" && !flow.batchBusy;
}

export default function PendingSelectAll({
  tasks,
  flow,
}: {
  tasks: PendingIngestItemDTO[];
  flow: UploadFlow;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const actionableIds = useMemo(
    () => tasks.filter((task) => isPendingTaskActionable(task, flow)).map((task) => task.id),
    [flow, tasks],
  );
  const selectedCount = actionableIds.filter((id) => flow.batchSelection.includes(id)).length;
  const checked = actionableIds.length > 0 && selectedCount === actionableIds.length;
  const indeterminate = selectedCount > 0 && !checked;

  useEffect(() => {
    if (inputRef.current) inputRef.current.indeterminate = indeterminate;
  }, [indeterminate]);

  const disabledReason = flow.batchBusy
    ? "正在处理批次，完成后可继续选择"
    : actionableIds.length === 0
      ? "当前没有可批量处理的待确认项"
      : null;

  return (
    <>
      <input
        ref={inputRef}
        aria-label="全选当前可处理的待确认项"
        checked={checked}
        disabled={disabledReason !== null}
        onChange={(event) => flow.setBatchTasksSelected(actionableIds, event.target.checked)}
        type="checkbox"
      />
      {disabledReason && <span className="upload77-selection-reason">{disabledReason}</span>}
    </>
  );
}
