import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  createCompanyKnowledgeBase,
  fetchCompanyKnowledgeBase,
  fetchPeople,
  fetchPerson,
  patchProjectMembership,
  removeProjectMembership,
  setCompanyRole,
  setUserStatus,
} from "../api/admin";
import { ApiError } from "../api/http";
import type { Capabilities } from "../auth/permissions";
import type { PersonDTO } from "../types/people";
import AdminPeoplePage from "./AdminPeoplePage";

const authState: { capabilities: Capabilities } = {
  capabilities: {
    isAdmin: true,
    isBoss: false,
    isConsultingDirector: false,
    isBusinessUser: false,
    isGovernance: false,
    hasProject: false,
    isProjectManager: false,
  },
};

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => authState,
}));

vi.mock("../api/admin", () => ({
  createCompanyKnowledgeBase: vi.fn(),
  fetchCompanyKnowledgeBase: vi.fn(),
  fetchPeople: vi.fn(),
  fetchPerson: vi.fn(),
  patchProjectMembership: vi.fn(),
  reconcileWecomIdentity: vi.fn(),
  removeProjectMembership: vi.fn(),
  revokeUserSessions: vi.fn(),
  setCompanyRole: vi.fn(),
  setUserPassword: vi.fn(),
  setUserStatus: vi.fn(),
  upsertProjectMembership: vi.fn(),
}));

const person: PersonDTO = {
  user_id: "person-ref",
  name: "测试人员",
  email: "person@example.test",
  phone: null,
  wecom_bound: false,
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  recent_session_at: null,
  active_session_count: 1,
  password_set: true,
  password_set_at: "2026-01-01T00:00:00Z",
  company_roles: [
    { role_id: "role-boss", company_role: "boss", status: "active" },
    { role_id: "role-consultant", company_role: "consultant", status: "inactive" },
  ],
  project_memberships: [
    {
      membership_id: "membership-ref",
      project_id: "project-ref",
      project_name: "示例项目",
      project_role: "consultant",
      status: "active",
      joined_at: "2026-01-01T00:00:00Z",
    },
  ],
};

function roleRow(label: string) {
  const labelNode = screen
    .getAllByText(label)
    .find((node) => node.closest(".pp-project-role-item"));
  const row = labelNode?.closest<HTMLElement>(".pp-project-role-item");
  expect(row).not.toBeNull();
  return within(row!);
}

async function renderDetail() {
  render(
    <MemoryRouter>
      <AdminPeoplePage />
    </MemoryRouter>,
  );
  fireEvent.click(await screen.findByRole("button", { name: "查看 / 治理" }));
  await screen.findByText("用户详情 · 治理");
}

describe("AdminPeoplePage governance controls", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.capabilities = {
      isAdmin: true,
      isBoss: false,
      isConsultingDirector: false,
      isBusinessUser: false,
      isGovernance: false,
      hasProject: false,
      isProjectManager: false,
    };
    vi.mocked(fetchPeople).mockResolvedValue({ items: [person], total: 1 });
    vi.mocked(fetchPerson).mockResolvedValue(person);
    vi.mocked(fetchCompanyKnowledgeBase).mockResolvedValue({
      exists: false,
      display_name: null,
      status: null,
      created_at: null,
      available: false,
      availability_summary: "尚未创建",
    });
    vi.mocked(createCompanyKnowledgeBase).mockReset();
    vi.mocked(setCompanyRole).mockResolvedValue(person);
    vi.mocked(setUserStatus).mockResolvedValue(person);
    vi.mocked(patchProjectMembership).mockResolvedValue(person.project_memberships[0]);
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  it("does not expose personnel management controls to pure admin", async () => {
    await renderDetail();
    expect(screen.queryByRole("button", { name: "撤销全部会话" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "设置 / 重置密码" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "停用账号" })).not.toBeInTheDocument();
    expect(roleRow("总经理").queryByRole("button")).not.toBeInTheDocument();
    expect(roleRow("顾问").queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByText("新增 / 更新成员关系")).not.toBeInTheDocument();
    expect(
      screen.getByText("总经理或咨询总监任命项目经理；项目经理在本项目内维护辅导老师与顾问。"),
    ).toBeInTheDocument();
    expect(fetchCompanyKnowledgeBase).not.toHaveBeenCalled();
  });

  it("lets the general manager govern business roles and appoint project leaders", async () => {
    authState.capabilities = {
      ...authState.capabilities,
      isAdmin: false,
      isBoss: true,
      isBusinessUser: true,
      isGovernance: true,
    };
    await renderDetail();
    expect(screen.getByRole("button", { name: "停用账号" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "设置 / 重置密码" })).toBeInTheDocument();
    expect(roleRow("总经理").getByRole("button", { name: "停用" })).toBeInTheDocument();
    expect(roleRow("咨询总监").getByRole("button", { name: "授予" })).toBeInTheDocument();
    expect(roleRow("顾问").getByRole("button", { name: "恢复" })).toBeInTheDocument();
    expect(screen.queryAllByText("管理员").length).toBeGreaterThan(0);
    expect(screen.getByText("新增 / 更新成员关系")).toBeInTheDocument();
    // 公司知识库已迁移到独立页面 /admin/company-kb，此处不再加载。
    expect(screen.queryByText("公司知识库")).not.toBeInTheDocument();
  });

  it("lets consulting directors with governance rights manage all company roles including boss", async () => {
    authState.capabilities = {
      ...authState.capabilities,
      isAdmin: false,
      isConsultingDirector: true,
      isBusinessUser: true,
      isGovernance: true,
    };
    await renderDetail();
    expect(roleRow("总经理").getByRole("button", { name: "停用" })).toBeInTheDocument();
    expect(roleRow("咨询总监").getByRole("button", { name: "授予" })).toBeInTheDocument();
    expect(roleRow("顾问").getByRole("button", { name: "恢复" })).toBeInTheDocument();
    expect(screen.getByText("新增 / 更新成员关系")).toBeInTheDocument();
  });

  it("renders a list-first workspace without sensitive identity fields", async () => {
    const { container } = render(
      <MemoryRouter>
        <AdminPeoplePage />
      </MemoryRouter>,
    );
    expect(await screen.findByText("人员名册")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const summary = screen.getByLabelText("人员摘要");
    expect(summary).toHaveClass("gp-summary-panel");
    expect(summary).toHaveTextContent("当前加载");
    expect(summary.querySelectorAll(".gp-summary-icon svg")).toHaveLength(4);
    expect(container.querySelector(".gp-governance-console")?.children).toHaveLength(2);
    expect(container.querySelector(".gp-summary")).not.toBeInTheDocument();
    expect(container.innerHTML).not.toMatch(
      /person-ref|person@example\.test|membership-ref|project-ref|role-boss/,
    );
    expect(screen.getByText("未绑定")).toBeInTheDocument();
    expect(container.querySelector(".pp-field-mark svg")).toBeInTheDocument();
  });

  it("summarizes 3+ project relationships and exposes the complete list inline", async () => {
    const densePerson: PersonDTO = {
      ...person,
      company_roles: [
        ...person.company_roles,
        { role_id: "role-director", company_role: "consulting_director", status: "active" },
        { role_id: "role-third", company_role: "consultant", status: "active" },
      ],
      project_memberships: ["甲项目", "乙项目", "丙项目", "丁项目"].map((name, index) => ({
        ...person.project_memberships[0],
        membership_id: `membership-${index}`,
        project_id: `project-${index}`,
        project_name: name,
      })),
    };
    vi.mocked(fetchPeople).mockResolvedValue({ items: [densePerson], total: 1 });
    vi.mocked(fetchPerson).mockResolvedValue(densePerson);

    const { container } = render(
      <MemoryRouter>
        <AdminPeoplePage />
      </MemoryRouter>,
    );
    const expandBtn = await screen.findByRole("button", { name: "+2 查看全部" });
    expect(container.querySelectorAll(".pp-cell-projects .pp-project-role-item")).toHaveLength(2);
    expect(screen.queryByText("丙项目")).not.toBeInTheDocument();

    // 点击展开，所有 4 个项目关系应内联显示
    fireEvent.click(expandBtn);
    const projectsCell = container.querySelector(".pp-cell-projects")!;
    const allItems = projectsCell.querySelectorAll(".pp-project-role-item");
    expect(allItems).toHaveLength(4);
    expect(screen.getByText("甲项目")).toBeInTheDocument();
    expect(screen.getByText("丁项目")).toBeInTheDocument();
    // 不应泄露 session 敏感数据
    expect(container.innerHTML).not.toMatch(/membership-3|project-3/);
    // 展开后按钮文字应为"收起"
    expect(screen.getByRole("button", { name: "收起" })).toBeInTheDocument();

    // 再次点击收起
    fireEvent.click(screen.getByRole("button", { name: "收起" }));
    expect(container.querySelectorAll(".pp-cell-projects .pp-project-role-item")).toHaveLength(2);
    expect(screen.queryByText("丙项目")).not.toBeInTheDocument();
  });

  it("sends real filters and opens detail only after selection", async () => {
    render(
      <MemoryRouter>
        <AdminPeoplePage />
      </MemoryRouter>,
    );
    await screen.findByText("人员名册");
    fireEvent.change(screen.getByLabelText("搜索姓名"), { target: { value: "测试" } });
    fireEvent.click(screen.getByRole("button", { name: "搜索 / 刷新" }));
    await waitFor(() =>
      expect(fetchPeople).toHaveBeenLastCalledWith(expect.objectContaining({ q: "测试" })),
    );
    fireEvent.click(screen.getByRole("button", { name: "查看 / 治理" }));
    expect(await screen.findByRole("dialog", { name: "人员治理详情" })).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("person@example.test");
  });

  it("ignores a stale detail response after selecting another person", async () => {
    const secondPerson = { ...person, user_id: "person-second", name: "第二人员" };
    vi.mocked(fetchPeople).mockResolvedValueOnce({ items: [person, secondPerson], total: 2 });
    let resolveFirst!: (value: PersonDTO) => void;
    let resolveSecond!: (value: PersonDTO) => void;
    vi.mocked(fetchPerson).mockImplementation((userId) =>
      userId === person.user_id
        ? new Promise<PersonDTO>((resolve) => {
            resolveFirst = resolve;
          })
        : new Promise<PersonDTO>((resolve) => {
            resolveSecond = resolve;
          }),
    );
    render(
      <MemoryRouter>
        <AdminPeoplePage />
      </MemoryRouter>,
    );
    const buttons = await screen.findAllByRole("button", { name: "查看 / 治理" });
    fireEvent.click(buttons[0]);
    fireEvent.click(buttons[1]);
    await act(async () => resolveSecond(secondPerson));
    const dialog = await screen.findByRole("dialog", { name: "人员治理详情" });
    expect(within(dialog).getByText("第二人员")).toBeInTheDocument();
    await act(async () => resolveFirst(person));
    await waitFor(() => expect(within(dialog).getByText("第二人员")).toBeInTheDocument());
    expect(within(dialog).queryByText("测试人员")).not.toBeInTheDocument();
  });

  it("does not let a completed write for person A cancel person B detail loading", async () => {
    authState.capabilities = {
      ...authState.capabilities,
      isAdmin: false,
      isBoss: true,
      isBusinessUser: true,
      isGovernance: true,
    };
    const secondPerson = { ...person, user_id: "person-second", name: "第二人员" };
    vi.mocked(fetchPeople).mockResolvedValueOnce({ items: [person, secondPerson], total: 2 });
    let resolveSecond!: (value: PersonDTO) => void;
    vi.mocked(fetchPerson).mockImplementation((userId) =>
      userId === person.user_id
        ? Promise.resolve(person)
        : new Promise<PersonDTO>((resolve) => {
            resolveSecond = resolve;
          }),
    );
    let resolveStatus!: (value: PersonDTO) => void;
    vi.mocked(setUserStatus).mockReturnValueOnce(
      new Promise<PersonDTO>((resolve) => {
        resolveStatus = resolve;
      }),
    );
    render(
      <MemoryRouter>
        <AdminPeoplePage />
      </MemoryRouter>,
    );
    let buttons = await screen.findAllByRole("button", { name: "查看 / 治理" });
    fireEvent.click(buttons[0]);
    await screen.findByRole("dialog", { name: "人员治理详情" });
    fireEvent.click(screen.getByRole("button", { name: "停用账号" }));
    fireEvent.click(screen.getByRole("button", { name: "关闭人员详情" }));
    buttons = screen.getAllByRole("button", { name: "查看 / 治理" });
    fireEvent.click(buttons[1]);

    await act(async () => resolveStatus(person));
    expect(fetchPerson).toHaveBeenCalledTimes(2);
    await act(async () => resolveSecond(secondPerson));
    const dialog = await screen.findByRole("dialog", { name: "人员治理详情" });
    expect(within(dialog).getByText("第二人员")).toBeInTheDocument();
  });

  it.each([
    [new ApiError(503, "raw people token"), "人员列表暂时无法加载，请稍后重试"],
    [new ApiError(403, "raw forbidden", "raw_reason"), "当前身份没有执行此操作的权限。"],
  ])("maps list failures safely", async (reason, expected) => {
    vi.mocked(fetchPeople).mockRejectedValueOnce(reason);
    const { container } = render(
      <MemoryRouter>
        <AdminPeoplePage />
      </MemoryRouter>,
    );
    expect(await screen.findByText(expected)).toBeInTheDocument();
    expect(container.innerHTML).not.toMatch(/raw people token|raw forbidden|raw_reason/);
  });

  it("uses a compact empty state", async () => {
    vi.mocked(fetchPeople).mockResolvedValueOnce({ items: [], total: 0 });
    render(
      <MemoryRouter>
        <AdminPeoplePage />
      </MemoryRouter>,
    );
    expect(await screen.findByText("无匹配用户")).toBeInTheDocument();
    expect(document.querySelector(".gp-empty-visual svg")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument();
  });

  it("keeps a failed role update local and hides the raw error", async () => {
    authState.capabilities = {
      ...authState.capabilities,
      isAdmin: false,
      isBoss: true,
      isBusinessUser: true,
      isGovernance: true,
    };
    vi.mocked(setCompanyRole).mockRejectedValueOnce(new ApiError(500, "raw role secret"));
    await renderDetail();
    fireEvent.click(roleRow("总经理").getByRole("button", { name: "停用" }));
    expect(await screen.findByText("更新公司角色失败")).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("raw role secret");
    expect(screen.getByText("人员名册")).toBeInTheDocument();
  });

  it("shows local loading while an account status update is pending", async () => {
    authState.capabilities = {
      ...authState.capabilities,
      isAdmin: false,
      isBoss: true,
      isBusinessUser: true,
      isGovernance: true,
    };
    let resolveStatus!: (value: PersonDTO) => void;
    vi.mocked(setUserStatus).mockReturnValueOnce(
      new Promise<PersonDTO>((resolve) => {
        resolveStatus = resolve;
      }),
    );
    await renderDetail();
    fireEvent.click(screen.getByRole("button", { name: "停用账号" }));
    expect(screen.getByRole("button", { name: "处理中…" })).toBeDisabled();
    await act(async () => resolveStatus(person));
    await waitFor(() => expect(setUserStatus).toHaveBeenCalledWith("person-ref", "inactive"));
  });

  it("recovers only the failed membership row and hides the raw error", async () => {
    authState.capabilities = {
      ...authState.capabilities,
      isAdmin: false,
      isBoss: true,
      isBusinessUser: true,
      isGovernance: true,
    };
    vi.mocked(fetchPerson).mockResolvedValue({
      ...person,
      project_memberships: [{ ...person.project_memberships[0], project_role: "project_manager" }],
    });
    vi.mocked(patchProjectMembership).mockRejectedValueOnce(
      new ApiError(500, "raw membership secret"),
    );
    await renderDetail();
    const projectRow = screen
      .getAllByText("示例项目")
      .map((node) => node.closest<HTMLElement>(".pp-project-role-item"))
      .find((row) => row && within(row).queryByRole("button", { name: "停用" }));
    expect(projectRow).not.toBeNull();
    fireEvent.click(within(projectRow!).getByRole("button", { name: "停用" }));
    expect(await screen.findByText("更新成员状态失败")).toBeInTheDocument();
    expect(within(projectRow!).getByRole("button", { name: "停用" })).toBeEnabled();
    expect(document.body.innerHTML).not.toContain("raw membership secret");
  });

  it("turns last project manager protection into inline guidance to project settings", async () => {
    authState.capabilities = {
      ...authState.capabilities,
      isAdmin: false,
      isBoss: true,
      isBusinessUser: true,
      isGovernance: true,
    };
    vi.mocked(fetchPerson).mockResolvedValue({
      ...person,
      project_memberships: [{ ...person.project_memberships[0], project_role: "project_manager" }],
    });
    vi.mocked(removeProjectMembership).mockRejectedValueOnce(
      new ApiError(409, "raw project manager detail", "last_project_manager_protected"),
    );
    await renderDetail();
    fireEvent.click(screen.getByRole("button", { name: "移除" }));

    const guidance = await screen.findByRole("alert");
    expect(guidance).toHaveTextContent("这是最后一位有效项目经理");
    expect(guidance).not.toHaveTextContent("raw project manager detail");
    expect(within(guidance).getByRole("link", { name: /前往.*项目设置/ })).toHaveAttribute(
      "href",
      "/project/project-ref/settings",
    );
  });
});
