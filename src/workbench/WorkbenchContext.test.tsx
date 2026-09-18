import { act, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchWorkbenchOverview } from "../api/workbench";
import type { WorkbenchOverviewDTO } from "../types/workbench";
import { WorkbenchProvider, useWorkbench } from "./WorkbenchContext";
import { TASK_STATUS_INVALIDATED_EVENT } from "./taskStatusEvents";

vi.mock("../api/workbench", () => ({ fetchWorkbenchOverview: vi.fn() }));
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ status: "authenticated" }),
}));

function overview(count: number): WorkbenchOverviewDTO {
  return {
    task_center: {
      status: "available",
      error_code: null,
      summary: { needs_action: count, running: 0, attention: 0, completed_today: 0 },
      priority_items: [],
      my_tasks: [],
      running_jobs: [],
      attention_items: [],
      recent_completed: [],
    },
    todos: { status: "empty", error_code: null, items: [], total: 0 },
    operations: { status: "empty", error_code: null, data: null },
    projects: { status: "empty", error_code: null, items: [], total: 0 },
    recent_activity: { status: "empty", error_code: null, items: [], total: 0 },
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

function Probe() {
  const { overview: value } = useWorkbench();
  return <output>{value?.task_center.summary.needs_action ?? "loading"}</output>;
}

describe("WorkbenchProvider refresh contract", () => {
  beforeEach(() => vi.mocked(fetchWorkbenchOverview).mockReset());
  afterEach(() => vi.restoreAllMocks());

  it.each(["resolve", "reject"])(
    "drains queued refresh on timeout without focus, ignoring late %s",
    async (settlement) => {
      const nativeTimeout = window.setTimeout.bind(window);
      let expire!: () => void;
      vi.spyOn(window, "setTimeout").mockImplementation((handler, delay, ...args) => {
        if (delay === 30_000 && typeof handler === "function") expire = handler as () => void;
        return nativeTimeout(handler, delay, ...args);
      });
      const old = deferred<WorkbenchOverviewDTO>();
      vi.mocked(fetchWorkbenchOverview)
        .mockReturnValueOnce(old.promise)
        .mockResolvedValue(overview(2));
      const view = render(
        <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <WorkbenchProvider>
            <Probe />
          </WorkbenchProvider>
        </MemoryRouter>,
      );
      const signal = vi.mocked(fetchWorkbenchOverview).mock.calls[0][0]!;
      act(() => {
        window.dispatchEvent(new Event(TASK_STATUS_INVALIDATED_EVENT));
        window.dispatchEvent(new Event(TASK_STATUS_INVALIDATED_EVENT));
      });
      vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
      await act(async () => {
        expire();
      });
      expect(signal.aborted).toBe(true);
      expect(fetchWorkbenchOverview).toHaveBeenCalledTimes(2);
      await act(async () => {
        if (settlement === "resolve") old.resolve(overview(99));
        else old.reject(new Error("late abort"));
      });
      expect(fetchWorkbenchOverview).toHaveBeenCalledTimes(2);
      expect(screen.getByText("2")).toBeInTheDocument();
      vi.mocked(fetchWorkbenchOverview).mockReturnValue(new Promise(() => {}));
      act(() => window.dispatchEvent(new Event(TASK_STATUS_INVALIDATED_EVENT)));
      const calls = vi.mocked(fetchWorkbenchOverview).mock.calls;
      const active = calls[calls.length - 1][0]!;
      act(() => window.dispatchEvent(new Event(TASK_STATUS_INVALIDATED_EVENT)));
      view.unmount();
      expect(active.aborted).toBe(true);
      act(() => expire());
      expect(fetchWorkbenchOverview).toHaveBeenCalledTimes(3);
    },
  );

  it("coalesces task invalidations behind an in-flight request and rejects its stale result", async () => {
    const first = deferred<WorkbenchOverviewDTO>();
    const latest = deferred<WorkbenchOverviewDTO>();
    vi.mocked(fetchWorkbenchOverview)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(latest.promise);

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <WorkbenchProvider>
          <Probe />
        </WorkbenchProvider>
      </MemoryRouter>,
    );
    expect(fetchWorkbenchOverview).toHaveBeenCalledTimes(1);

    act(() => window.dispatchEvent(new Event(TASK_STATUS_INVALIDATED_EVENT)));
    act(() => window.dispatchEvent(new Event(TASK_STATUS_INVALIDATED_EVENT)));
    expect(fetchWorkbenchOverview).toHaveBeenCalledTimes(1);
    await act(async () => first.resolve(overview(4)));
    expect(fetchWorkbenchOverview).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("4")).not.toBeInTheDocument();

    await act(async () => latest.resolve(overview(0)));
    expect(screen.getByText("0")).toBeInTheDocument();

    expect(screen.getByText("0")).toBeInTheDocument();
  });
});
