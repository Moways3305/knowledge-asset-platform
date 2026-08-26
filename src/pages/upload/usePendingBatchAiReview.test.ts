import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PendingIngestItemDTO } from "../../types/ingest";
import { usePendingBatchAiReview } from "./usePendingBatchAiReview";

const commands = vi.hoisted(() => ({
  fetchIngestAiResult: vi.fn(),
  retryIngestTask: vi.fn(),
}));
vi.mock("../../api/ingest", () => commands);

const task = { id: "task-generic", source_file_name: "generic.pdf" } as PendingIngestItemDTO;

describe("usePendingBatchAiReview", () => {
  beforeEach(() => {
    commands.fetchIngestAiResult.mockReset();
    commands.retryIngestTask.mockReset();
  });

  it("loads on demand and normalizes a saved draft", async () => {
    commands.fetchIngestAiResult.mockResolvedValue({
      status: "completed",
      suggested_title: " 建议标题 ",
      suggested_summary: " 安全摘要 ",
      suggested_key_points: [" 要点 ", ""],
      suggested_tags: [" 标签 "],
    });
    const { result } = renderHook(() => usePendingBatchAiReview());
    await act(async () => result.current.open(task));
    await waitFor(() => expect(result.current.form?.title).toBe(" 建议标题 "));

    let saved: ReturnType<typeof result.current.saveDraft> = null;
    act(() => {
      saved = result.current.saveDraft();
    });
    expect(saved).toEqual({
      taskId: task.id,
      draft: {
        title: "建议标题",
        one_liner: "",
        summary: "安全摘要",
        key_points: ["要点"],
        tags: ["标签"],
      },
    });
    expect(result.current.task).toBeNull();
  });

  it("claims retry before reloading and ignores a cancelled response", async () => {
    let resolve!: (value: unknown) => void;
    commands.fetchIngestAiResult.mockReturnValue(new Promise((done) => (resolve = done)));
    const { result } = renderHook(() => usePendingBatchAiReview());
    let opening!: Promise<void>;
    act(() => {
      opening = result.current.open(task, true);
    });
    await waitFor(() => expect(commands.retryIngestTask).toHaveBeenCalledWith(task.id));
    act(() => result.current.cancel());
    await act(async () => {
      resolve({ status: "completed", suggested_title: "late", suggested_summary: "late" });
      await opening;
    });
    expect(result.current.task).toBeNull();
    expect(result.current.form).toBeNull();
  });
});
