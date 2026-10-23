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
  replaceUploadSessionItemBytes: vi.fn(),
  recordUploadTransportFailure: vi.fn(),
  completeUploadSession: vi.fn(),
}));
const options = {
  activePath: "b" as const,
  loadLocalPending: vi.fn().mockResolvedValue(undefined),
  setLocalPendingTasks: vi.fn(),
};
let server: UploadSessionDTO;
beforeEach(() => {
  vi.resetAllMocks();
  server = {
    id: "restored",
    status: "active",
    total_files: 3,
    total_batches: 2,
    uploaded_files: 1,
    uploaded_batches: 1,
    upload_completed: false,
    completed_files: 0,
    processing_files: 1,
    waiting_files: 2,
    failed_files: 0,
    current_batch_number: 1,
    created_at: "",
    updated_at: "",
    items: [0, 1, 2].map((i) => ({
      id: `row-${i}`,
      ordinal: i,
      batch_number: 1,
      transport_batch_number: i === 0 ? 1 : 2,
      ingest_task_id: i === 0 ? "existing-task" : null,
      file_name: `${i}.txt`,
      file_size: 4,
      file_type: "text/plain",
      status: i === 0 ? "awaiting_confirmation" : "waiting_upload",
      bytes_available: i === 0,
      error_code: null,
      error_message: null,
      retryable: false,
      same_name_warning: false,
    })),
  };
  vi.mocked(api.fetchUploadSessions).mockImplementation(async () => [server]);
  vi.mocked(api.fetchUploadSession).mockImplementation(async () => server);
  vi.mocked(api.replaceUploadSessionItemBytes).mockImplementation(async ({ itemId }) => {
    server = {
      ...server,
      uploaded_files: (server.uploaded_files ?? 0) + 1,
      items: server.items.map((item) =>
        item.id === itemId
          ? {
              ...item,
              ingest_task_id: `task-${itemId}`,
              status: "awaiting_confirmation",
              bytes_available: true,
            }
          : item,
      ),
    };
    return server;
  });
  vi.mocked(api.recordUploadTransportFailure).mockImplementation(
    async (_id, _items, _code, batch) => {
      expect(batch?.index).toBe(server.uploaded_batches);
      server = { ...server, uploaded_batches: (batch?.index ?? 0) + 1 };
      return server;
    },
  );
  vi.mocked(api.completeUploadSession).mockImplementation(async () => {
    server = { ...server, upload_completed: true };
    return server;
  });
});
async function restore() {
  const hook = renderHook(() => useUploadIntake(options));
  await waitFor(() => expect(hook.result.current.uploadSession?.id).toBe("restored"));
  return hook;
}
const original = (i: number) => new File(["test"], `${i}.txt`, { type: "text/plain" });

it("reselects exact rows after refresh and completes only after all missing bytes are durable", async () => {
  const { result, unmount } = await restore();
  expect(result.current.localUploadQueue.map((item) => item.needsReselection)).toEqual([
    false,
    true,
    true,
  ]);
  const first = original(1);
  await act(async () => result.current.reselectLocalUpload("row-1", first));
  expect(api.completeUploadSession).not.toHaveBeenCalled();
  expect(api.recordUploadTransportFailure).not.toHaveBeenCalled();
  await act(async () => result.current.reselectLocalUpload("row-2", original(2)));
  expect(api.replaceUploadSessionItemBytes).toHaveBeenCalledTimes(2);
  expect(api.replaceUploadSessionItemBytes).toHaveBeenNthCalledWith(1, {
    sessionId: "restored",
    itemId: "row-1",
    file: first,
  });
  expect(api.initializeUploadSession).not.toHaveBeenCalled();
  expect(api.appendUploadSessionBatch).not.toHaveBeenCalled();
  expect(api.recordUploadTransportFailure).toHaveBeenCalledWith(
    "restored",
    ["row-1", "row-2"],
    "network_interrupted",
    { id: "restored:1", index: 1 },
  );
  expect(api.completeUploadSession).toHaveBeenCalledTimes(1);
  expect(result.current.uploadSession?.upload_completed).toBe(true);
  expect(result.current.localUploadQueue[0].ingestTaskId).toBe("existing-task");
  expect(new Set(result.current.localUploadQueue.map((item) => item.ingestTaskId)).size).toBe(3);
  unmount();
});

it.each([new File(["test"], "wrong.txt"), new File(["different"], "1.txt")])(
  "rejects a manifest mismatch without sending bytes",
  async (file) => {
    const { result, unmount } = await restore();
    await act(async () => {
      await expect(result.current.reselectLocalUpload("row-1", file)).rejects.toThrow(
        "原清单不一致",
      );
    });
    expect(api.replaceUploadSessionItemBytes).not.toHaveBeenCalled();
    expect(result.current.localUploadQueue[1].needsReselection).toBe(true);
    unmount();
  },
);

it.each(["received", "cancelled", "completed"])(
  "does not reselect a %s task or session",
  async (condition) => {
    if (condition === "cancelled") server.status = "cancelled";
    if (condition === "completed") server.upload_completed = true;
    const { result, unmount } = await restore();
    await act(async () => {
      await expect(
        result.current.reselectLocalUpload(
          condition === "received" ? "row-0" : "row-1",
          original(condition === "received" ? 0 : 1),
        ),
      ).rejects.toThrow("不可补传");
    });
    expect(api.replaceUploadSessionItemBytes).not.toHaveBeenCalled();
    unmount();
  },
);

it("coalesces repeated confirmation of the same file", async () => {
  const { result, unmount } = await restore();
  await act(async () => {
    const first = result.current.reselectLocalUpload("row-1", original(1));
    const second = result.current.reselectLocalUpload("row-1", original(1));
    expect(second).toBe(first);
    await first;
  });
  expect(api.replaceUploadSessionItemBytes).toHaveBeenCalledTimes(1);
  unmount();
});

it("keeps local bytes retryable after an unconfirmed transfer and uses the same row", async () => {
  const { result, unmount } = await restore();
  vi.mocked(api.replaceUploadSessionItemBytes).mockRejectedValueOnce(new Error("network lost"));
  const file = original(1);
  await act(async () => {
    await expect(result.current.reselectLocalUpload("row-1", file)).rejects.toThrow("network lost");
  });
  expect(result.current.localUploadQueue[1]).toMatchObject({
    file,
    status: "failed",
    retryable: true,
  });
  await act(async () => result.current.retryLocalUpload("row-1"));
  expect(api.replaceUploadSessionItemBytes).toHaveBeenCalledTimes(2);
  expect(api.replaceUploadSessionItemBytes).toHaveBeenLastCalledWith({
    sessionId: "restored",
    itemId: "row-1",
    file,
  });
  expect(result.current.localUploadQueue[1].ingestTaskId).toBe("task-row-1");
  expect(api.initializeUploadSession).not.toHaveBeenCalled();
  unmount();
});

it("keeps uploaded task identity when completion fails and retries only finalization", async () => {
  const { result, unmount } = await restore();
  vi.mocked(api.completeUploadSession).mockRejectedValueOnce(new Error("completion response lost"));
  await act(async () => result.current.reselectLocalUpload("row-1", original(1)));
  await act(async () => {
    await expect(result.current.reselectLocalUpload("row-2", original(2))).rejects.toThrow(
      "response lost",
    );
  });
  expect(result.current.localUploadQueue[2].ingestTaskId).toBe("task-row-2");
  expect(result.current.localUploadQueue[2].status).toBe("awaiting_confirmation");
  await act(async () => result.current.finishRecoveredUpload());
  expect(api.replaceUploadSessionItemBytes).toHaveBeenCalledTimes(2);
  expect(api.completeUploadSession).toHaveBeenCalledTimes(2);
  expect(result.current.uploadSession?.upload_completed).toBe(true);
  unmount();
});

it("does not finalize after unmount while file transfer is pending", async () => {
  let resolve!: (value: UploadSessionDTO) => void;
  vi.mocked(api.replaceUploadSessionItemBytes).mockReturnValue(
    new Promise((done) => {
      resolve = done;
    }),
  );
  const { result, unmount } = await restore();
  let transfer!: Promise<void>;
  act(() => {
    transfer = result.current.reselectLocalUpload("row-1", original(1));
  });
  await waitFor(() => expect(api.replaceUploadSessionItemBytes).toHaveBeenCalledTimes(1));
  unmount();
  resolve(server);
  await transfer;
  expect(api.completeUploadSession).not.toHaveBeenCalled();
  expect(api.recordUploadTransportFailure).not.toHaveBeenCalled();
});
