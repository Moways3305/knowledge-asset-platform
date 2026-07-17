import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchPendingIngestTasks } from "../api/ingest";
import { fetchKnowledgeOpsInsights, fetchOriginalAccessRequests } from "../api/knowledge";
import { fetchProjects } from "../api/project";
import { fetchReviews } from "../api/review";
import { fetchWorkbenchOverview } from "../api/workbench";
import type { WorkbenchOverviewDTO } from "../types/workbench";
import HomeDashboardPage from "./HomeDashboardPage";

const auth = vi.hoisted(() => ({
  authMe: {
    userId: "secret-user-81",
    name: "林顾问",
    email: "lin@example.test",
    companyRoles: ["consultant"],
    isBusinessUser: true,
    canDiscoverL5: false,
    projects: [],
  },
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

vi.mock("../auth/AuthContext", () => ({ useAuth: () => auth }));
vi.mock("../api/workbench", () => ({ fetchWorkbenchOverview: vi.fn() }));
vi.mock("../api/ingest", () => ({ fetchPendingIngestTasks: vi.fn() }));
vi.mock("../api/review", () => ({ fetchReviews: vi.fn() }));
vi.mock("../api/project", () => ({ fetchProjects: vi.fn() }));
vi.mock("../api/knowledge", () => ({
  fetchKnowledgeOpsInsights: vi.fn(),
  fetchOriginalAccessRequests: vi.fn(),
}));

function overview(overrides: Partial<WorkbenchOverviewDTO> = {}): WorkbenchOverviewDTO {
  return {
    todos: {
      status: "available",
      error_code: null,
      total: 3,
      items: [
        {
          key: "review_pending",
          count: 2,
          severity: "warning",
          route_key: "reviews",
          action_key: "decide_review",
        },
        {
          key: "ingest_pending",
          count: 1,
          severity: "warning",
          route_key: "upload",
          action_key: "confirm_ingest",
        },
      ],
    },
    operations: {
      status: "available",
      error_code: null,
      data: {
        title_visible: true,
        scope: "company",
        window_days: 30,
        cards: [
          {
            key: "index_failed",
            label: "server label",
            count: 4,
            severity: "warning",
            action_hint: "server hint",
          },
        ],
        indexing: {
          index_failed: 4,
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
      total: 1,
      items: [
        {
          project_id: "project-real-81",
          name: "华东交付项目",
          status: "active",
          project_role: "consultant",
          lifecycle_route_key: "secret-route-A",
          lifecycle_phase_key: "secret-phase",
        },
      ],
    },
    recent_activity: {
      status: "available",
      error_code: null,
      total: 1,
      items: [
        {
          asset_id: "asset-real-81",
          title: "客户交付复盘",
          scope: "project",
          zone: "secret-zone",
          asset_type: "secret-type",
          confidentiality_level: "secret-level",
          summary: "secret-summary",
          project_name: "华东交付项目",
          updated_at: "2026-07-17T02:30:00Z",
        },
      ],
    },
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <HomeDashboardPage />
    </MemoryRouter>,
  );
}

describe("HomeDashboardPage overview workbench", () => {
  beforeEach(() => {
    auth.authMe.name = "林顾问";
    auth.authMe.companyRoles = ["consultant"];
    auth.authMe.isBusinessUser = true;
    Object.assign(auth.capabilities, {
      isAdmin: false,
      isBusinessUser: true,
      hasProject: true,
    });
    vi.mocked(fetchWorkbenchOverview).mockReset().mockResolvedValue(overview());
    vi.mocked(fetchPendingIngestTasks).mockReset();
    vi.mocked(fetchKnowledgeOpsInsights).mockReset();
    vi.mocked(fetchOriginalAccessRequests).mockReset();
    vi.mocked(fetchProjects).mockReset();
    vi.mocked(fetchReviews).mockReset();
  });

  it("uses only overview and renders all four available sections with formal routes", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "我的待办" })).toBeInTheDocument();
    expect(fetchWorkbenchOverview).toHaveBeenCalledTimes(1);
    expect(fetchPendingIngestTasks).not.toHaveBeenCalled();
    expect(fetchKnowledgeOpsInsights).not.toHaveBeenCalled();
    expect(fetchOriginalAccessRequests).not.toHaveBeenCalled();
    expect(fetchProjects).not.toHaveBeenCalled();
    expect(fetchReviews).not.toHaveBeenCalled();

    expect(screen.getByRole("link", { name: /处理知识审核/ })).toHaveAttribute("href", "/review");
    expect(screen.getByRole("link", { name: /确认待入库资料/ })).toHaveAttribute("href", "/upload");
    expect(screen.getByText("索引失败")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /华东交付项目.*顾问.*进行中/ })).toHaveAttribute(
      "href",
      "/project/project-real-81",
    );
    expect(screen.getByRole("link", { name: /客户交付复盘/ })).toHaveAttribute(
      "href",
      "/knowledge/asset-real-81",
    );
    expect(screen.getByRole("link", { name: "知识资产库" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "上传资产化" })).toBeInTheDocument();

    expect(document.body.textContent).not.toMatch(
      /review_pending|decide_review|secret-route-A|secret-phase|secret-zone|secret-type|secret-level|secret-summary|server label|server hint/,
    );
  });

  it("renders empty, forbidden and error sections independently and retries overview", async () => {
    vi.mocked(fetchWorkbenchOverview)
      .mockResolvedValueOnce(
        overview({
          todos: { status: "empty", error_code: null, items: [], total: 0 },
          operations: { status: "empty", error_code: null, data: null },
          projects: { status: "forbidden", error_code: "secret_forbidden", items: [], total: 0 },
          recent_activity: {
            status: "error",
            error_code: "secret_unavailable",
            items: [],
            total: 0,
          },
        }),
      )
      .mockResolvedValueOnce(
        overview({
          recent_activity: { status: "empty", error_code: null, items: [], total: 0 },
        }),
      );
    renderPage();

    expect(await screen.findByText("今天没有待处理事项")).toBeInTheDocument();
    expect(screen.getByText("当前没有需要处理的运营事项")).toBeInTheDocument();
    expect(screen.getByText("当前身份暂无访问权限")).toBeInTheDocument();
    const recent = screen.getByRole("heading", { name: "最近动态" }).closest("section")!;
    expect(within(recent).getByText("内容暂时未能加载")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(
      /secret_forbidden|secret_unavailable|forbidden|error/,
    );

    fireEvent.click(within(recent).getByRole("button", { name: "重新加载" }));
    expect(await within(recent).findByText("当前没有最近更新的资产")).toBeInTheDocument();
    expect(fetchWorkbenchOverview).toHaveBeenCalledTimes(2);
  });

  it("keeps unknown todo routes read-only and localizes every unknown enum", async () => {
    vi.mocked(fetchWorkbenchOverview).mockResolvedValue(
      overview({
        todos: {
          status: "available",
          error_code: null,
          total: 1,
          items: [
            {
              key: "secret_todo",
              count: 1,
              severity: "secret_severity",
              route_key: "secret_route",
              action_key: "secret_action",
            },
          ],
        },
        operations: {
          ...overview().operations,
          data: {
            ...overview().operations.data!,
            cards: [
              {
                key: "secret_card",
                label: "secret label",
                count: 7,
                severity: "secret_severity",
                action_hint: "secret hint",
              },
            ],
          },
        },
        projects: {
          status: "available",
          error_code: null,
          total: 1,
          items: [
            {
              ...overview().projects.items[0],
              project_role: "secret_role",
              status: "secret_status",
            },
          ],
        },
        recent_activity: {
          ...overview().recent_activity,
          items: [{ ...overview().recent_activity.items[0], scope: "secret_scope" }],
        },
      }),
    );
    renderPage();

    const todo = await screen.findByText("待处理事项");
    expect(todo.closest("a")).toBeNull();
    expect(screen.getAllByText("信息待确认")).toHaveLength(2);
    const projectLink = screen
      .getAllByRole("link")
      .find((link) => link.getAttribute("href") === "/project/project-real-81");
    expect(projectLink).toHaveTextContent("信息待确认 · 信息待确认");
    expect(screen.getByRole("link", { name: /客户交付复盘/ })).toHaveTextContent("信息待确认");
    expect(document.body.textContent).not.toMatch(
      /secret_todo|secret_severity|secret_route|secret_action|secret_card|secret label|secret hint|secret_role|secret_status|secret_scope/,
    );
  });

  it("never exposes an activity title when title visibility is false", async () => {
    vi.mocked(fetchWorkbenchOverview).mockResolvedValue(
      overview({
        operations: {
          ...overview().operations,
          data: { ...overview().operations.data!, title_visible: false },
        },
      }),
    );
    renderPage();

    expect(await screen.findByText("业务标题已隐藏")).toBeInTheDocument();
    expect(screen.queryByText("客户交付复盘")).not.toBeInTheDocument();
  });

  it("turns a whole overview failure into recoverable section states", async () => {
    vi.mocked(fetchWorkbenchOverview)
      .mockRejectedValueOnce(new Error("SECRET-LIKE /api/v1/workbench/overview"))
      .mockResolvedValueOnce(overview());
    renderPage();

    const alerts = await screen.findAllByRole("alert");
    expect(alerts).toHaveLength(4);
    expect(document.body.textContent).not.toMatch(/SECRET-LIKE|api\/v1|HTTP|500/);
    fireEvent.click(within(alerts[0]).getByRole("button", { name: "重新加载" }));
    await waitFor(() => expect(fetchWorkbenchOverview).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("客户交付复盘")).toBeInTheDocument();
  });

  it("hides business shortcuts when the current identity lacks capabilities", async () => {
    auth.authMe.companyRoles = ["admin"];
    auth.authMe.isBusinessUser = false;
    Object.assign(auth.capabilities, { isAdmin: true, isBusinessUser: false, hasProject: false });
    vi.mocked(fetchWorkbenchOverview).mockResolvedValue(
      overview({
        todos: { status: "forbidden", error_code: null, items: [], total: 0 },
        projects: { status: "forbidden", error_code: null, items: [], total: 0 },
        recent_activity: { status: "forbidden", error_code: null, items: [], total: 0 },
      }),
    );
    renderPage();

    expect(await screen.findAllByText("当前身份暂无访问权限")).toHaveLength(3);
    expect(screen.queryByRole("link", { name: "知识资产库" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "上传资产化" })).not.toBeInTheDocument();
  });
});
