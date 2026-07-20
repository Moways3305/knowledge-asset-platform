import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import IdentityMenu, { wecomOAuthModeForUserAgent } from "./IdentityMenu";
import { login, logout } from "../api/auth";
import { startWecomOAuth } from "../api/admin";

const me = {
  userId: "u1",
  name: "Alice",
  email: "alice@example.com",
  companyRoles: ["admin"],
  isBusinessUser: true,
  canDiscoverL5: true,
  projects: [{ projectId: "p1", projectName: "Alpha 项目", projectRole: "project_manager" }],
};

const authState: {
  authMe: typeof me | null;
  status: "authenticated" | "anonymous" | "loading" | "error";
  setAuthMe: ReturnType<typeof vi.fn>;
  reload: ReturnType<typeof vi.fn>;
} = {
  authMe: me,
  status: "authenticated",
  setAuthMe: vi.fn(),
  reload: vi.fn(),
};

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({
    authMe: authState.authMe,
    status: authState.status,
    setAuthMe: authState.setAuthMe,
    reload: authState.reload,
  }),
}));

vi.mock("../api/auth", () => ({
  login: vi.fn(),
  logout: vi.fn(),
}));

vi.mock("../api/admin", () => ({
  startWecomOAuth: vi.fn(),
}));

describe("IdentityMenu", () => {
  beforeEach(() => {
    authState.authMe = me;
    authState.status = "authenticated";
    authState.setAuthMe.mockReset();
    authState.reload.mockReset();
    vi.mocked(login).mockReset();
    vi.mocked(logout).mockReset();
    vi.mocked(startWecomOAuth).mockReset();
  });

  it("hides the login form by default after the user is logged in", async () => {
    render(<IdentityMenu />);

    fireEvent.click(screen.getByText("Alice"));

    expect(screen.getByText("平台身份：管理员")).toBeInTheDocument();
    expect(screen.getByText("Alpha 项目")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("登录邮箱")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("密码")).not.toBeInTheDocument();
    expect(screen.queryByText(/开发环境/)).not.toBeInTheDocument();
  });

  it("reveals the login form only after an explicit switch-account action", async () => {
    render(<IdentityMenu />);

    fireEvent.click(screen.getByText("Alice"));
    fireEvent.click(screen.getByText("切换账号"));

    await waitFor(() => {
      expect(screen.getByPlaceholderText("登录邮箱")).toBeInTheDocument();
      expect(screen.getByPlaceholderText("密码")).toBeInTheDocument();
    });
    expect(screen.getByText("使用企业微信登录 Kivo，或使用已分配的账号密码。")).toBeInTheDocument();
  });

  it("keeps 企业微信 as the login method and starts web QR mode in normal browsers", async () => {
    authState.authMe = null;
    authState.status = "anonymous";
    vi.mocked(startWecomOAuth).mockResolvedValue({
      authorize_url: "/auth-started",
    });

    render(<IdentityMenu />);
    fireEvent.click(screen.getByText("未登录"));
    fireEvent.click(screen.getByText("企业微信"));

    expect(screen.getByText("企业微信")).toBeInTheDocument();
    expect(screen.queryByText("Kivo 登录")).not.toBeInTheDocument();
    await waitFor(() => expect(startWecomOAuth).toHaveBeenCalledWith("web_qr"));
  });

  it("selects client mode inside WeCom client user agents", () => {
    expect(wecomOAuthModeForUserAgent("Mozilla/5.0 wxwork/4.1.20")).toBe("client");
    expect(wecomOAuthModeForUserAgent("Mozilla/5.0 Chrome/120.0")).toBe("web_qr");
  });
});
