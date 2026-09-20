import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import * as api from "../../api/ingest";
import type { UploadSessionDTO } from "../../types/ingest";
import { useUploadIntake } from "./useUploadIntake";

vi.mock("../../api/ingest", async (original) => ({
  ...(await original<typeof api>()),
  fetchUploadSessions: vi.fn(),
  fetchUploadSession: vi.fn(),
  initializeUploadSession: vi.fn(),
  appendUploadSessionBatch: vi.fn(),
  completeUploadSession: vi.fn(),
}));
const oldSession: UploadSessionDTO = {
  id: "old",
  status: "completed",
  total_files: 1,
  total_batches: 1,
  completed_files: 1,
  processing_files: 0,
  waiting_files: 0,
  failed_files: 0,
  current_batch_number: null,
  upload_completed: true,
  uploaded_files: 1,
  created_at: "",
  updated_at: "",
  items: [
    {
      id: "old-item",
      ingest_task_id: "old-task",
      ordinal: 0,
      batch_number: 1,
      file_name: "old.txt",
      file_size: 1,
      file_type: "text/plain",
      status: "completed",
      error_code: null,
      error_message: null,
      same_name_warning: false,
      retryable: false,
    },
  ],
};
const options = {
  activePath: "b" as const,
  loadLocalPending: vi.fn().mockResolvedValue(undefined),
  setLocalPendingTasks: vi.fn(),
};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.fetchUploadSessions).mockResolvedValue([oldSession]);
});

it("starts 1301 files after a finished session, preserving sequential ten-file transport", async () => {
  let current: UploadSessionDTO;
  let inFlight = 0;
  let maxInFlight = 0;
  vi.mocked(api.initializeUploadSession).mockImplementation(async (input) => {
    current = {
      ...oldSession,
      id: input.sessionId,
      status: "active",
      upload_completed: false,
      total_files: input.manifest.length,
      total_batches: input.totalTransportBatches,
      completed_files: 0,
      uploaded_files: 0,
      uploaded_batches: 0,
      items: input.manifest.map((item, index) => ({
        ...oldSession.items[0],
        id: `new-${index}`,
        ingest_task_id: null,
        ordinal: index,
        file_name: item.file_name,
        status: "waiting_upload",
        transport_batch_number: (item.transport_batch_index ?? 0) + 1,
      })),
    };
    return current;
  });
  vi.mocked(api.appendUploadSessionBatch).mockImplementation(async (input) => {
    maxInFlight = Math.max(maxInFlight, ++inFlight);
    expect(input.batchIndex).toBe(current.uploaded_batches);
    expect(input.files.length).toBeLessThanOrEqual(10);
    await Promise.resolve();
    current = {
      ...current,
      uploaded_batches: input.batchIndex + 1,
      items: current.items.map((item) =>
        input.itemIds.includes(item.id)
          ? { ...item, status: "awaiting_confirmation", ingest_task_id: `task-${item.ordinal}` }
          : item,
      ),
    };
    --inFlight;
    return current;
  });
  vi.mocked(api.completeUploadSession).mockImplementation(async () => ({
    ...current,
    upload_completed: true,
    status: "completed",
  }));
  const { result, unmount } = renderHook(() => useUploadIntake(options));
  await waitFor(() => expect(result.current.uploadSession?.id).toBe("old"));
  act(() =>
    result.current.handleFileDrop(
      Array.from({ length: 1301 }, (_, i) => new File(["x"], `${i}.txt`)),
    ),
  );
  act(() => result.current.confirmPendingSelection());
  await waitFor(() => expect(api.completeUploadSession).toHaveBeenCalledTimes(1), {
    timeout: 10000,
  });
  expect(api.appendUploadSessionBatch).toHaveBeenCalledTimes(131);
  expect(maxInFlight).toBe(1);
  expect(result.current.localUploadQueue).toHaveLength(1301);
  expect(result.current.localUploadQueue.some((item) => item.id === "old-item")).toBe(false);
  unmount();
});

it("keeps the existing session intact when selection exceeds the advertised limit", async () => {
  const { result, unmount } = renderHook(() => useUploadIntake(options));
  await waitFor(() => expect(result.current.uploadSession?.id).toBe("old"));
  act(() =>
    result.current.handleFileDrop(Array.from({ length: 5001 }, () => new File(["x"], "x.txt"))),
  );
  act(() => result.current.confirmPendingSelection());
  expect(api.initializeUploadSession).not.toHaveBeenCalled();
  expect(result.current.folderDropNotice).toContain("5000");
  expect(result.current.uploadSession?.id).toBe("old");
  unmount();
});

it("waits for completed history before starting a new batch whose initialization fails", async () => {
  let restore!: (sessions: UploadSessionDTO[]) => void;
  vi.mocked(api.fetchUploadSessions).mockReturnValue(
    new Promise((resolve) => {
      restore = resolve;
    }),
  );
  vi.mocked(api.initializeUploadSession).mockRejectedValue(new Error("offline"));
  vi.mocked(api.fetchUploadSession).mockRejectedValue(new Error("not created"));
  const { result, unmount } = renderHook(() => useUploadIntake(options));
  act(() => result.current.handleFileDrop([new File(["x"], "new.txt")]));
  act(() => result.current.confirmPendingSelection());
  expect(api.initializeUploadSession).not.toHaveBeenCalled();
  expect(result.current.pendingSelection?.items).toHaveLength(1);
  await act(async () => restore([oldSession]));
  act(() => result.current.confirmPendingSelection());
  await waitFor(() => expect(result.current.localUploadQueue[0]?.status).toBe("failed"));
  expect(result.current.uploadSession).toBeNull();
  expect(result.current.localUploadQueue.map((item) => item.fileName)).toEqual(["new.txt"]);
  act(() => result.current.removeFailedLocalUploads());
  expect(result.current.localUploadQueue).toHaveLength(0);
  unmount();
});

it("restores unfinished transport without letting an early confirmation hide it", async () => {
  let restore!: (sessions: UploadSessionDTO[]) => void;
  vi.mocked(api.fetchUploadSessions).mockReturnValue(
    new Promise((resolve) => {
      restore = resolve;
    }),
  );
  const { result, unmount } = renderHook(() => useUploadIntake(options));
  act(() => result.current.handleFileDrop([new File(["x"], "new.txt")]));
  act(() => result.current.confirmPendingSelection());
  expect(result.current.folderDropNotice).toContain("正在恢复");
  await act(async () =>
    restore([
      {
        ...oldSession,
        status: "active",
        upload_completed: false,
        items: [{ ...oldSession.items[0], status: "waiting_upload", ingest_task_id: null }],
      },
    ]),
  );
  act(() => result.current.confirmPendingSelection());
  expect(api.initializeUploadSession).not.toHaveBeenCalled();
  expect(result.current.uploadSession?.id).toBe("old");
  expect(result.current.localUploadQueue.map((item) => item.id)).toEqual(["old-item"]);
  expect(result.current.pendingSelection?.items).toHaveLength(1);
  expect(result.current.folderDropNotice).toContain("尚未传输完成");
  unmount();
});

it("does not treat a failed recovery as an empty history", async () => {
  vi.mocked(api.fetchUploadSessions).mockRejectedValue(new Error("offline"));
  const { result, unmount } = renderHook(() => useUploadIntake(options));
  await act(async () => {
    await Promise.resolve();
  });
  act(() => result.current.handleFileDrop([new File(["x"], "new.txt")]));
  act(() => result.current.confirmPendingSelection());
  expect(api.initializeUploadSession).not.toHaveBeenCalled();
  expect(result.current.folderDropNotice).toContain("无法确认");
  expect(result.current.pendingSelection?.items).toHaveLength(1);
  unmount();
});
