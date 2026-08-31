import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchWorkbenchOverview } from "../api/workbench";
import { fetchWorkbuddyToken } from "../api/workbuddy";
import { fetchPeople } from "../api/admin";
import { createProject } from "../api/project";
import type { WorkbenchOverviewDTO, WorkbenchTaskItemDTO } from "../types/workbench";
import { TASK_STATUS_INVALIDATED_EVENT } from "../workbench/taskStatusEvents";
import { WorkbenchProvider } from "../workbench/WorkbenchContext";
import HomeDashboardPage from "./HomeDashboardPage";

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
vi.mock("../api/workbench", () => ({ fetchWorkbenchOverview: vi.fn() }));
vi.mock("../api/workbuddy", () => ({ fetchWorkbuddyToken: vi.fn() }));
vi.mock("../api/admin", () => ({ fetchPeople: vi.fn() }));
vi.mock("../api/project", () => ({ createProject: vi.fn() }));

function task(overrides: Partial<WorkbenchTaskItemDTO> = {}): WorkbenchTaskItemDTO {
  return {
    task_ref: "review-safe-ref",
    task_type: "review",
    object_name: "客户交付复盘审核",
    project_name: "华东交付项目",
    status: "needs_action",
    priority: "high",
    assignee: "林顾问",
    responsibility: "由你处理",
    created_at: "2026-08-27T01:30:00Z",
    updated_at: "2026-08-27T02:30:00Z",
    waiting_minutes: 65,
    next_action_key: "decide_review",
    next_action_label: "进入审核",
    route_key: "reviews",
    result_summary: null,
    progress_total: null,
    progress_success: null,
    progress_failed: null,
    ...overrides,
  };
}

function overview(overrides: Partial<WorkbenchOverviewDTO> = {}): WorkbenchOverviewDTO {
  const actionable = task();
  const running = task({
    task_ref: "ingest-running-safe-ref",
    task_type: "ingest",
    object_name: "项目访谈纪要.pdf",
    status: "processing",
    next_action_key: null,
    next_action_label: "正在解析内容",
    route_key: "upload",
    progress_total: 10,
    progress_success: 4,
    progress_failed: 0,
  });
  const completed = task({
    task_ref: "ingest-complete-safe-ref",
    task_type: "ingest",
    object_name: "行业研究摘要.docx",
    status: "duplicate_skipped",
    priority: "low",
    next_action_label: "查看入库结果",
    result_summary: "因内容重复已跳过",
  });
  return {
    task_center: {
      status: "available",
      error_code: null,
      summary: { needs_action: 1, running: 1, attention: 1, completed_today: 1 },
      priority_items: [actionable],
      my_tasks: [actionable],
      running_jobs: [running],
      attention_items: [
        task({ task_ref: "attention-safe-ref", status: "failed", object_name: "索引异常" }),
      ],
      recent_completed: [completed],
    },
    todos: { status: "available", error_code: null, items: [], total: 1 },
    operations: {
      status: "available",
      error_code: null,
      data: {
        title_visible: true,
        scope: "company",
        window_days: 30,
        cards: [],
        indexing: {
          index_failed: 0,
          skipped: 0,
          not_indexed: 0,
          parse_failed: 0,
          parse_pending: 0,
          parse_processing: 0,
          kb_init_failed: 0,
        },
        access: {
          pending_original_requests: 0,
          overdue_original_requests: 0,
          recent_auto_approved: 0,
          timeout_enabled: false,
        },
        lifecycle: {
          archive_candidates: 0,
          archive_warnings: 0,
          needs_update: 0,
          reuse_upgrade_candidates: 0,
        },
      },
    },
    projects: {
      status: "available",
      error_code: null,
      total: 2,
      items: [
        {
          project_id: "project-safe-1",
          name: "华东交付项目",
          status: "active",
          project_role: "consultant",
          access_mode: "member",
          access_label: "可查看资料",
          lifecycle_route_key: null,
          lifecycle_phase_key: null,
        },
        {
          project_id: "project-summary-safe-2",
          name: "行业研究项目",
          status: "active",
          project_role: null,
          access_mode: "summary_visible",
          access_label: "摘要可见",
          lifecycle_route_key: null,
          lifecycle_phase_key: null,
        },
      ],
    },
    recent_activity: {
      status: "available",
      error_code: null,
      total: 1,
      items: [
        {
          asset_id: "asset-safe-1",
          title: "交付复盘方法",
          scope: "project",
          zone: "project",
          asset_type: "document",
          access_mode: "member",
          confidentiality_level: "L2",
          summary: null,
          project_name: "华东交付项目",
          updated_at: "2026-08-27T02:30:00Z",
        },
      ],
    },
    ...overrides,
  };
}

function LocationProbe() {
  const location = useLocation();
  return (
    <output data-testid="location">
      {location.pathname}
      {location.search}
    </output>
  );
}

function renderPage(initialEntry = "/") {
  return render(
    <MemoryRouter
      initialEntries={[initialEntry]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <WorkbenchProvider>
        <HomeDashboardPage />
        <LocationProbe />
      </WorkbenchProvider>
    </MemoryRouter>,
  );
}

describe("HomeDashboardPage task-first workbench", () => {
  beforeEach(() => {
    Object.assign(auth.capabilities, {
      isAdmin: false,
      isBoss: false,
      isConsultingDirector: false,
      isBusinessUser: true,
      isGovernance: false,
      hasProject: true,
      isProjectManager: false,
    });
    vi.mocked(fetchWorkbenchOverview).mockReset().mockResolvedValue(overview());
    vi.mocked(fetchWorkbuddyToken).mockReset().mockResolvedValue({
      enabled: false,
      boundUserName: null,
      lastRotatedAt: null,
      lastConnectedAt: null,
    });
    vi.mocked(fetchPeople).mockReset().mockResolvedValue({ items: [], total: 0 });
    vi.mocked(createProject).mockReset();
  });

  it("uses the overview read model for the task-first layout and removes legacy dashboard regions", async () => {
    const networkSpy = vi.spyOn(globalThis, "fetch");
    const { container } = renderPage();

    expect(await screen.findByRole("heading", { name: "我的工作" })).toBeInTheDocument();
    expect(screen.getByText("1 项需要你处理")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "待处理1" })).toHaveAttribute("aria-selected", "true");
    expect(
      screen.getByRole("button", { name: /客户交付复盘审核.*知识审核.*华东交付项目.*进入审核/ }),
    ).toHaveClass("material-review");
    fireEvent.click(screen.getByRole("tab", { name: "进行中1" }));
    expect(screen.getByText(/处理中 · 4\/10/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "最近动态" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "我的项目" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /华东交付项目.*可查看资料/ })).toHaveAttribute(
      "href",
      "/project/project-safe-1",
    );
    expect(screen.getByRole("link", { name: /华东交付项目.*可查看资料/ })).toHaveClass(
      "material-project",
    );
    expect(screen.getByRole("link", { name: /行业研究项目.*摘要可见/ })).toHaveAttribute(
      "href",
      "/knowledge?scope=project&project_id=project-summary-safe-2",
    );
    expect(screen.getByRole("link", { name: /行业研究项目.*摘要可见/ })).toHaveClass(
      "material-summary",
    );
    expect(await screen.findByText("尚未启用")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /交付复盘方法/ })).toHaveAttribute(
      "href",
      "/knowledge/asset-safe-1",
    );
    expect(screen.getByRole("link", { name: /交付复盘方法/ })).toHaveClass("material-source");
    expect(container.querySelector(".workbench-layout")).toBeInTheDocument();
    expect(screen.queryByText("今日任务调度")).not.toBeInTheDocument();
    expect(screen.queryByText("项目概览")).not.toBeInTheDocument();
    expect(screen.queryByText("资产运行概览")).not.toBeInTheDocument();
    expect(fetchWorkbenchOverview).toHaveBeenCalledTimes(1);
    expect(networkSpy).not.toHaveBeenCalled();
    networkSpy.mockRestore();
  });

  it("shows project creation only to governance users and reuses the shared modal", async () => {
    Object.assign(auth.capabilities, { isGovernance: true, isBoss: true });
    vi.mocked(fetchPeople).mockResolvedValue({
      total: 1,
      items: [
        {
          user_id: "manager-safe-1",
          name: "项目经理",
          email: "manager@example.com",
          phone: null,
          wecom_bound: false,
          status: "active",
          created_at: "2026-08-28T01:00:00Z",
          updated_at: "2026-08-28T01:00:00Z",
          company_roles: [],
          project_memberships: [],
          recent_session_at: null,
          password_set: true,
          password_set_at: "2026-08-28T01:00:00Z",
        },
      ],
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "新建项目" }));
    expect(screen.getByRole("dialog", { name: "新建项目" })).toBeInTheDocument();
    await waitFor(() => expect(fetchPeople).toHaveBeenCalledTimes(1));
  });

  it("does not render project creation hints for non-governance users", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { name: "我的项目" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "新建项目" })).not.toBeInTheDocument();
    expect(screen.queryByText("仅治理角色可见")).not.toBeInTheDocument();
  });

  it("opens the same task drawer on the selected row and preserves strict status labels", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /客户交付复盘审核.*进入审核/ }));

    expect(screen.getByRole("heading", { name: "任务中心" })).toBeInTheDocument();
    expect(screen.getByText("客户交付复盘审核", { selector: "h3" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /进入审核/ })).toHaveAttribute("href", "/review");
    expect(screen.getByTestId("location")).toHaveTextContent("/?task_group=my_tasks");

    fireEvent.click(screen.getByRole("tab", { name: "已完成" }));
    expect(await screen.findByText(/因内容重复已跳过/)).toBeInTheDocument();
    expect(screen.getByText(/重复跳过 ·/)).toBeInTheDocument();
  });

  it("opens the priority task from the focus surface and switches groups from the rhythm rail", async () => {
    renderPage();

    const focus = await screen.findByRole("button", { name: "打开今日焦点任务" });
    const rhythm = screen.getByLabelText("今日工作节奏");
    const running = within(rhythm).getByRole("button", { name: /进行中1/ });

    fireEvent.click(running);
    expect(running).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/处理中 · 4\/10/)).toBeInTheDocument();

    fireEvent.click(focus);
    expect(screen.getByRole("heading", { name: "任务中心" })).toBeInTheDocument();
    expect(screen.getByText("客户交付复盘审核", { selector: "h3" })).toBeInTheDocument();
  });

  it("uses the real migration and markdown backfill task type labels", async () => {
    const migration = task({
      task_ref: "migration-safe-ref",
      task_type: "kb_migration",
      object_name: "知识库迁移",
      status: "processing",
      next_action_key: "inspect_operation",
      next_action_label: "查看作业进度",
      route_key: "models",
    });
    const markdown = task({
      task_ref: "markdown-safe-ref",
      task_type: "markdown_backfill",
      object_name: "规范 Markdown 补齐",
      status: "processing",
      next_action_key: "inspect_operation",
      next_action_label: "查看作业进度",
      route_key: "admin_ingest",
    });
    vi.mocked(fetchWorkbenchOverview).mockResolvedValue(
      overview({
        task_center: {
          ...overview().task_center,
          summary: { needs_action: 1, running: 2, attention: 1, completed_today: 1 },
          running_jobs: [migration, markdown],
        },
      }),
    );
    renderPage();
    fireEvent.click(await screen.findByRole("tab", { name: "进行中2" }));
    expect(screen.getByRole("button", { name: /知识库迁移.*迁移作业/ })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /规范 Markdown 补齐.*内容补齐作业/ }),
    ).toBeInTheDocument();
  });

  it("deep-links to a drawer group and restores the URL when closed", async () => {
    renderPage("/?task_group=running_jobs&from=notification");
    expect(await screen.findByRole("heading", { name: "任务中心" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /进行中的作业/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByText("项目访谈纪要.pdf", { selector: "h3" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "关闭详情" }));
    expect(screen.getByTestId("location")).toHaveTextContent("/?from=notification");
  });

  it("shows a single permitted next step when no action is required", async () => {
    vi.mocked(fetchWorkbenchOverview).mockResolvedValue(
      overview({
        task_center: {
          status: "empty",
          error_code: null,
          summary: { needs_action: 0, running: 0, attention: 0, completed_today: 0 },
          priority_items: [],
          my_tasks: [],
          running_jobs: [],
          attention_items: [],
          recent_completed: [],
        },
      }),
    );
    renderPage();
    expect(await screen.findAllByText("当前没有需要你处理的事项")).not.toHaveLength(0);
    expect(screen.getByRole("link", { name: "上传资料" })).toHaveAttribute("href", "/upload");
    expect(screen.queryByText("今日工作已完成")).not.toBeInTheDocument();
  });

  it("does not present a submitted task waiting on someone else as actionable", async () => {
    const submitted = task({
      status: "submitted",
      next_action_key: null,
      next_action_label: "等待审核结果",
      responsibility: "由你提交",
    });
    vi.mocked(fetchWorkbenchOverview).mockResolvedValue(
      overview({
        task_center: {
          ...overview().task_center,
          summary: { needs_action: 0, running: 1, attention: 1, completed_today: 1 },
          my_tasks: [submitted],
        },
      }),
    );
    renderPage();
    expect(await screen.findAllByText("当前没有需要你处理的事项")).not.toHaveLength(0);
    expect(screen.getByRole("tab", { name: "待处理0" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /客户交付复盘审核.*等待审核结果/ }),
    ).not.toBeInTheDocument();
  });

  it("keeps restricted recent titles neutral", async () => {
    const hidden = overview();
    hidden.operations.data!.title_visible = false;
    vi.mocked(fetchWorkbenchOverview).mockResolvedValue(hidden);
    renderPage();
    expect(await screen.findByText("业务标题已隐藏")).toBeInTheDocument();
    expect(screen.queryByText("交付复盘方法")).not.toBeInTheDocument();
  });

  it("uses projected access mode for cross-project summary material", async () => {
    const data = overview();
    data.recent_activity.items.push({
      ...data.recent_activity.items[0],
      asset_id: "asset-summary-safe-2",
      title: "跨项目安全摘要",
      access_mode: "summary_visible",
    });
    vi.mocked(fetchWorkbenchOverview).mockResolvedValue(data);

    renderPage();

    expect(await screen.findByRole("link", { name: /跨项目安全摘要/ })).toHaveClass(
      "material-summary",
    );
    expect(screen.getByRole("link", { name: /交付复盘方法/ })).toHaveClass("material-source");
  });

  it("does not send a pure administrator to business-only task or knowledge routes", async () => {
    Object.assign(auth.capabilities, {
      isAdmin: true,
      isBusinessUser: false,
      isGovernance: false,
      hasProject: false,
    });
    const adminOverview = overview();
    adminOverview.task_center.attention_items = [
      task({
        task_ref: "restricted-attention",
        task_type: "archive_candidates",
        object_name: "待归档资料",
        route_key: "knowledge",
        next_action_label: "查看受影响范围",
      }),
    ];
    vi.mocked(fetchWorkbenchOverview).mockResolvedValue(adminOverview);
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /另有 1 项需要关注/ }));
    expect(screen.getByText("待归档资料", { selector: "h3" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "查看受影响范围" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /交付复盘方法|业务标题已隐藏/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("当前身份没有可显示的工作事项")).toBeInTheDocument();
  });

  it("renders a safe recoverable error without technical details", async () => {
    vi.mocked(fetchWorkbenchOverview)
      .mockRejectedValueOnce(new Error("SECRET /api/v1/workbench/overview"))
      .mockResolvedValueOnce(overview());
    renderPage();
    const alerts = await screen.findAllByRole("alert");
    expect(alerts.length).toBeGreaterThan(0);
    expect(document.body).not.toHaveTextContent("SECRET");
    expect(document.body).not.toHaveTextContent("/api/v1");
    fireEvent.click(within(alerts[0]).getByRole("button", { name: "重新加载" }));
    expect(await screen.findByText("客户交付复盘审核")).toBeInTheDocument();
  });

  it("refreshes counts and lists immediately after a task status event", async () => {
    const done = overview({
      task_center: {
        ...overview().task_center,
        summary: { needs_action: 0, running: 1, attention: 1, completed_today: 2 },
        my_tasks: [],
        recent_completed: [
          ...overview().task_center.recent_completed,
          task({
            task_ref: "just-completed",
            status: "completed",
            object_name: "刚完成的审核",
            result_summary: "审核已通过",
          }),
        ],
      },
    });
    vi.mocked(fetchWorkbenchOverview).mockResolvedValueOnce(overview()).mockResolvedValueOnce(done);
    renderPage();
    expect(await screen.findByText("1 项需要你处理")).toBeInTheDocument();

    act(() => window.dispatchEvent(new Event(TASK_STATUS_INVALIDATED_EVENT)));
    await waitFor(() => expect(fetchWorkbenchOverview).toHaveBeenCalledTimes(2));
    expect(await screen.findAllByText("当前没有需要你处理的事项")).not.toHaveLength(0);
    fireEvent.click(screen.getByRole("tab", { name: "已完成" }));
    expect((await screen.findAllByText("刚完成的审核")).length).toBeGreaterThan(0);
  });
});
