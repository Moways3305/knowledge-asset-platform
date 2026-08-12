import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
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
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function Probe() {
  const { overview: value } = useWorkbench();
  return <output>{value?.task_center.summary.needs_action ?? "loading"}</output>;
}

describe("WorkbenchProvider refresh contract", () => {
  beforeEach(() => vi.mocked(fetchWorkbenchOverview).mockReset());

  it("refreshes immediately after a task-changing operation and rejects an older response", async () => {
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
    await waitFor(() => expect(fetchWorkbenchOverview).toHaveBeenCalledTimes(1));

    act(() => window.dispatchEvent(new Event(TASK_STATUS_INVALIDATED_EVENT)));
    await waitFor(() => expect(fetchWorkbenchOverview).toHaveBeenCalledTimes(2));

    await act(async () => latest.resolve(overview(0)));
    expect(screen.getByText("0")).toBeInTheDocument();

    await act(async () => first.resolve(overview(4)));
    expect(screen.getByText("0")).toBeInTheDocument();
  });
});
