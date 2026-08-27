import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { WorkbenchOverviewDTO, WorkbenchTaskItemDTO } from "../types/workbench";
import GlobalTaskStatus from "./GlobalTaskStatus";

const state = vi.hoisted(() => ({
  overview: null as WorkbenchOverviewDTO | null,
  refresh: vi.fn(),
}));

vi.mock("../workbench/WorkbenchContext", () => ({
  useWorkbench: () => ({ overview: state.overview, state: "ready", refresh: state.refresh }),
}));

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({
    status: "authenticated",
    capabilities: {
      isAdmin: false,
      isBoss: false,
      isConsultingDirector: false,
      isBusinessUser: true,
      isGovernance: false,
      hasProject: true,
      isProjectManager: false,
    },
  }),
}));

function task(index: number): WorkbenchTaskItemDTO {
  return {
    task_ref: `safe-task-${index}`,
    task_type: "review",
    object_name: `待审核资料 ${index}`,
    project_name: "交付项目",
    status: "needs_action",
    priority: "high",
    assignee: "当前用户",
    responsibility: "由你处理",
    created_at: "2026-08-27T01:00:00Z",
    updated_at: "2026-08-27T02:00:00Z",
    waiting_minutes: 60,
    next_action_key: "decide_review",
    next_action_label: "进入审核",
    route_key: "reviews",
    result_summary: null,
    progress_total: null,
    progress_success: null,
    progress_failed: null,
  };
}

function overview(count: number): WorkbenchOverviewDTO {
  const items = Array.from({ length: count }, (_, index) => task(index + 1));
  return {
    task_center: {
      status: count ? "available" : "empty",
      error_code: null,
      summary: { needs_action: count, running: 0, attention: 0, completed_today: 0 },
      priority_items: items,
      my_tasks: items,
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

describe("GlobalTaskStatus", () => {
  beforeEach(() => {
    state.overview = overview(2);
    state.refresh.mockReset().mockResolvedValue(undefined);
  });

  it("keeps the badge and default drawer group synchronized with needs_action", () => {
    const view = render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <GlobalTaskStatus />
      </MemoryRouter>,
    );

    expect(screen.getByRole("button", { name: "打开任务中心，2 项待处理" })).toHaveTextContent("2");
    fireEvent.click(screen.getByRole("button", { name: "打开任务中心，2 项待处理" }));
    expect(state.refresh).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("tab", { name: /我的任务\s*2/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    state.overview = overview(0);
    view.rerender(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <GlobalTaskStatus />
      </MemoryRouter>,
    );

    expect(screen.getByRole("button", { name: "打开任务中心，0 项待处理" })).toBeInTheDocument();
    expect(view.container.querySelector(".global-task-status span")).toBeNull();
    expect(screen.getByRole("tab", { name: /我的任务\s*0/ })).toBeInTheDocument();
    expect(screen.getByText("此分组当前没有任务。")).toBeInTheDocument();
  });
});
