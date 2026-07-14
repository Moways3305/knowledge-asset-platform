import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/http";
import { fetchPendingIngestTasks } from "../api/ingest";
import { fetchKnowledgeOpsInsights, fetchOriginalAccessRequests } from "../api/knowledge";
import { fetchProjects } from "../api/project";
import { fetchReviews } from "../api/review";
import type { KnowledgeOpsInsightsDTO } from "../types/insights";
import HomeDashboardPage from "./HomeDashboardPage";

const auth = vi.hoisted(() => ({
  status: "authenticated",
  authMe: {
    userId: "user-real-65",
    name: "林顾问",
    email: "lin@example.test",
    companyRoles: ["consultant"],
    isBusinessUser: true,
    canDiscoverL5: false,
    projects: [
      { projectId: "project-a", projectName: "甲项目", projectRole: "consultant" },
      { projectId: "project-b", projectName: "乙项目", projectRole: "project_manager" },
    ],
  },
  capabilities: {
    isAdmin: false,
    isBoss: false,
    isConsultingDirector: false,
    isBusinessUser: true,
    isGovernance: false,
    hasProject: true,
    isProjectManager: true,
  },
}));

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => auth,
}));

vi.mock("../api/ingest", () => ({ fetchPendingIngestTasks: vi.fn() }));
vi.mock("../api/review", () => ({ fetchReviews: vi.fn() }));
vi.mock("../api/project", () => ({ fetchProjects: vi.fn() }));
vi.mock("../api/knowledge", () => ({
  fetchKnowledgeOpsInsights: vi.fn(),
  fetchOriginalAccessRequests: vi.fn(),
}));

function insights(overrides: Partial<KnowledgeOpsInsightsDTO> = {}): KnowledgeOpsInsightsDTO {
  return {
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
      recent_jobs: [],
    },
    access: {
      pending_original_requests: 0,
      overdue_original_requests: 0,
      recent_auto_approved: 0,
      timeout_enabled: true,
    },
    lifecycle: {
      archive_candidates: 0,
      archive_warnings: 0,
      needs_update: 0,
      reuse_upgrade_candidates: 0,
    },
    recommendations: [],
    recent_items: [],
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

describe("HomeDashboardPage real workbench", () => {
  beforeEach(() => {
    auth.status = "authenticated";
    auth.authMe.name = "林顾问";
    auth.authMe.companyRoles = ["consultant"];
    auth.authMe.isBusinessUser = true;
    auth.authMe.canDiscoverL5 = false;
    auth.authMe.projects = [
      { projectId: "project-a", projectName: "甲项目", projectRole: "consultant" },
      { projectId: "project-b", projectName: "乙项目", projectRole: "project_manager" },
    ];
    Object.assign(auth.capabilities, {
      isAdmin: false,
      isBoss: false,
      isConsultingDirector: false,
      isBusinessUser: true,
      isGovernance: false,
      hasProject: true,
      isProjectManager: true,
    });

    vi.mocked(fetchPendingIngestTasks).mockReset().mockResolvedValue([]);
    vi.mocked(fetchReviews).mockReset().mockResolvedValue([]);
    vi.mocked(fetchOriginalAccessRequests).mockReset().mockResolvedValue({ items: [], total: 0 });
    vi.mocked(fetchKnowledgeOpsInsights).mockReset().mockResolvedValue(insights());
    vi.mocked(fetchProjects)
      .mockReset()
      .mockResolvedValue({
        items: [
          {
            id: "project-a",
            name: "甲项目",
            client_name: null,
            status: "active",
            lifecycle_route_key: null,
            lifecycle_phase_key: null,
            created_at: "2026-07-14T00:00:00Z",
            can_manage: false,
          },
          {
            id: "project-b",
            name: "乙项目",
            client_name: null,
            status: "active",
            lifecycle_route_key: null,
            lifecycle_phase_key: null,
            created_at: "2026-07-14T00:00:00Z",
            can_manage: true,
          },
        ],
      });
  });

  it("uses real counts, severity order and business routes for a consultant", async () => {
    vi.mocked(fetchPendingIngestTasks).mockResolvedValue([{} as never, {} as never]);
    vi.mocked(fetchReviews).mockResolvedValue([
      { status: "pending" } as never,
      { status: "approved" } as never,
    ]);
    vi.mocked(fetchKnowledgeOpsInsights).mockResolvedValue(
      insights({
        indexing: { ...insights().indexing, index_failed: 1 },
        lifecycle: { ...insights().lifecycle, needs_update: 3 },
      }),
    );

    const { container } = renderPage();
    expect(await screen.findByRole("link", { name: /处理索引失败/ })).toHaveAttribute(
      "href",
      "/knowledge",
    );
    expect(screen.getByRole("link", { name: /更新知识资产/ })).toHaveTextContent("3");
    expect(screen.getByRole("link", { name: /确认待入库资料/ })).toHaveTextContent("2");
    expect(screen.getByRole("link", { name: /处理升级审核/ })).toHaveTextContent("1");
    const todoLinks = Array.from(container.querySelectorAll(".workbench-todo"));
    expect(todoLinks[0]).toHaveTextContent("处理索引失败");
    expect(screen.getByRole("link", { name: "上传资产化" })).toBeInTheDocument();
    expect(screen.queryByText(/增长率|趋势/)).not.toBeInTheDocument();
  });

  it("keeps every real project directly reachable", async () => {
    renderPage();

    expect(await screen.findByRole("link", { name: /甲项目/ })).toHaveAttribute(
      "href",
      "/project/project-a/knowledge",
    );
    expect(screen.getByRole("link", { name: /乙项目/ })).toHaveAttribute(
      "href",
      "/project/project-b/knowledge",
    );
    expect(screen.getByRole("link", { name: /甲项目/ })).toHaveTextContent("顾问");
    expect(screen.getByRole("link", { name: /乙项目/ })).toHaveTextContent("项目经理");
  });

  it("distinguishes zero work from an unavailable identity scope", async () => {
    const first = renderPage();
    expect(await screen.findByText("今天没有待处理事项")).toBeInTheDocument();
    first.unmount();
    vi.mocked(fetchPendingIngestTasks).mockClear();
    vi.mocked(fetchReviews).mockClear();

    auth.authMe.companyRoles = ["admin"];
    auth.authMe.isBusinessUser = false;
    auth.authMe.projects = [];
    Object.assign(auth.capabilities, {
      isAdmin: true,
      isBusinessUser: false,
      isGovernance: false,
      hasProject: false,
      isProjectManager: false,
    });
    vi.mocked(fetchKnowledgeOpsInsights).mockRejectedValue(new ApiError(403, "denied"));

    renderPage();
    expect(await screen.findByText("当前身份没有可用待办队列")).toBeInTheDocument();
    expect(screen.getByText("当前身份不可查看资产运行状态。")).toBeInTheDocument();
    expect(fetchPendingIngestTasks).not.toHaveBeenCalled();
    expect(fetchReviews).not.toHaveBeenCalled();
    expect(screen.queryByRole("link", { name: "上传资产化" })).not.toBeInTheDocument();
  });

  it("shows a failed source without turning it into an empty queue and retries it", async () => {
    vi.mocked(fetchReviews)
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce([{ status: "pending" } as never]);

    renderPage();
    const alert = await screen.findByRole("alert", { name: "" });
    expect(within(alert).getByText("部分待办数据未加载成功")).toBeInTheDocument();
    expect(screen.queryByText("今天没有待处理事项")).not.toBeInTheDocument();

    fireEvent.click(within(alert).getByRole("button", { name: "重新加载" }));
    expect(await screen.findByRole("link", { name: /处理升级审核/ })).toHaveTextContent("1");
    await waitFor(() => expect(fetchReviews).toHaveBeenCalledTimes(2));
  });

  it("keeps successful modules visible when the project request fails", async () => {
    vi.mocked(fetchProjects).mockRejectedValue(new Error("network"));
    vi.mocked(fetchKnowledgeOpsInsights).mockResolvedValue(
      insights({
        recommendations: [
          {
            key: "real-recommendation",
            severity: "warning",
            message: "处理失败索引",
            target: "/knowledge",
          },
        ],
      }),
    );

    renderPage();
    expect(await screen.findByText("处理失败索引")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /甲项目/ })).toHaveAttribute(
      "href",
      "/project/project-a/knowledge",
    );
    expect(screen.getByText(/以上入口来自当前登录身份中的有效项目关系/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument();
  });
});
