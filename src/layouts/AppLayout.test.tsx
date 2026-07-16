import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AppLayout from "./AppLayout";

const auth = vi.hoisted(() => ({
  capabilities: {
    isAdmin: true,
    isBoss: true,
    isConsultingDirector: false,
    isBusinessUser: true,
    isGovernance: true,
    hasProject: true,
    isProjectManager: true,
  },
  authMe: {
    userId: "00000000-0000-0000-0000-000000000064",
    name: "一位名称很长但不应撑破顶栏的布局验收用户",
    email: "layout@example.test",
    companyRoles: ["admin", "boss"],
    isBusinessUser: true,
    canDiscoverL5: true,
    projects: [
      {
        projectId: "project-real-64",
        projectName: "真实项目上下文",
        projectRole: "project_manager",
      },
    ],
  },
}));

vi.mock("../auth/AuthContext", () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  useAuth: () => ({
    capabilities: auth.capabilities,
    authMe: auth.authMe,
    status: "authenticated",
    setAuthMe: vi.fn(),
    reload: vi.fn(),
  }),
}));

function renderLayout() {
  return render(
    <MemoryRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<div>home</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("AppLayout shell contract", () => {
  beforeEach(() => {
    auth.capabilities.isAdmin = true;
    auth.capabilities.isBoss = true;
    auth.capabilities.isConsultingDirector = false;
    auth.capabilities.isBusinessUser = true;
    auth.capabilities.isGovernance = true;
    auth.capabilities.hasProject = true;
    auth.capabilities.isProjectManager = true;
  });

  it("keeps the product brand and real identity menu in the shell", () => {
    const { container } = renderLayout();
    expect(screen.getByText("KAP")).toBeInTheDocument();
    expect(container.querySelector(".rail-sub")).toHaveTextContent("博维知识资产平台");
    expect(container.querySelector(".deck-title")).toHaveTextContent("今日工作台");
    expect(screen.getByRole("button", { name: /布局验收用户/ })).toBeInTheDocument();
    expect(container.querySelector(".rail-foot .rail-identity .idm-trigger")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "使用说明" })).toBeInTheDocument();
  });

  it("filters navigation with the existing capabilities", () => {
    auth.capabilities.isAdmin = false;
    auth.capabilities.isGovernance = false;
    renderLayout();
    expect(screen.getByRole("link", { name: "知识资产库" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "模型配置" })).not.toBeInTheDocument();
  });

  it("builds project navigation from the real auth project id", () => {
    renderLayout();
    expect(screen.getByRole("link", { name: "项目看板" })).toHaveAttribute(
      "href",
      "/project/project-real-64/knowledge",
    );
    expect(screen.getByRole("link", { name: "项目设置" })).toHaveAttribute(
      "href",
      "/project/project-real-64/settings",
    );
  });

  it("exposes accessible names and native tooltips in collapsed mode", () => {
    const { container } = renderLayout();
    fireEvent.click(screen.getByRole("button", { name: "折叠主导航" }));

    expect(container.querySelector(".app-layout")).toHaveClass("is-rail-collapsed");
    expect(screen.getByRole("button", { name: "展开主导航" })).toHaveAttribute(
      "title",
      "展开主导航",
    );
    expect(screen.getByRole("button", { name: "展开主导航" })).toHaveClass("rail-collapse");
    expect(screen.getByRole("link", { name: "今日工作台" })).toHaveAttribute("title", "今日工作台");
  });

  it("does not add uncontracted global actions to the slim header", () => {
    const { container } = renderLayout();
    const header = container.querySelector(".deck");
    expect(header).toHaveTextContent("今日工作台");
    expect(header).not.toHaveTextContent(/搜索|导出|新建项目|通知/);
    expect(header?.querySelector("input")).toBeNull();
  });

  it("keeps pure admin out of people and project business navigation", () => {
    auth.capabilities.isAdmin = true;
    auth.capabilities.isBoss = false;
    auth.capabilities.isGovernance = false;
    auth.capabilities.isBusinessUser = false;
    auth.capabilities.hasProject = false;
    auth.capabilities.isProjectManager = false;
    renderLayout();
    expect(screen.getByRole("link", { name: "审计日志" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "人员权限" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "项目设置" })).not.toBeInTheDocument();
  });
});
