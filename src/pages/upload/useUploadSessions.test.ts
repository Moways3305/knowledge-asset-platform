import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { UploadSessionDTO } from "../../types/ingest";
import { useUploadFlow } from "./useUploadFlow";

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
  fetchUploadSessions: vi.fn(),
  fetchUploadSession: vi.fn(),
  retryUploadSessionItem: vi.fn(),
  removeUploadSessionItem: vi.fn(),
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
  beforeEach(() => {
    ingest.createUploadSession.mockReset();
    ingest.fetchUploadSessions.mockReset().mockResolvedValue([]);
    ingest.fetchUploadSession.mockReset();
    ingest.retryUploadSessionItem.mockReset();
    ingest.removeUploadSessionItem.mockReset();
    ingest.fetchPendingIngestTasks.mockReset().mockResolvedValue([]);
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

  it("submits all 700 selected files once and renders four stable batches", async () => {
    ingest.createUploadSession.mockResolvedValue(session(700));
    const { result } = renderHook(() => useUploadFlow());
    const files = Array.from(
      { length: 700 },
      (_, index) => new File(["x"], `file-${index}.txt`, { type: "text/plain" }),
    );

    act(() => result.current.handleFileDrop(files));
    await waitFor(() => expect(ingest.createUploadSession).toHaveBeenCalledTimes(1));
    expect(ingest.createUploadSession.mock.calls[0][0].files).toHaveLength(700);
    await waitFor(() => expect(result.current.localUploadQueue).toHaveLength(700));
    expect(
      [1, 2, 3, 4].map(
        (batch) =>
          result.current.localUploadQueue.filter((item) => item.batchNumber === batch).length,
      ),
    ).toEqual([200, 200, 200, 100]);
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
    await waitFor(() => expect(ingest.fetchUploadSession).toHaveBeenCalledTimes(1));
    const requestedId = ingest.createUploadSession.mock.calls[0][0].sessionId;
    expect(requestedId).toMatch(/^[0-9a-f-]{36}$/i);
    expect(ingest.fetchUploadSession).toHaveBeenCalledWith(requestedId);
    await waitFor(() => expect(result.current.uploadSession?.id).toBe("session-safe-id"));
  });
});
