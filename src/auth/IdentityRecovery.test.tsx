import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { AuthProvider } from "./AuthContext";
import LoginGate from "./LoginGate";
import { fetchAuthMe, switchActiveCompanyRole, type AuthMeVM } from "../api/auth";
import { ApiError } from "../api/http";

vi.mock("../api/auth", () => ({
  fetchAuthMe: vi.fn(),
  switchActiveCompanyRole: vi.fn(),
  login: vi.fn(),
}));
const identity: AuthMeVM = {
  userId: "test",
  name: "Test",
  email: "test@example.test",
  companyRoles: ["consultant"],
  activeCompanyRole: "consultant",
  isBusinessUser: true,
  canDiscoverL5: false,
  projects: [],
};
beforeEach(() => vi.resetAllMocks());
function setup() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <LoginGate>
          <p>业务页面</p>
        </LoginGate>
      </AuthProvider>
    </MemoryRouter>,
  );
}
it("uses the recovered authoritative identity", async () => {
  vi.mocked(fetchAuthMe).mockResolvedValue(identity);
  setup();
  expect(await screen.findByText("业务页面")).toBeInTheDocument();
});
it("requires explicit choice and never exposes protected content first", async () => {
  vi.mocked(fetchAuthMe).mockRejectedValue(
    new ApiError(403, "", "active_company_role_selection_required", {
      available_roles: ["admin", "consultant"],
    }),
  );
  vi.mocked(switchActiveCompanyRole).mockResolvedValue(identity);
  setup();
  expect(await screen.findByText("工作身份已变更，请选择当前要使用的身份。")).toBeInTheDocument();
  expect(screen.queryByText("业务页面")).not.toBeInTheDocument();
  expect(switchActiveCompanyRole).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "咨询顾问" }));
  await waitFor(() => expect(switchActiveCompanyRole).toHaveBeenCalledWith("consultant"));
  expect(await screen.findByText("业务页面")).toBeInTheDocument();
});
it("offers normal login for invalid credentials rather than a connection retry loop", async () => {
  vi.mocked(fetchAuthMe).mockRejectedValue(
    new ApiError(403, "", "active_company_role_cookie_invalid"),
  );
  setup();
  expect(await screen.findByLabelText("密码")).toBeInTheDocument();
  expect(screen.getByText("工作身份凭证已失效，请重新登录。")).toBeInTheDocument();
  expect(screen.queryByText("业务页面")).not.toBeInTheDocument();
});
it("does not grant access when no roles remain", async () => {
  vi.mocked(fetchAuthMe).mockRejectedValue(
    new ApiError(403, "", "active_company_role_unavailable"),
  );
  setup();
  expect(await screen.findByText("当前没有可用工作身份，请联系管理员。")).toBeInTheDocument();
  expect(screen.queryByText("业务页面")).not.toBeInTheDocument();
});
