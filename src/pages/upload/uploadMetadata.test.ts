import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { localDateFromMs } from "../../api/ingest";
import { useUploadIntake } from "./useUploadIntake";

const api = vi.hoisted(() => ({
  initializeUploadSession: vi.fn(() => new Promise<never>(() => {})),
  fetchUploadSessions: vi.fn().mockResolvedValue([]),
}));
vi.mock("../../api/ingest", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/ingest")>()),
  ...api,
}));

describe("upload source metadata", () => {
  it("sends the original lastModified date in each manifest item, not a filename date", async () => {
    const modified = new Date(2026, 8, 7, 11, 30).getTime();
    const file = new File(["content"], "report_20180801.txt", {
      type: "text/plain",
      lastModified: modified,
    });
    const options = {
      activePath: "b" as const,
      loadLocalPending: vi.fn().mockResolvedValue(undefined),
      setLocalPendingTasks: vi.fn(),
    };
    const { result, unmount } = renderHook(() => useUploadIntake(options));
    act(() => result.current.handleFileDrop([file]));
    await act(async () => result.current.confirmPendingSelection());
    await waitFor(() =>
      expect(api.initializeUploadSession).toHaveBeenCalledWith(
        expect.objectContaining({
          manifest: [
            expect.objectContaining({
              file_name: "report_20180801.txt",
              formed_on: "2026-09-07",
            }),
          ],
        }),
      ),
    );
    unmount();
  });

  it("does not fabricate a date from invalid timestamps", () => {
    expect(localDateFromMs(0)).toBeNull();
    expect(localDateFromMs(Number.NaN)).toBeNull();
    expect(localDateFromMs(1e20)).toBeNull();
  });
});
