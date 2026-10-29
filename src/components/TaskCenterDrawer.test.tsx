import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import TaskCenterDrawer from "./TaskCenterDrawer";
import type { WorkbenchTaskItemDTO } from "../types/workbench";

const auth = vi.hoisted(() => ({
  capabilities: {
    isAdmin: false,
    isBoss: false,
    isConsultingDirector: false,
    isBusinessUser: true,
    isGovernance: false,
    hasProject: true,
    isProjectManager: false,
  },
}));

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ status: "authenticated", capabilities: auth.capabilities }),
}));

const task: WorkbenchTaskItemDTO = {
  task_ref: "review-safe-reference",
  task_type: "review",
  object_name: "客户复盘审核",
  project_name: "华东交付项目",
  status: "needs_action",
  priority: "high",
  assignee: "林顾问",
  responsibility: "由你处理",
  created_at: "2026-08-12T01:00:00Z",
  updated_at: "2026-08-12T01:30:00Z",
  waiting_minutes: 30,
  next_action_key: "decide_review",
  next_action_label: "进入审核",
  route_key: "reviews",
  result_summary: null,
  progress_total: null,
  progress_success: null,
  progress_failed: null,
};

describe("TaskCenterDrawer", () => {
  it("shows submitted indexing as waiting for indexing confirmation", () => {
    render(
      <MemoryRouter>
        <TaskCenterDrawer
          open
          groups={{
            my_tasks: [{ ...task, task_type: "indexing", status: "submitted_pending_index" }],
            running_jobs: [],
            attention_items: [],
            recent_completed: [],
          }}
          onClose={vi.fn()}
        />
      </MemoryRouter>,
    );
    expect(screen.getAllByText("已提交，待索引").length).toBeGreaterThan(0);
    expect(screen.queryByText("状态待确认")).not.toBeInTheDocument();
  });

  it("keeps a rejection distinct from processing failure and shows the actual next action", () => {
    render(
      <MemoryRouter>
        <TaskCenterDrawer
          open
          groups={{
            my_tasks: [
              {
                ...task,
                task_type: "ingest",
                status: "rejected",
                next_action_label: "修改后重新上传",
                route_key: "upload",
                result_summary: "审核已拒绝：请补充依据",
              },
            ],
            running_jobs: [],
            attention_items: [],
            recent_completed: [],
          }}
          onClose={vi.fn()}
        />
      </MemoryRouter>,
    );
    expect(screen.getAllByText("审核已拒绝").length).toBeGreaterThan(0);
    expect(screen.getByText("审核已拒绝：请补充依据")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /修改后重新上传/ })).toHaveAttribute("href", "/upload");
    expect(screen.queryByText("修正或重试")).not.toBeInTheDocument();
  });
  it("shows safe task context and keeps long groups inside the drawer", () => {
    const onClose = vi.fn();
    const { container } = render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <TaskCenterDrawer
          open
          groups={{
            my_tasks: [task],
            running_jobs: [{ ...task, task_ref: "run-safe", status: "processing" }],
            attention_items: [],
            recent_completed: [],
          }}
          onClose={onClose}
        />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { name: "任务中心" })).toBeInTheDocument();
    expect(screen.getByText("客户复盘审核", { selector: "h3" })).toBeInTheDocument();
    expect(screen.getByText("华东交付项目", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /进入审核/ })).toHaveAttribute("href", "/review");
    expect(container.querySelector(".tc90-drawer-list")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("review-safe-reference");

    fireEvent.click(screen.getByRole("tab", { name: /进行中的作业/ }));
    const list = screen.getByLabelText("进行中的作业列表");
    expect(within(list).getByText("处理中")).toBeInTheDocument();
  });

  it("uses user-facing fallbacks instead of exposing unknown enum keys", () => {
    const unknown = {
      ...task,
      task_type: "internal_task_v9",
      status: "secret_transition" as WorkbenchTaskItemDTO["status"],
      priority: "internal_priority" as WorkbenchTaskItemDTO["priority"],
    };
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <TaskCenterDrawer
          open
          groups={{
            my_tasks: [unknown],
            running_jobs: [],
            attention_items: [],
            recent_completed: [],
          }}
          onClose={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(screen.getAllByText("状态待确认").length).toBeGreaterThan(0);
    expect(screen.getByText("常规")).toBeInTheDocument();
    expect(screen.getByText("业务任务")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("secret_transition");
    expect(document.body).not.toHaveTextContent("internal_priority");
    expect(document.body).not.toHaveTextContent("internal_task_v9");
  });
});
