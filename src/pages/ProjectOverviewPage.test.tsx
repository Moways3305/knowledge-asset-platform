import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ProjectOverviewPage from "./ProjectOverviewPage";

const api = vi.hoisted(() => ({
  fetchProjects: vi.fn(),
  fetchProjectOverview: vi.fn(),
}));

vi.mock("../api/project", () => api);

const PROJECT_A = "00000000-0000-0000-0000-000000000078";
const PROJECT_B = "00000000-0000-0000-0000-000000000079";

const projects = [
  {
    id: PROJECT_A,
    name: "华东增长项目",
    client_name: "华东客户中心",
    status: "active",
    lifecycle_route_key: "route_A",
    lifecycle_phase_key: "诊断",
    created_at: "2026-07-01T08:00:00Z",
    project_role: "consultant",
    can_manage: false,
  },
  {
    id: PROJECT_B,
    name: "年度辅导项目",
    client_name: null,
    status: "active",
    lifecycle_route_key: "route_B",
    lifecycle_phase_key: "年度复盘",
    created_at: "2026-07-02T08:00:00Z",
    project_role: "project_manager",
    can_manage: true,
  },
];

function overview(projectId = PROJECT_A, overrides: Record<string, unknown> = {}) {
  const source = projects.find((project) => project.id === projectId) ?? projects[0];
  return {
    project: {
      project_id: source.id,
      name: source.name,
      client_name: source.client_name,
      status: source.status,
      project_role: source.project_role,
      lifecycle_route_key: source.lifecycle_route_key,
      lifecycle_phase_key: source.lifecycle_phase_key,
      can_manage: source.can_manage,
    },
    capabilities: {
      can_view_knowledge: true,
      can_upload_material: true,
      can_manage_members: false,
      can_manage_kb: false,
      can_confirm_assets: false,
    },
    counts: {
      material_count: 12,
      asset_count: 7,
      pending_confirmation_count: 3,
      pending_review_count: 2,
      original_access_request_count: 1,
    },
    knowledge_base: { configured: true, status: "active" },
    members: [],
    recent_activity: [
      {
        asset_id: "asset-safe-link-78",
        title: "客户访谈洞察",
        zone: "asset",
        asset_type: "insight",
        confidentiality_level: "L2",
        updated_at: "2026-07-16T08:00:00Z",
      },
    ],
    ...overrides,
  };
}

function renderPage(path = `/project/${PROJECT_A}`) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/project/:id" element={<ProjectOverviewPage />} />
        <Route path="/" element={<div>今日工作台</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ProjectOverviewPage reference implementation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.fetchProjects.mockResolvedValue({ items: projects });
    api.fetchProjectOverview.mockImplementation(async (projectId: string) => overview(projectId));
  });

  it("renders only real overview counts, knowledge status and recent activity", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "华东增长项目" })).toBeInTheDocument();
    expect(await screen.findByText("12")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("已启用")).toBeInTheDocument();
    expect(screen.getByText(/L2 内部参考级/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /客户访谈洞察/ })).toHaveAttribute(
      "href",
      "/knowledge/asset-safe-link-78",
    );
    expect(screen.getByRole("link", { name: "项目知识库" })).toHaveAttribute(
      "href",
      `/project/${PROJECT_A}/knowledge`,
    );
    expect(screen.queryByText("项目成员")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "项目设置" })).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(PROJECT_A);
    expect(document.body).not.toHaveTextContent("route_A");
    expect(document.body).not.toHaveTextContent("诊断");
  });

  it("shows manager-only confirmation, settings and members from capabilities", async () => {
    api.fetchProjectOverview.mockResolvedValue(
      overview(PROJECT_B, {
        capabilities: {
          can_view_knowledge: true,
          can_upload_material: true,
          can_manage_members: true,
          can_manage_kb: false,
          can_confirm_assets: true,
        },
        members: [
          {
            user_id: "member-hidden-id",
            name: "周项目经理",
            project_role: "project_manager",
            status: "active",
          },
        ],
      }),
    );
    renderPage(`/project/${PROJECT_B}`);

    expect(await screen.findByText("周项目经理")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "处理待审核（2）" })).toHaveAttribute(
      "href",
      `/project/${PROJECT_B}/settings`,
    );
    expect(screen.getByRole("link", { name: "项目设置" })).toHaveAttribute(
      "href",
      `/project/${PROJECT_B}/settings`,
    );
    expect(document.body).not.toHaveTextContent("member-hidden-id");
  });

  it("switches URL context and ignores a late response from the previous project", async () => {
    let resolveA!: (value: ReturnType<typeof overview>) => void;
    api.fetchProjectOverview.mockImplementation((projectId: string) => {
      if (projectId === PROJECT_A) {
        return new Promise((resolve) => {
          resolveA = resolve;
        });
      }
      return Promise.resolve(overview(PROJECT_B));
    });
    renderPage();
    const picker = await screen.findByLabelText("切换项目");

    fireEvent.change(picker, { target: { value: PROJECT_B } });
    expect(await screen.findByRole("heading", { name: "年度辅导项目" })).toBeInTheDocument();
    resolveA(overview(PROJECT_A));

    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "年度辅导项目" })).toBeInTheDocument(),
    );
    expect(screen.queryByRole("heading", { name: "华东增长项目" })).not.toBeInTheDocument();
  });

  it("hides a ready project overview as soon as the URL switches to a pending project", async () => {
    let resolveB!: (value: ReturnType<typeof overview>) => void;
    const managerOverview = overview(PROJECT_A, {
      capabilities: {
        can_view_knowledge: true,
        can_upload_material: true,
        can_manage_members: true,
        can_manage_kb: false,
        can_confirm_assets: true,
      },
      members: [
        {
          user_id: "old-project-member-id",
          name: "项目 A 负责人",
          project_role: "project_manager",
          status: "active",
        },
      ],
    });
    api.fetchProjectOverview.mockImplementation((projectId: string) => {
      if (projectId === PROJECT_A) return Promise.resolve(managerOverview);
      return new Promise((resolve) => {
        resolveB = resolve;
      });
    });
    renderPage();

    expect(await screen.findByText("项目 A 负责人")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "处理待审核（2）" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("切换项目"), { target: { value: PROJECT_B } });

    expect(screen.getByRole("heading", { name: "年度辅导项目" })).toBeInTheDocument();
    expect(screen.getByText("正在加载项目概览…")).toBeInTheDocument();
    expect(screen.queryByText("项目 A 负责人")).not.toBeInTheDocument();
    expect(screen.queryByText("12")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "项目设置" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "处理待审核（2）" })).not.toBeInTheDocument();

    resolveB(overview(PROJECT_B));
    expect(await screen.findByText("最近更新的知识")).toBeInTheDocument();
  });

  it("keeps pending confirmation as a statistic without inventing a manager action", async () => {
    api.fetchProjectOverview.mockResolvedValue(
      overview(PROJECT_B, {
        capabilities: {
          can_view_knowledge: true,
          can_upload_material: true,
          can_manage_members: true,
          can_manage_kb: false,
          can_confirm_assets: true,
        },
        counts: {
          material_count: 12,
          asset_count: 7,
          pending_confirmation_count: 3,
          pending_review_count: 0,
          original_access_request_count: 1,
        },
      }),
    );
    renderPage(`/project/${PROJECT_B}`);

    expect(await screen.findByText("最近更新的知识")).toBeInTheDocument();
    expect(screen.getByText("待确认").previousElementSibling).toHaveTextContent("3");
    expect(screen.queryByText(/处理待确认/)).not.toBeInTheDocument();
    expect(screen.queryByText(/处理待审核/)).not.toBeInTheDocument();
  });

  it("uses a safe label for an unknown confidentiality level", async () => {
    const unsafeOverview = overview(PROJECT_A);
    unsafeOverview.recent_activity[0].confidentiality_level = "secret_level_78";
    api.fetchProjectOverview.mockResolvedValue(unsafeOverview);
    renderPage();

    expect(await screen.findByText(/保密级别待确认/)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("secret_level_78");
  });

  it("keeps empty and inaccessible project contexts explicit", async () => {
    api.fetchProjects.mockResolvedValueOnce({ items: [] });
    const empty = renderPage();
    expect(await screen.findByText("暂无可访问项目")).toBeInTheDocument();
    expect(api.fetchProjectOverview).not.toHaveBeenCalled();
    empty.unmount();

    api.fetchProjects.mockResolvedValueOnce({ items: projects });
    renderPage("/project/not-accessible");
    expect(await screen.findByText("项目不可访问")).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "选择可访问项目" })).toBeInTheDocument();
    expect(api.fetchProjectOverview).not.toHaveBeenCalled();
  });

  it("separates project-list and overview failures with working retries", async () => {
    api.fetchProjects.mockRejectedValueOnce(new Error("项目列表暂时不可用"));
    renderPage();
    expect(await screen.findByText("项目列表加载失败")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByRole("heading", { name: "华东增长项目" })).toBeInTheDocument();

    api.fetchProjectOverview.mockRejectedValueOnce(new Error("项目概览暂时不可用"));
    fireEvent.change(screen.getByLabelText("切换项目"), { target: { value: PROJECT_B } });
    expect(await screen.findByText("项目概览加载失败")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("最近更新的知识")).toBeInTheDocument();
  });
});
