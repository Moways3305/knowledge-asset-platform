import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../api/http";
import { fetchPendingIngestTasks } from "../../api/ingest";
import type { PendingIngestItemDTO } from "../../types/ingest";
import type { PathBranch } from "./uploadConstants";

export function usePendingIngest(activePath: PathBranch) {
  const pendingRequestRef = useRef(0);
  const localPendingRequestRef = useRef(0);
  const batchRunRef = useRef<number | null>(null);
  const [pendingTasks, setPendingTasks] = useState<PendingIngestItemDTO[]>([]);
  const [pendingLoading, setPendingLoading] = useState(true);
  const [pendingError, setPendingError] = useState<string | null>(null);
  const [localPendingTasks, setLocalPendingTasks] = useState<PendingIngestItemDTO[]>([]);
  const [localPendingLoading, setLocalPendingLoading] = useState(true);
  const [localPendingError, setLocalPendingError] = useState<string | null>(null);
  const [batchSelection, setBatchSelection] = useState<string[]>([]);
  const [batchStatus, setBatchStatus] = useState<
    Record<string, "waiting" | "processing" | "success" | "failed">
  >({});
  const [batchBusy, setBatchBusy] = useState(false);
  const [batchOperation, setBatchOperation] = useState<"confirm" | "reject" | null>(null);
  const [batchErrors, setBatchErrors] = useState<Record<string, string>>({});
  // Presence identifies a per-row permanent-reject failure; the boolean controls
  // whether an automatic retry is safe. Confirmation errors are intentionally absent.
  const [batchRejectRetryability, setBatchRejectRetryability] = useState<Record<string, boolean>>(
    {},
  );

  const reconcileBatchState = useCallback((tasks: PendingIngestItemDTO[]) => {
    // The active batch owns its row progress until it finishes. A refresh made
    // by that batch must not erase the terminal result it has just produced.
    if (batchRunRef.current !== null) return;
    const pendingIds = new Set(
      tasks
        .filter((task) => task.can_batch_confirm || task.can_batch_reject)
        .map((task) => task.id),
    );
    setBatchSelection((current) => current.filter((id) => pendingIds.has(id)));
    setBatchStatus((current) =>
      Object.fromEntries(
        Object.entries(current).filter(([id, state]) => pendingIds.has(id) && state === "failed"),
      ),
    );
    setBatchErrors((current) =>
      Object.fromEntries(Object.entries(current).filter(([id]) => pendingIds.has(id))),
    );
    setBatchRejectRetryability((current) =>
      Object.fromEntries(Object.entries(current).filter(([id]) => pendingIds.has(id))),
    );
  }, []);

  const loadPending = useCallback(async () => {
    const requestId = ++pendingRequestRef.current;
    setPendingLoading(true);
    setPendingError(null);
    setBatchSelection([]);
    try {
      const tasks = await fetchPendingIngestTasks("path_a_wecom");
      if (pendingRequestRef.current === requestId) {
        setPendingTasks(tasks);
        reconcileBatchState(tasks);
      }
    } catch (error) {
      if (pendingRequestRef.current === requestId) {
        setPendingError(
          error instanceof ApiError ? error.message : "待确认任务暂时无法加载，请稍后重试",
        );
      }
    } finally {
      if (pendingRequestRef.current === requestId) setPendingLoading(false);
    }
  }, [reconcileBatchState]);

  const loadLocalPending = useCallback(async () => {
    const requestId = ++localPendingRequestRef.current;
    setLocalPendingLoading(true);
    setLocalPendingError(null);
    setBatchSelection([]);
    try {
      const tasks = await fetchPendingIngestTasks("path_b_upload");
      if (localPendingRequestRef.current === requestId) {
        setLocalPendingTasks(tasks);
        reconcileBatchState(tasks);
      }
    } catch (error) {
      if (localPendingRequestRef.current === requestId) {
        setLocalPendingError(
          error instanceof ApiError ? error.message : "待确认任务暂时无法加载，请稍后重试",
        );
      }
    } finally {
      if (localPendingRequestRef.current === requestId) setLocalPendingLoading(false);
    }
  }, [reconcileBatchState]);

  useEffect(() => {
    if (activePath === "a") void loadPending();
    else void loadLocalPending();
  }, [activePath, loadLocalPending, loadPending]);

  useEffect(
    () => () => {
      pendingRequestRef.current += 1;
      localPendingRequestRef.current += 1;
      batchRunRef.current = null;
    },
    [],
  );

  const toggleBatchTask = useCallback(
    (id: string) => {
      if (batchBusy) return;
      setBatchSelection((current) =>
        current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
      );
    },
    [batchBusy],
  );

  const setBatchTasksSelected = useCallback(
    (ids: string[], selected: boolean) => {
      if (batchBusy) return;
      setBatchSelection((current) => {
        if (!selected) return current.filter((id) => !ids.includes(id));
        return Array.from(new Set([...current, ...ids]));
      });
    },
    [batchBusy],
  );

  const cancelBatchRun = useCallback(() => {
    batchRunRef.current = null;
    setBatchBusy(false);
    setBatchOperation(null);
  }, []);

  return {
    pendingTasks,
    setPendingTasks,
    pendingLoading,
    setPendingLoading,
    pendingError,
    localPendingTasks,
    setLocalPendingTasks,
    localPendingLoading,
    setLocalPendingLoading,
    localPendingError,
    loadPending,
    loadLocalPending,
    batchSelection,
    setBatchSelection,
    batchStatus,
    setBatchStatus,
    batchBusy,
    setBatchBusy,
    batchOperation,
    setBatchOperation,
    batchErrors,
    setBatchErrors,
    batchRejectRetryability,
    setBatchRejectRetryability,
    batchRunRef,
    pendingRequestRef,
    localPendingRequestRef,
    toggleBatchTask,
    setBatchTasksSelected,
    cancelBatchRun,
  };
}
