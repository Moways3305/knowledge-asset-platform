import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { UploadSessionDTO } from "../../types/ingest";
import { useUploadFlow } from "./useUploadFlow";
import { mergeFileTasks } from "./UnifiedFileTasks";
import type { PendingIngestItemDTO } from "../../types/ingest";
import { fetchAuthMe } from "../../api/auth";

vi.mock("../../hooks/useModelSelection", () => ({
  useModelSelection: () => ({
    loading: false,
    loaded: true,
    weknoraDisabled: false,
    defaultMissing: false,
    embeddingOptions: [],
    rerankOptions: [],
    embeddingRef: "",
    rerankRef: "",
    setEmbeddingRef: vi.fn(),
    setRerankRef: vi.fn(),
    reload: vi.fn(),
    blockSubmit: false,
  }),
}));

vi.mock("../../api/auth", () => ({
  fetchAuthMe: vi.fn().mockResolvedValue({ projects: [] }),
}));

const ingest = vi.hoisted(() => ({
  createUploadSession: vi.fn(),
  initializeUploadSession: undefined,
  appendUploadSessionBatch: undefined,
  completeUploadSession: undefined,
  recordUploadTransportFailure: undefined,
  replaceUploadSessionItemBytes: undefined,
  fetchUploadSessions: vi.fn(),
  fetchUploadSession: vi.fn(),
  retryUploadSessionItem: vi.fn(),
  removeUploadSessionItem: vi.fn(),
  removeFailedUploadSessionItems: vi.fn(),
  fetchPendingIngestTasks: vi.fn(),
  createIngestUpload: vi.fn(),
  fetchIngestAiResult: vi.fn(),
  fetchIngestTaskStatus: vi.fn(),
  confirmIngest: vi.fn(),
  deletePendingTask: vi.fn(),
}));
vi.mock("../../api/ingest", () => ingest);

function session(total: number, status: "completed" | "waiting" = "completed"): UploadSessionDTO {
  return {
    id: "session-safe-id",
    status: status === "completed" ? "completed" : "active",
    total_files: total,
    completed_files: status === "completed" ? total : 0,
    processing_files: 0,
    waiting_files: status === "waiting" ? total : 0,
    failed_files: 0,
    current_batch_number: status === "waiting" ? 1 : null,
    total_batches: Math.ceil(total / 200),
    created_at: "2026-07-30T00:00:00Z",
    updated_at: "2026-07-30T00:00:00Z",
    items: Array.from({ length: total }, (_, ordinal) => ({
      id: `item-${ordinal}`,
      ordinal,
      batch_number: Math.floor(ordinal / 200) + 1,
      file_name: `file-${ordinal}.txt`,
      file_size: 1,
      file_type: "text/plain",
      status,
      error_code: null,
      error_message: null,
      same_name_warning: ordinal === 1,
      retryable: false,
    })),
  };
}

describe("useUploadFlow persistent upload sessions", () => {
  afterEach(() => vi.restoreAllMocks());
  beforeEach(() => {
    vi.mocked(fetchAuthMe).mockResolvedValue({
      userId: "test-user",
      name: "Test",
      email: "test@example.com",
      companyRoles: ["consultant"],
      activeCompanyRole: "consultant",
      isBusinessUser: true,
      canDiscoverL5: false,
      projects: [],
    });
    ingest.createUploadSession.mockReset();
    ingest.fetchUploadSessions.mockReset().mockResolvedValue([]);
    ingest.fetchUploadSession.mockReset();
    ingest.fetchIngestTaskStatus.mockReset();
    ingest.retryUploadSessionItem.mockReset();
    ingest.removeUploadSessionItem.mockReset();
    ingest.fetchPendingIngestTasks.mockReset().mockResolvedValue([]);
  });

  it("polls a processing session once instead of every task and stops after unmount", async () => {
    const uploaded = session(25, "waiting");
    uploaded.items.forEach((item, index) => {
      item.status = "processing";
      item.ingest_task_id = `task-${index}`;
    });
    const callbacks: Array<() => void> = [];
    vi.spyOn(window, "setInterval").mockImplementation((callback) => {
      callbacks.push(callback as () => void);
      return callbacks.length;
    });
    const clear = vi.spyOn(window, "clearInterval");
    ingest.fetchUploadSessions.mockResolvedValue([uploaded]);
    let resolve!: (value: UploadSessionDTO) => void;
    ingest.fetchUploadSession.mockImplementation(
      () =>
        new Promise<UploadSessionDTO>((done) => {
          resolve = done;
        }),
    );
    const { result, unmount } = renderHook(() => useUploadFlow());
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.localUploadQueue).toHaveLength(25);
    await act(async () => {
      callbacks.forEach((callback) => callback());
    });
    await act(async () => {
      callbacks.forEach((callback) => callback());
    });
    expect(ingest.fetchUploadSession).toHaveBeenCalledTimes(1);
    expect(ingest.fetchIngestTaskStatus).not.toHaveBeenCalled();
    unmount();
    expect(clear).toHaveBeenCalled();
    expect(ingest.fetchUploadSession.mock.calls[0][1].aborted).toBe(true);
    await act(async () => resolve(session(25)));
    expect(ingest.fetchUploadSession).toHaveBeenCalledTimes(1);
  });

  it("expires a stuck poll and ignores its late response without unlocking the replacement", async () => {
    const uploaded = session(1, "waiting");
    ingest.fetchUploadSessions.mockResolvedValue([uploaded]);
    const intervals: Array<() => void> = [];
    const deadlines: Array<() => void> = [];
    const realTimeout = window.setTimeout.bind(window);
    vi.spyOn(window, "setInterval").mockImplementation((callback) => {
      intervals.push(callback as () => void);
      return intervals.length;
    });
    vi.spyOn(window, "setTimeout").mockImplementation((callback, delay, ...args) => {
      if (delay === 30_000) {
        deadlines.push(callback as () => void);
        return 100000 + deadlines.length;
      }
      return realTimeout(callback, delay, ...args);
    });
    const resolves: Array<(value: UploadSessionDTO) => void> = [];
    ingest.fetchUploadSession.mockImplementation(
      () => new Promise<UploadSessionDTO>((resolve) => resolves.push(resolve)),
    );
    const { result, unmount } = renderHook(() => useUploadFlow());
    await act(async () => {
      await Promise.resolve();
    });
    await act(async () => intervals.forEach((callback) => callback()));
    expect(ingest.fetchUploadSession).toHaveBeenCalledTimes(1);
    await act(async () => deadlines[0]());
    expect(ingest.fetchUploadSession.mock.calls[0][1].aborted).toBe(true);
    await act(async () => intervals.forEach((callback) => callback()));
    expect(ingest.fetchUploadSession).toHaveBeenCalledTimes(2);
    await act(async () => resolves[0](session(1)));
    expect(result.current.uploadSession?.status).toBe("active");
    await act(async () => intervals.forEach((callback) => callback()));
    expect(ingest.fetchUploadSession).toHaveBeenCalledTimes(2);
    await act(async () => resolves[1](session(1)));
    expect(result.current.uploadSession?.status).toBe("completed");
    unmount();
  });

  it("restores the latest server-owned session after remount", async () => {
    ingest.fetchUploadSessions.mockResolvedValue([session(2)]);
    const { result } = renderHook(() => useUploadFlow());

    await waitFor(() => expect(result.current.localUploadQueue).toHaveLength(2));
    expect(result.current.uploadSession?.id).toBe("session-safe-id");
    expect(result.current.localUploadQueue[1]).toMatchObject({
      batchNumber: 1,
      sameNameWarning: true,
      status: "completed",
    });
  });

  it("restores task identity so 43 uploaded files remain 43 merged rows", async () => {
    const uploaded = session(43);
    uploaded.items.forEach((item, index) => {
      item.ingest_task_id = `task-${index}`;
    });
    ingest.fetchUploadSessions.mockResolvedValue([uploaded]);
    const { result } = renderHook(() => useUploadFlow());
    await waitFor(() => expect(result.current.localUploadQueue).toHaveLength(43));
    const pending = uploaded.items.map((item) => ({
      id: item.ingest_task_id!,
      source_file_name: item.file_name,
    })) as PendingIngestItemDTO[];
    expect(result.current.localUploadQueue[0].ingestTaskId).toBe("task-0");
    expect(mergeFileTasks(result.current.localUploadQueue, pending)).toHaveLength(43);
  });

  it("treats a completed session item as authoritative over stale parse failure metadata", async () => {
    const completedWithStaleError = session(1);
    completedWithStaleError.items[0].error_code = "file_parse_failed";
    completedWithStaleError.items[0].error_message = "旧解析失败";
    ingest.fetchUploadSessions.mockResolvedValue([completedWithStaleError]);

    const { result } = renderHook(() => useUploadFlow());

    await waitFor(() => expect(result.current.localUploadQueue).toHaveLength(1));
    expect(result.current.localUploadQueue[0]).toMatchObject({
      status: "completed",
      error: null,
    });
  });

  it("restores legacy processing batches without presenting them as transport batches", async () => {
    ingest.createUploadSession.mockResolvedValue(session(700));
    const { result } = renderHook(() => useUploadFlow());
    const files = Array.from(
      { length: 700 },
      (_, index) => new File(["x"], `file-${index}.txt`, { type: "text/plain" }),
    );

    act(() => result.current.handleFileDrop(files));
    expect(ingest.createUploadSession).not.toHaveBeenCalled();
    expect(ingest.createIngestUpload).not.toHaveBeenCalled();
    await act(async () => result.current.confirmPendingSelection());
    await waitFor(() => expect(ingest.createUploadSession).toHaveBeenCalledTimes(1));
    expect(ingest.createUploadSession.mock.calls[0][0].files).toHaveLength(700);
    await waitFor(() => expect(result.current.localUploadQueue).toHaveLength(700));
    expect(
      [1, 2, 3, 4].map(
        (batch) =>
          result.current.localUploadQueue.filter((item) => item.batchNumber === batch).length,
      ),
    ).toEqual([200, 200, 200, 100]);
    expect(result.current.intakeFeedback?.batchSizes).toEqual([]);
  });

  it("does not send macOS metadata bytes and keeps a real hidden document", async () => {
    ingest.createUploadSession.mockResolvedValue(session(3));
    const { result } = renderHook(() => useUploadFlow());
    const files = [
      new File(["metadata"], "._foo.md", { type: "text/markdown" }),
      new File(["finder"], ".DS_Store"),
      new File(["real"], ".notes.md", { type: "text/markdown" }),
    ];

    act(() => result.current.handleFileDrop(files));
    expect(ingest.createUploadSession).not.toHaveBeenCalled();
    expect(ingest.createIngestUpload).not.toHaveBeenCalled();
    await act(async () => result.current.confirmPendingSelection());
    await waitFor(() => expect(ingest.createUploadSession).toHaveBeenCalledTimes(1));
    const request = ingest.createUploadSession.mock.calls[0][0];
    expect(request.files.map((file: File) => file.name)).toEqual([".notes.md"]);
    expect(request.rejectedFiles).toEqual([
      expect.objectContaining({ file_name: "._foo.md", error_code: "macos_metadata" }),
      expect.objectContaining({ file_name: ".DS_Store", error_code: "macos_metadata" }),
    ]);
  });

  it("recovers the exact idempotent session after a lost create response", async () => {
    ingest.createUploadSession.mockRejectedValue(new Error("network interrupted"));
    ingest.fetchUploadSession.mockResolvedValue(session(2));
    const { result } = renderHook(() => useUploadFlow());
    const files = [
      new File(["a"], "a.txt", { type: "text/plain" }),
      new File(["b"], "b.txt", { type: "text/plain" }),
    ];

    act(() => result.current.handleFileDrop(files));
    expect(ingest.createUploadSession).not.toHaveBeenCalled();
    expect(ingest.createIngestUpload).not.toHaveBeenCalled();
    await act(async () => result.current.confirmPendingSelection());
    await waitFor(() => expect(ingest.fetchUploadSession).toHaveBeenCalledTimes(1));
    const requestedId = ingest.createUploadSession.mock.calls[0][0].sessionId;
    expect(requestedId).toMatch(/^[0-9a-f-]{36}$/i);
    expect(ingest.fetchUploadSession).toHaveBeenCalledWith(requestedId);
    await waitFor(() => expect(result.current.uploadSession?.id).toBe("session-safe-id"));
  });
});
