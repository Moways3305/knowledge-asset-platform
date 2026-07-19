import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchAgentRegistry,
  fetchPermissionRules,
  setAgentRegistryEnabled,
  updatePermissionRule,
} from "../api/admin";
import { fetchAuthMe } from "../api/auth";
import { ApiError } from "../api/http";
import type { AgentRegistryRuleDTO, PermissionRuleDTO } from "../types/permission";
import AdminPermissionsPage from "./AdminPermissionsPage";

vi.mock("../api/admin", () => ({
  fetchAgentRegistry: vi.fn(),
  fetchPermissionRules: vi.fn(),
  setAgentRegistryEnabled: vi.fn(),
  updatePermissionRule: vi.fn(),
}));
vi.mock("../api/auth", () => ({ fetchAuthMe: vi.fn() }));

const rule: PermissionRuleDTO = {
  rule_id: "rule-secret-id",
  rule_key: "internal.secret.rule",
  rule_group: "access_request",
  rule_type: "numeric",
  display_name: "原文访问有效期",
  value_bool: null,
  value_number: 7,
  value_text: null,
  default_bool: null,
  default_number: 5,
  default_text: null,
  unit: "天",
  description: "设置访问授权的有效时间。",
  editable: true,
  enabled: true,
  updated_by_user_id: "updater-secret",
  updated_by_name: "治理负责人",
  updated_at: "2026-07-20T01:00:00Z",
};
const agent: AgentRegistryRuleDTO = {
  id: "agent-secret-id",
  provider: "provider-secret",
  agent_name: "项目知识助手",
  capability: "semantic_search",
  allowed_scope: "project",
  allowed_project_id: "project-secret-id",
  max_confidentiality_level: "L5-secret",
  max_ai_access_level: "A4-secret",
  enabled: true,
  risk_level: "secret-risk",
  risk_note: "token=secret-risk-note",
  created_at: "2026-07-20T01:00:00Z",
  updated_at: "2026-07-20T01:00:00Z",
};

const me = {
  userId: "me-secret",
  name: "安全管理员",
  email: "admin@example.test",
  companyRoles: ["admin"],
  isBusinessUser: false,
  canDiscoverL5: false,
  projects: [],
};

describe("AdminPermissionsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchAuthMe).mockResolvedValue(me);
    vi.mocked(fetchPermissionRules).mockResolvedValue({ items: [rule], total: 1 });
    vi.mocked(fetchAgentRegistry).mockResolvedValue({ items: [agent] });
    vi.mocked(updatePermissionRule).mockResolvedValue({ ...rule, value_number: 9 });
    vi.mocked(setAgentRegistryEnabled).mockResolvedValue({ ...agent, enabled: false });
  });

  it("renders the rule-first workspace without internal fields", async () => {
    const { container } = render(<AdminPermissionsPage />);
    expect(await screen.findByText("原文访问有效期")).toBeInTheDocument();
    expect(screen.getByText("外部助手白名单")).toBeInTheDocument();
    expect(screen.getByText("语义检索")).toBeInTheDocument();
    expect(
      screen.getByText("当前身份为只读模式，规则修改需总经理或咨询总监权限。"),
    ).toBeInTheDocument();
    for (const secret of [
      "rule-secret-id",
      "internal.secret.rule",
      "updater-secret",
      "agent-secret-id",
      "provider-secret",
      "project-secret-id",
      "L5-secret",
      "A4-secret",
      "token=secret-risk-note",
      "admin@example.test",
    ])
      expect(container.innerHTML).not.toContain(secret);
  });

  it("updates only the active agent row for admin", async () => {
    render(<AdminPermissionsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "停用" }));
    await waitFor(() =>
      expect(setAgentRegistryEnabled).toHaveBeenCalledWith("agent-secret-id", false),
    );
    expect(await screen.findByText("已停用")).toBeInTheDocument();
  });

  it("recovers only the failed whitelist row and hides the raw error", async () => {
    vi.mocked(setAgentRegistryEnabled).mockRejectedValueOnce(
      new ApiError(500, "raw whitelist token"),
    );
    render(<AdminPermissionsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "停用" }));
    expect(await screen.findByText("白名单状态保存失败，请重试。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "停用" })).toBeEnabled();
    expect(document.body.innerHTML).not.toContain("raw whitelist token");
  });

  it("edits a numeric rule for governance and recovers a local failure", async () => {
    vi.mocked(fetchAuthMe).mockResolvedValue({ ...me, companyRoles: ["boss"] });
    vi.mocked(updatePermissionRule).mockRejectedValueOnce(
      new ApiError(500, "raw permission token"),
    );
    render(<AdminPermissionsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "编辑" }));
    fireEvent.change(screen.getByLabelText("原文访问有效期数值"), { target: { value: "9" } });
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    expect(await screen.findByText("规则保存失败，请重试。")).toBeInTheDocument();
    expect(screen.getByDisplayValue("9")).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("raw permission token");
  });

  it.each([
    [new ApiError(503, "raw server token"), "权限规则暂时无法加载，请稍后重试。"],
    [new ApiError(403, "raw forbidden", "raw_reason"), "当前身份没有权限规则查看权限。"],
  ])("maps permission failures safely", async (reason, expected) => {
    vi.mocked(fetchPermissionRules).mockRejectedValueOnce(reason);
    const { container } = render(<AdminPermissionsPage />);
    expect(await screen.findByText(expected)).toBeInTheDocument();
    expect(container.innerHTML).not.toMatch(/raw server token|raw forbidden|raw_reason/);
  });

  it("uses compact empty states for rules and agents", async () => {
    vi.mocked(fetchPermissionRules).mockResolvedValueOnce({ items: [], total: 0 });
    vi.mocked(fetchAgentRegistry).mockResolvedValueOnce({ items: [] });
    render(<AdminPermissionsPage />);
    expect(await screen.findByText("暂无符合条件的权限规则")).toBeInTheDocument();
    expect(screen.getByText("暂无已登记的外部助手")).toBeInTheDocument();
  });
});
