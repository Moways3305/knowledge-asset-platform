import { useEffect, useMemo, useRef } from "react";
import type { PendingIngestItemDTO } from "../../types/ingest";
import type { UploadFlow } from "./useUploadFlow";

export function isPendingTaskActionable(task: PendingIngestItemDTO, flow: UploadFlow): boolean {
  return task.status === "pending_confirmation" && !flow.batchStatus[task.id] && !flow.batchBusy;
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

  return (
    <input
      ref={inputRef}
      aria-label="全选当前可处理的待确认项"
      checked={checked}
      disabled={flow.batchBusy || actionableIds.length === 0}
      onChange={(event) => flow.setBatchTasksSelected(actionableIds, event.target.checked)}
      type="checkbox"
    />
  );
}
