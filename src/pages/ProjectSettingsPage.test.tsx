import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/http";
import ProjectSettingsPage from "./ProjectSettingsPage";

const PROJECT_ID = "00000000-0000-0000-0000-000000000074";
const OTHER_PROJECT_ID = "00000000-0000-0000-0000-000000000075";

const projectApi = vi.hoisted(() => ({
  fetchProjectSettings: vi.fn(),
  updateProjectSettings: vi.fn(),
  fetchProjectMembers: vi.fn(),
  patchProjectMember: vi.fn(),
}));
const reviewApi = vi.hoisted(() => ({
  fetchReviews: vi.fn(),
  approveReview: vi.fn(),
  rejectReview: vi.fn(),
}));
const auth = vi.hoisted(() => ({
  projectRole: "project_manager",
}));

vi.mock("../api/project", () => projectApi);
vi.mock("../api/review", () => reviewApi);
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({
    authMe: {
      userId: "00000000-0000-0000-0000-000000000001",
      name: "项目经理",
      email: "manager@example.test",
      companyRoles: [],
      isBusinessUser: true,
      canDiscoverL5: false,
      projects: [
        {
          projectId: PROJECT_ID,
          projectName: "真实项目",
          projectRole: auth.projectRole,
        },
      ],
    },
  }),
}));

const settings = {
  project_id: PROJECT_ID,
  name: "华东交付优化项目",
  status: "active",
  client_name: "客户运营中心",
  coach_name: "陈老师",
  lifecycle_route_key: "route_A",
  lifecycle_phase_key: "诊断阶段",
  force_review_on_ingest: true,
  wecom_group_bound: true,
  wecom_group_label: "群组…9074",
  updated_at: "2026-07-15T08:00:00Z",
  can_write: true,
};

const members = [
  {
    member_id: "member-manager",
    user_id: "user-manager",
    name: "项目负责人",
    email: "must-not-render@example.test",
    company_roles: ["boss"],
    project_role: "project_manager",
    status: "active",
    source: "manual",
    joined_at: "2026-07-01T08:00:00Z",
    wecom_bound: false,
  },
  {
    member_id: "member-consultant",
    user_id: "user-consultant",
    name: "交付顾问",
    email: "hidden-consultant@example.test",
    company_roles: ["consulting_director"],
    project_role: "consultant",
    status: "active",
    source: "manual",
    joined_at: "2026-07-02T08:00:00Z",
    wecom_bound: true,
  },
];

const actionableReview = {
  id: "review-secret-id",
  review_type: "project_ingest_approval",
  trigger_source: "upload",
  status: "pending_reviewer",
  target_asset_id: "asset-secret-id",
  asset_title: "客户访谈纪要",
  target_scope: "project",
  target_project_id: PROJECT_ID,
  project_name: "华东交付优化项目",
  submitted_by: "user-secret-id",
  reviewer_user_id: null,
  evidence_count: 0,
  review_comment: null,
  reviewed_at: null,
  created_at: "2026-07-15T09:00:00Z",
  can_decide: true,
  can_withdraw: false,
  general_manager_confirmation_status: null,
  consulting_director_confirmation_status: null,
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={[`/project/${PROJECT_ID}/settings`]}>
      <Routes>
        <Route path="/project/:id/settings" element={<ProjectSettingsPage />} />
        <Route path="/review" element={<div>审核页</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ProjectSettingsPage reference implementation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    auth.projectRole = "project_manager";
    projectApi.fetchProjectSettings.mockResolvedValue({ ...settings });
    projectApi.fetchProjectMembers.mockResolvedValue({
      items: members.map((member) => ({ ...member })),
      total: members.length,
      can_manage: true,
    });
    projectApi.updateProjectSettings.mockImplementation(async (_projectId, body) => ({
      ...settings,
      lifecycle_route_key: body.lifecycle_route_key ?? settings.lifecycle_route_key,
      lifecycle_phase_key: body.lifecycle_phase_key ?? settings.lifecycle_phase_key,
      force_review_on_ingest: body.force_review_on_ingest ?? settings.force_review_on_ingest,
    }));
    projectApi.patchProjectMember.mockImplementation(async (_projectId, _memberId, body) => ({
      ...members[1],
      ...body,
    }));
    reviewApi.fetchReviews.mockResolvedValue([
      actionableReview,
      {
        ...actionableReview,
        id: "other-review",
        target_project_id: OTHER_PROJECT_ID,
        asset_title: "其它项目",
      },
      {
        ...actionableReview,
        id: "readonly-review",
        can_decide: false,
        asset_title: "不可处理记录",
      },
    ]);
    reviewApi.approveReview.mockResolvedValue(undefined);
    reviewApi.rejectReview.mockResolvedValue(undefined);
  });

  it("shows an honest loading state", () => {
    projectApi.fetchProjectSettings.mockReturnValue(new Promise(() => undefined));
    projectApi.fetchProjectMembers.mockReturnValue(new Promise(() => undefined));
    renderPage();
    expect(screen.getByText("正在加载项目设置…")).toBeInTheDocument();
  });

  it("renders the two-column work page from real project data without identity leakage", async () => {
    const { container } = renderPage();
    expect(await screen.findByRole("heading", { name: settings.name })).toBeInTheDocument();
    expect(container.querySelector(".ps74-layout")).toBeInTheDocument();
    expect(screen.getByText("客户访谈纪要")).toBeInTheDocument();
    expect(screen.queryByText("其它项目")).not.toBeInTheDocument();
    expect(screen.queryByText("不可处理记录")).not.toBeInTheDocument();
    expect(screen.queryByText("must-not-render@example.test")).not.toBeInTheDocument();
    expect(screen.queryByText("咨询总监")).not.toBeInTheDocument();
    expect(screen.queryByText("review-secret-id")).not.toBeInTheDocument();
    expect(screen.queryByText(PROJECT_ID)).not.toBeInTheDocument();
    expect(screen.getByText("由治理角色任命")).toBeInTheDocument();
  });

  it("keeps a coach read-only and does not fetch a decision queue", async () => {
    auth.projectRole = "coach";
    projectApi.fetchProjectSettings.mockResolvedValue({ ...settings, can_write: false });
    projectApi.fetchProjectMembers.mockResolvedValue({
      items: members,
      total: members.length,
      can_manage: false,
    });
    renderPage();
    expect(
      await screen.findByText("当前身份可查看项目设置，修改仅由本项目经理完成。"),
    ).toBeInTheDocument();
    expect(screen.getByText("当前身份无确认权限")).toBeInTheDocument();
    expect(reviewApi.fetchReviews).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "保存设置" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("调整交付顾问的项目内角色")).not.toBeInTheDocument();
  });

  it("shows a non-membership failure without rendering project data", async () => {
    projectApi.fetchProjectSettings.mockRejectedValue(
      new ApiError(403, "当前身份不是该项目成员", "project_membership_required"),
    );
    renderPage();
    expect(await screen.findByText("无法加载项目设置")).toBeInTheDocument();
    expect(screen.getByText("当前身份不是该项目成员")).toBeInTheDocument();
    expect(screen.queryByText(settings.name)).not.toBeInTheDocument();
  });

  it("saves only changed draft fields and adopts the successful backend value", async () => {
    renderPage();
    const route = await screen.findByLabelText("生命周期路线");
    fireEvent.change(route, { target: { value: "route_B" } });
    expect(screen.getByRole("button", { name: /保存设置/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /保存设置/ }));
    await waitFor(() =>
      expect(projectApi.updateProjectSettings).toHaveBeenCalledWith(PROJECT_ID, {
        lifecycle_route_key: "route_B",
      }),
    );
    expect(await screen.findByText("项目设置已保存")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /保存设置/ })).not.toBeInTheDocument();
  });

  it("retains the draft after save failure so the user can retry", async () => {
    projectApi.updateProjectSettings.mockRejectedValue(new ApiError(503, "保存服务暂时不可用"));
    renderPage();
    const route = await screen.findByLabelText("生命周期路线");
    fireEvent.change(route, { target: { value: "route_B" } });
    fireEvent.click(screen.getByRole("button", { name: /保存设置/ }));
    expect(await screen.findByText("保存服务暂时不可用")).toBeInTheDocument();
    expect(route).toHaveValue("route_B");
    expect(screen.getByRole("button", { name: /保存设置/ })).toBeInTheDocument();
  });

  it("discards changes back to the last successful backend value", async () => {
    renderPage();
    const phase = await screen.findByLabelText("当前阶段");
    fireEvent.change(phase, { target: { value: "交付阶段" } });
    fireEvent.click(screen.getByRole("button", { name: /放弃未保存/ }));
    expect(phase).toHaveValue("诊断阶段");
    expect(screen.queryByRole("button", { name: /保存设置/ })).not.toBeInTheDocument();
    expect(projectApi.updateProjectSettings).not.toHaveBeenCalled();
  });

  it("only lets can_manage project managers change coach and consultant rows", async () => {
    renderPage();
    const role = await screen.findByLabelText("调整交付顾问的项目内角色");
    fireEvent.change(role, { target: { value: "coach" } });
    await waitFor(() =>
      expect(projectApi.patchProjectMember).toHaveBeenCalledWith(PROJECT_ID, "member-consultant", {
        project_role: "coach",
      }),
    );
    expect(screen.queryByLabelText("调整项目负责人的项目内角色")).not.toBeInTheDocument();
  });

  it("refreshes the exact-project queue after an authorized decision", async () => {
    reviewApi.fetchReviews.mockResolvedValueOnce([actionableReview]).mockResolvedValueOnce([]);
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "通过" }));
    await waitFor(() =>
      expect(reviewApi.approveReview).toHaveBeenCalledWith(actionableReview.id, "项目经理确认通过"),
    );
    expect(await screen.findByText("暂无待确认任务")).toBeInTheDocument();
    expect(reviewApi.fetchReviews).toHaveBeenCalledTimes(2);
  });

  it("keeps the settings usable when the independent review request fails", async () => {
    reviewApi.fetchReviews.mockRejectedValue(new ApiError(503, "审核服务暂时不可用"));
    renderPage();
    expect(await screen.findByRole("heading", { name: settings.name })).toBeInTheDocument();
    expect(screen.getByText("待确认任务加载失败")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "项目基本信息" })).toBeInTheDocument();
  });
});
