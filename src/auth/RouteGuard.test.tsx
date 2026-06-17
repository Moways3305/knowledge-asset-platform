import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import RouteGuard from "./RouteGuard";
import type { Capabilities } from "./permissions";

// 用可变的 mock 身份驱动守卫分支（守卫只消费 useAuth，不直接 fetch）。
const authState: {
  status: "loading" | "authenticated" | "anonymous" | "error";
  capabilities: Capabilities;
} = {
  status: "authenticated",
  capabilities: {
    isAdmin: false,
    isBusinessUser: false,
    isGovernance: false,
    hasProject: false,
    isProjectManager: false,
  },
};

vi.mock("./AuthContext", () => ({
  useAuth: () => authState,
}));

function renderGuard(cap: (c: Capabilities) => boolean) {
  return render(
    <MemoryRouter>
      <RouteGuard cap={cap}>
        <div>受保护内容</div>
      </RouteGuard>
    </MemoryRouter>,
  );
}

describe("RouteGuard", () => {
  beforeEach(() => {
    authState.status = "authenticated";
  });

  it("renders children when the capability is granted", () => {
    renderGuard(() => true);
    expect(screen.getByText("受保护内容")).toBeInTheDocument();
  });

  it("shows a no-access state (not children, not a load error) when denied", () => {
    renderGuard(() => false);
    expect(screen.queryByText("受保护内容")).not.toBeInTheDocument();
    expect(screen.getByText("当前账号无此入口")).toBeInTheDocument();
    expect(screen.getByText("返回今日工作台")).toBeInTheDocument();
  });

  it("prompts login when anonymous", () => {
    authState.status = "anonymous";
    renderGuard(() => false);
    expect(screen.getByText("请先登录")).toBeInTheDocument();
  });

  it("shows a placeholder while identity is loading", () => {
    authState.status = "loading";
    renderGuard(() => true);
    expect(screen.queryByText("受保护内容")).not.toBeInTheDocument();
    expect(screen.getByText("加载中…")).toBeInTheDocument();
  });
});
