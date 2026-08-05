import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/http";
import ProjectSettingsPage from "./ProjectSettingsPage";

const PROJECT_ID = "00000000-0000-0000-0000-000000000074";
const OTHER_PROJECT_ID = "00000000-0000-0000-0000-000000000075";

const projectApi = vi.hoisted(() => ({
  fetchProjectSettings: vi.fn(),
  fetchProjectDeletionReadiness: vi.fn(),
  updateProjectSettings: vi.fn(),
  fetchProjectMembers: vi.fn(),
  fetchCandidateMembers: vi.fn(),
  patchProjectMember: vi.fn(),
  fetchProjects: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  addProjectMember: vi.fn(),
  removeProjectMember: vi.fn(),
  deleteProject: vi.fn(),
}));
const reviewApi = vi.hoisted(() => ({
  fetchReviews: vi.fn(),
  approveReview: vi.fn(),
  rejectReview: vi.fn(),
}));
const adminApi = vi.hoisted(() => ({
  fetchPeople: vi.fn().mockResolvedValue({ items: [], total: 0 }),
}));
const auth = vi.hoisted(() => ({
  reload: vi.fn().mockResolvedValue(undefined),
  projectRole: "project_manager",
  capabilities: {
    isBoss: false,
    isConsultingDirector: false,
    isGovernance: false,
  },
}));

vi.mock("../api/project", () => projectApi);
vi.mock("../api/review", () => reviewApi);
vi.mock("../api/admin", () => adminApi);
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
        {
          projectId: OTHER_PROJECT_ID,
          projectName: "切换后的项目",
          projectRole: auth.projectRole,
        },
      ],
    },
    capabilities: auth.capabilities,
    reload: auth.reload,
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

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function ProjectSwitcher() {
  const navigate = useNavigate();
  return (
    <button onClick={() => navigate(`/project/${OTHER_PROJECT_ID}/settings`)}>切换到项目 B</button>
  );
}

function LocationProbe() {
  return <output aria-label="当前路径">{useLocation().pathname}</output>;
}

function HomeRoute() {
  const navigate = useNavigate();
  return (
    <>
      <div>今日工作台</div>
      <button onClick={() => navigate(-1)}>返回上一页</button>
    </>
  );
}

function renderPage(withPreviousEntry = false) {
  const settingsPath = `/project/${PROJECT_ID}/settings`;
  return render(
    <MemoryRouter
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      initialEntries={withPreviousEntry ? ["/previous", settingsPath] : [settingsPath]}
      initialIndex={withPreviousEntry ? 1 : 0}
    >
      <LocationProbe />
      <ProjectSwitcher />
      <Routes>
        <Route path="/project/:id/settings" element={<ProjectSettingsPage />} />
        <Route path="/review" element={<div>审核页</div>} />
        <Route path="/" element={<HomeRoute />} />
        <Route path="/previous" element={<div>先前页面</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ProjectSettingsPage reference implementation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    auth.projectRole = "project_manager";
    auth.capabilities.isBoss = false;
    auth.capabilities.isConsultingDirector = false;
    auth.capabilities.isGovernance = false;
    auth.reload.mockClear();
    projectApi.deleteProject.mockReset().mockResolvedValue(undefined);
    projectApi.fetchProjectSettings.mockResolvedValue({ ...settings });
    projectApi.fetchProjectDeletionReadiness.mockResolvedValue({
      can_delete: true,
      asset_count: 2,
      member_count: members.length,
      blockers: ["project_has_assets"],
    });
    projectApi.fetchProjectMembers.mockResolvedValue({
      items: members.map((member) => ({ ...member })),
      total: members.length,
      can_manage: true,
    });
    projectApi.fetchCandidateMembers.mockResolvedValue({
      items: [
        {
          user_id: "candidate-coach",
          name: "候选辅导老师",
          email: "candidate@example.test",
        },
      ],
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
    expect(screen.getByRole("option", { name: "历史阶段：诊断阶段" })).toBeInTheDocument();
    expect(screen.queryByText("先归档项目")).not.toBeInTheDocument();
    expect(screen.getByText(/仍有\s*2\s*个项目知识资产/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "前往项目知识库" })).toHaveAttribute(
      "href",
      `/project/${PROJECT_ID}/knowledge`,
    );
    expect(screen.queryByRole("button", { name: "删除项目" })).not.toBeInTheDocument();
  });

  it("closes the dialog, refreshes identity and replace-navigates after deletion succeeds", async () => {
    projectApi.fetchProjectDeletionReadiness.mockResolvedValue({
      can_delete: true,
      asset_count: 0,
      member_count: 3,
      blockers: [],
    });
    renderPage(true);
    fireEvent.click(await screen.findByRole("button", { name: "删除项目" }));
    const dialog = screen.getByRole("dialog", { name: `删除项目“${settings.name}”` });
    expect(dialog).toHaveTextContent("此操作不可恢复");
    expect(dialog).toHaveTextContent("一并移除 3 条项目成员关系");

    expect(within(dialog).getByRole("button", { name: "删除项目" })).toBeDisabled();
    expect(projectApi.deleteProject).not.toHaveBeenCalled();

    fireEvent.change(within(dialog).getByRole("textbox"), {
      target: { value: settings.name },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "删除项目" }));
    await waitFor(() => expect(projectApi.deleteProject).toHaveBeenCalledWith(PROJECT_ID));
    await waitFor(() => expect(auth.reload).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("今日工作台")).toBeInTheDocument();
    expect(screen.getByLabelText("当前路径")).toHaveTextContent("/");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByText(settings.name)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "返回上一页" }));
    expect(await screen.findByText("先前页面")).toBeInTheDocument();
    expect(screen.queryByText(settings.name)).not.toBeInTheDocument();
  });

  it("treats a delete-target 404 as an idempotent exit without a failure message", async () => {
    projectApi.fetchProjectDeletionReadiness.mockResolvedValue({
      can_delete: true,
      asset_count: 0,
      member_count: 2,
      blockers: [],
    });
    projectApi.deleteProject.mockRejectedValue(
      new ApiError(404, "项目不存在", "project_not_found"),
    );

    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "删除项目" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByRole("textbox"), {
      target: { value: settings.name },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "删除项目" }));

    expect(await screen.findByText("今日工作台")).toBeInTheDocument();
    expect(auth.reload).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/删除失败/)).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("uses a synchronous in-flight lock so rapid confirmation sends one delete request", async () => {
    const pendingDelete = deferred<void>();
    projectApi.fetchProjectDeletionReadiness.mockResolvedValue({
      can_delete: true,
      asset_count: 0,
      member_count: 2,
      blockers: [],
    });
    projectApi.deleteProject.mockReturnValue(pendingDelete.promise);

    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "删除项目" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByRole("textbox"), {
      target: { value: settings.name },
    });
    const confirm = within(dialog).getByRole("button", { name: "删除项目" });
    act(() => {
      confirm.click();
      confirm.click();
    });

    expect(projectApi.deleteProject).toHaveBeenCalledTimes(1);
    pendingDelete.resolve();
    expect(await screen.findByText("今日工作台")).toBeInTheDocument();
  });

  it("keeps asset, permission, unrelated 404 and network failures visible without leaving", async () => {
    projectApi.fetchProjectDeletionReadiness.mockResolvedValue({
      can_delete: true,
      asset_count: 0,
      member_count: 2,
      blockers: [],
    });
    const failures = [
      {
        error: new ApiError(409, "仍有资产", "project_has_assets"),
        message: "项目中仍有资产，请先前往项目知识库清空资产后再删除。",
      },
      {
        error: new ApiError(403, "禁止", "project_delete_forbidden"),
        message: "当前身份无权执行此操作",
      },
      {
        error: new ApiError(404, "依赖资源不存在", "dependent_resource_not_found"),
        message: "删除失败，请刷新项目状态后重试",
      },
      { error: new Error("network unavailable"), message: "删除失败，请刷新项目状态后重试" },
    ];

    for (const failure of failures) {
      projectApi.deleteProject.mockRejectedValueOnce(failure.error);
      const view = renderPage();
      fireEvent.click(await screen.findByRole("button", { name: "删除项目" }));
      const dialog = screen.getByRole("dialog");
      fireEvent.change(within(dialog).getByRole("textbox"), {
        target: { value: settings.name },
      });
      fireEvent.click(within(dialog).getByRole("button", { name: "删除项目" }));

      expect(await screen.findByText(failure.message)).toBeInTheDocument();
      expect(screen.getByLabelText("当前路径")).toHaveTextContent(
        `/project/${PROJECT_ID}/settings`,
      );
      expect(screen.getByRole("dialog")).toBeInTheDocument();
      expect(auth.reload).not.toHaveBeenCalled();
      view.unmount();
    }
  });

  it("keeps a coach read-only and does not fetch a decision queue", async () => {
    auth.projectRole = "coach";
    projectApi.fetchProjectSettings.mockResolvedValue({ ...settings, can_write: false });
    projectApi.fetchProjectMembers.mockResolvedValue({
      items: members,
      total: members.length,
      can_manage: false,
    });
    projectApi.fetchProjectDeletionReadiness.mockResolvedValue({
      can_delete: false,
      asset_count: 2,
      member_count: members.length,
      blockers: ["project_delete_forbidden", "project_has_assets"],
    });
    renderPage();
    expect(
      await screen.findByText("当前身份可查看项目设置，修改仅由本项目经理完成。"),
    ).toBeInTheDocument();
    expect(screen.getByText("当前身份无确认权限")).toBeInTheDocument();
    expect(reviewApi.fetchReviews).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "保存设置" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "删除项目" })).not.toBeInTheDocument();
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

  it("replaces a historical phase only after an explicit supported selection", async () => {
    renderPage();
    const phase = await screen.findByLabelText("当前阶段");
    expect(phase).toHaveValue("诊断阶段");
    fireEvent.change(phase, { target: { value: "诊断" } });
    fireEvent.click(screen.getByRole("button", { name: /保存设置/ }));
    await waitFor(() =>
      expect(projectApi.updateProjectSettings).toHaveBeenCalledWith(PROJECT_ID, {
        lifecycle_phase_key: "诊断",
      }),
    );
  });

  it("retains the draft after save failure so the user can retry", async () => {
    projectApi.updateProjectSettings.mockRejectedValue(new ApiError(503, "保存服务暂时不可用"));
    renderPage();
    const route = await screen.findByLabelText("生命周期路线");
    fireEvent.change(route, { target: { value: "route_B" } });
    fireEvent.click(screen.getByRole("button", { name: /保存设置/ }));
    expect(await screen.findByText("保存失败，未保存内容已保留")).toBeInTheDocument();
    expect(screen.queryByText("保存服务暂时不可用")).not.toBeInTheDocument();
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

  it("opens the add-member form and cancel restores the centered entry", async () => {
    const { container } = renderPage();
    const entry = await screen.findByRole("button", { name: "添加成员" });
    expect(container.querySelector(".ps74-member-action-row")).toContainElement(entry);

    fireEvent.click(entry);
    expect(await screen.findByLabelText("搜索用户")).toBeInTheDocument();
    expect(screen.getByLabelText("选择用户")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认添加" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "取消" })).toBeEnabled();
    expect(projectApi.fetchCandidateMembers).toHaveBeenCalledWith(PROJECT_ID);

    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(screen.queryByLabelText("搜索用户")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "添加成员" })).toBeInTheDocument();
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

  it("requires and submits the project manager's actual rejection reason", async () => {
    reviewApi.fetchReviews.mockResolvedValueOnce([actionableReview]).mockResolvedValueOnce([]);
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "驳回" }));
    expect(screen.getByRole("heading", { name: "驳回项目知识" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认驳回" }));

    expect(screen.getByText("请填写驳回理由")).toBeInTheDocument();
    expect(reviewApi.rejectReview).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("驳回理由"), {
      target: { value: "  缺少客户确认记录，请补充会议纪要。  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "确认驳回" }));

    await waitFor(() =>
      expect(reviewApi.rejectReview).toHaveBeenCalledWith(
        actionableReview.id,
        "缺少客户确认记录，请补充会议纪要。",
      ),
    );
    expect(screen.queryByRole("heading", { name: "驳回项目知识" })).not.toBeInTheDocument();
    expect(reviewApi.fetchReviews).toHaveBeenCalledTimes(2);
  });

  it("keeps the settings usable when the independent review request fails", async () => {
    reviewApi.fetchReviews.mockRejectedValue(new ApiError(503, "审核服务暂时不可用"));
    renderPage();
    expect(await screen.findByRole("heading", { name: settings.name })).toBeInTheDocument();
    expect(await screen.findByText("待确认任务加载失败")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "项目基本信息" })).toBeInTheDocument();
  });

  it("ignores stale settings and members when project B finishes before project A", async () => {
    const settingsA = deferred<typeof settings>();
    const membersA = deferred<{ items: typeof members; total: number; can_manage: boolean }>();
    const settingsB = {
      ...settings,
      project_id: OTHER_PROJECT_ID,
      name: "项目 B 设置",
      coach_name: "项目 B 辅导老师",
    };
    const membersB = {
      items: [{ ...members[1], member_id: "member-b", name: "项目 B 顾问" }],
      total: 1,
      can_manage: true,
    };
    projectApi.fetchProjectSettings.mockImplementation((pid) =>
      pid === PROJECT_ID ? settingsA.promise : Promise.resolve(settingsB),
    );
    projectApi.fetchProjectMembers.mockImplementation((pid) =>
      pid === PROJECT_ID ? membersA.promise : Promise.resolve(membersB),
    );
    reviewApi.fetchReviews.mockResolvedValue([]);

    renderPage();
    await waitFor(() => expect(projectApi.fetchProjectSettings).toHaveBeenCalledWith(PROJECT_ID));
    fireEvent.click(screen.getByRole("button", { name: "切换到项目 B" }));

    expect(await screen.findByRole("heading", { name: "项目 B 设置" })).toBeInTheDocument();
    expect(screen.getByText("项目 B 顾问")).toBeInTheDocument();

    await act(async () => {
      settingsA.resolve({ ...settings, name: "过期的项目 A 设置" });
      membersA.resolve({ items: members, total: members.length, can_manage: true });
      await Promise.all([settingsA.promise, membersA.promise]);
    });

    expect(screen.getByRole("heading", { name: "项目 B 设置" })).toBeInTheDocument();
    expect(screen.getByText("项目 B 顾问")).toBeInTheDocument();
    expect(screen.queryByText("过期的项目 A 设置")).not.toBeInTheDocument();
    expect(screen.queryByText("项目负责人")).not.toBeInTheDocument();
  });

  it("ignores a stale project A review queue after project B is active", async () => {
    const reviewsA = deferred<(typeof actionableReview)[]>();
    const settingsB = {
      ...settings,
      project_id: OTHER_PROJECT_ID,
      name: "项目 B 设置",
    };
    const reviewB = {
      ...actionableReview,
      id: "review-b",
      target_project_id: OTHER_PROJECT_ID,
      asset_title: "项目 B 待确认事项",
    };
    projectApi.fetchProjectSettings.mockImplementation((pid) =>
      Promise.resolve(pid === PROJECT_ID ? settings : settingsB),
    );
    projectApi.fetchProjectMembers.mockResolvedValue({
      items: members,
      total: members.length,
      can_manage: true,
    });
    reviewApi.fetchReviews
      .mockImplementationOnce(() => reviewsA.promise)
      .mockResolvedValueOnce([reviewB]);

    renderPage();
    expect(await screen.findByRole("heading", { name: settings.name })).toBeInTheDocument();
    await waitFor(() => expect(reviewApi.fetchReviews).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "切换到项目 B" }));

    expect(await screen.findByRole("heading", { name: "项目 B 设置" })).toBeInTheDocument();
    expect(await screen.findByText("项目 B 待确认事项")).toBeInTheDocument();

    await act(async () => {
      reviewsA.resolve([{ ...actionableReview, asset_title: "过期的项目 A 待确认事项" }]);
      await reviewsA.promise;
    });

    expect(screen.getByText("项目 B 待确认事项")).toBeInTheDocument();
    expect(screen.queryByText("过期的项目 A 待确认事项")).not.toBeInTheDocument();
  });
});
