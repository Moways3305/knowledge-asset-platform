import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiError } from "../../api/http";
import { fetchPendingIngestTasks } from "../../api/ingest";
import type { PendingIngestItemDTO } from "../../types/ingest";
import { usePendingIngest } from "./usePendingIngest";

vi.mock("../../api/ingest", () => ({ fetchPendingIngestTasks: vi.fn() }));
const task = { id: "task", can_batch_confirm: true } as PendingIngestItemDTO;
beforeEach(() => vi.resetAllMocks());

it("keeps pending rows and selection while another uploaded file completes", async () => {
  vi.mocked(fetchPendingIngestTasks).mockResolvedValueOnce([task]);
  const { result } = renderHook(() => usePendingIngest("b"));
  await waitFor(() => expect(result.current.localPendingTasks).toEqual([task]));
  act(() => result.current.toggleBatchTask(task.id));
  let complete!: (items: PendingIngestItemDTO[]) => void;
  vi.mocked(fetchPendingIngestTasks).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        complete = resolve;
      }),
  );
  let pending!: Promise<void>;
  act(() => {
    pending = result.current.loadLocalPending();
  });
  expect(result.current.localPendingLoading).toBe(false);
  expect(result.current.localPendingTasks).toEqual([task]);
  expect(result.current.batchSelection).toEqual([task.id]);
  await act(async () => {
    complete([task, { ...task, id: "new" }]);
    await pending;
  });
  expect(result.current.batchSelection).toEqual([task.id]);
  expect(result.current.localPendingTasks).toHaveLength(2);
  vi.mocked(fetchPendingIngestTasks).mockRejectedValueOnce(new ApiError(503, "网络暂不可用"));
  await act(async () => result.current.loadLocalPending());
  expect(result.current.localPendingTasks).toHaveLength(2);
  expect(result.current.localPendingError).toBe("网络暂不可用");
  vi.mocked(fetchPendingIngestTasks).mockRejectedValueOnce(new ApiError(403, "权限已变更"));
  await act(async () => result.current.loadLocalPending());
  expect(result.current.localPendingTasks).toHaveLength(0);
});
