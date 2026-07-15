import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  createCompanyKnowledgeBase,
  fetchCompanyKnowledgeBase,
  fetchPeople,
  fetchPerson,
} from "../api/admin";
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
    expect(screen.queryByText("管理员")).not.toBeInTheDocument();
    expect(screen.getByText("新增 / 更新成员关系")).toBeInTheDocument();
    await waitFor(() => expect(fetchCompanyKnowledgeBase).toHaveBeenCalled());
  });

  it("lets consulting directors manage director and consultant roles but not general managers", async () => {
    authState.capabilities = {
      ...authState.capabilities,
      isAdmin: false,
      isConsultingDirector: true,
      isBusinessUser: true,
      isGovernance: true,
    };
    await renderDetail();
    expect(roleRow("总经理").queryByRole("button")).not.toBeInTheDocument();
    expect(roleRow("咨询总监").getByRole("button", { name: "授予" })).toBeInTheDocument();
    expect(roleRow("顾问").getByRole("button", { name: "恢复" })).toBeInTheDocument();
    expect(screen.getByText("新增 / 更新成员关系")).toBeInTheDocument();
  });
});
