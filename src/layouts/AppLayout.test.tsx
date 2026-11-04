import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AppLayout from "./AppLayout";
import { logout } from "../api/auth";
import { fetchNotificationUnreadCount, fetchNotifications } from "../api/notifications";
import { fetchWorkbenchOverview } from "../api/workbench";

const auth = vi.hoisted(() => ({
  reload: vi.fn(),
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
    reload: auth.reload,
  }),
}));

vi.mock("../api/auth", () => ({
  logout: vi.fn(),
}));

vi.mock("../api/notifications", () => ({
  fetchNotificationUnreadCount: vi.fn(),
  fetchNotifications: vi.fn(),
  markNotificationRead: vi.fn(),
  markNotificationsRead: vi.fn(),
}));
vi.mock("../api/workbench", () => ({ fetchWorkbenchOverview: vi.fn() }));
vi.mock("../workbench/WorkbenchContext", () => ({
  WorkbenchProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  useWorkbench: () => ({
    overview: {
      task_center: {
        summary: { needs_action: 0, running: 0, attention: 0, completed_today: 0 },
        priority_items: [],
        my_tasks: [],
        running_jobs: [],
        attention_items: [],
        recent_completed: [],
      },
    },
    state: "ready",
    refresh: vi.fn(),
  }),
}));

function renderLayout(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<div>home</div>} />
          <Route path="*" element={<div>page</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("AppLayout shell contract", () => {
  beforeEach(() => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      writable: true,
      value: 1024,
    });
    auth.reload.mockReset();
    vi.mocked(logout).mockReset();
    vi.mocked(fetchNotificationUnreadCount).mockResolvedValue({ unread_count: 0 });
    // AppLayout tests cover shell composition, while NotificationBell tests own its async
    // loading contract. Keep this request pending so it cannot update after a shell assertion.
    vi.mocked(fetchNotifications).mockImplementation(() => new Promise(() => {}));
    vi.mocked(fetchWorkbenchOverview).mockResolvedValue({
      task_center: {
        status: "empty",
        error_code: null,
        summary: { needs_action: 0, running: 0, attention: 0, completed_today: 0 },
        priority_items: [],
        my_tasks: [],
        running_jobs: [],
        attention_items: [],
        recent_completed: [],
      },
      todos: { status: "empty", error_code: null, items: [], total: 0 },
      operations: { status: "empty", error_code: null, data: null },
      projects: { status: "empty", error_code: null, items: [], total: 0 },
      recent_activity: { status: "empty", error_code: null, items: [], total: 0 },
    });
    auth.capabilities.isAdmin = true;
    auth.capabilities.isBoss = true;
    auth.capabilities.isConsultingDirector = false;
    auth.capabilities.isBusinessUser = true;
    auth.capabilities.isGovernance = true;
    auth.capabilities.hasProject = true;
    auth.capabilities.isProjectManager = true;
  });

  it("makes the parent breadcrumb clickable and returns to the previous page", async () => {
    sessionStorage.clear();
    renderLayout("/original-access");
    expect(screen.getByRole("link", { name: "进入审批中心" })).toHaveAttribute("href", "/review");
    fireEvent.click(screen.getByRole("link", { name: "进入审批中心" }));
    await waitFor(() =>
      expect(document.querySelector(".deck-title")).toHaveTextContent("升级审核"),
    );
    fireEvent.click(screen.getByRole("link", { name: "返回上一页" }));
    await waitFor(() =>
      expect(document.querySelector(".deck-title")).toHaveTextContent("原文访问审批"),
    );
  });

  it("keeps the product brand and real identity menu in the shell", () => {
    const { container } = renderLayout();
    const logos = screen.getAllByRole("img", { name: "MOWAYS 博维咨询" });
    expect(logos).toHaveLength(2);
    logos.forEach((logo) => expect(logo).toHaveAttribute("src", "/moways-logo.png"));
    expect(screen.queryByText("KAP")).not.toBeInTheDocument();
    expect(container.querySelector(".rail-sub")).toHaveTextContent("博维知识资产平台");
    expect(container.querySelector(".deck-title")).toHaveTextContent("我的工作");
    expect(screen.getByRole("button", { name: /布局验收用户/ })).toBeInTheDocument();
    expect(container.querySelector(".rail-foot .rail-identity .idm-trigger")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "帮助与更新" }));
    expect(screen.getByRole("link", { name: "帮助" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "登出当前会话" })).not.toBeInTheDocument();
  });

  it("groups features into five modules and keeps management tools in their local menu", () => {
    renderLayout("/admin/ingest");
    const nav = screen.getByRole("navigation", { name: "主导航" });
    expect(within(nav).getAllByRole("link")).toHaveLength(5);
    expect(within(nav).getByRole("link", { name: "管理中心" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).queryByRole("link", { name: "入库管理" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "切换管理模块" }));
    expect(screen.getByRole("link", { name: "入库管理" })).toHaveAttribute("href", "/admin/ingest");
    expect(screen.getByRole("link", { name: "人员权限" })).toHaveAttribute("href", "/admin/people");
  });

  it("offers logout through the existing identity menu and refreshes the shared identity", async () => {
    vi.mocked(logout).mockResolvedValue(undefined);
    auth.reload.mockResolvedValue(undefined);
    renderLayout();

    fireEvent.click(screen.getByRole("button", { name: /布局验收用户/ }));
    fireEvent.click(screen.getByRole("button", { name: "登出当前会话" }));

    await waitFor(() => expect(logout).toHaveBeenCalledTimes(1));
    expect(auth.reload).toHaveBeenCalledTimes(1);
  });

  it("shows scoped model configuration navigation to project managers", () => {
    auth.capabilities.isAdmin = false;
    auth.capabilities.isGovernance = false;
    renderLayout("/admin/weknora-models");
    fireEvent.click(screen.getByRole("button", { name: "切换管理模块" }));
    expect(screen.getByRole("link", { name: "知识库" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "模型配置" })).toHaveAttribute(
      "href",
      "/admin/weknora-models",
    );
  });

  it("hides model configuration navigation from ordinary project members", () => {
    auth.capabilities.isAdmin = false;
    auth.capabilities.isBoss = false;
    auth.capabilities.isGovernance = false;
    auth.capabilities.isProjectManager = false;
    renderLayout();
    expect(screen.getByRole("link", { name: "知识库" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "模型配置" })).not.toBeInTheDocument();
  });

  it("opens the project directory instead of silently choosing the first project", () => {
    renderLayout();
    expect(screen.getByRole("link", { name: "项目空间" })).toHaveAttribute("href", "/projects");
    expect(screen.queryByRole("button", { name: "切换项目" })).not.toBeInTheDocument();
  });

  it("uses the same permitted project and full menu in mobile navigation", () => {
    renderLayout("/projects");
    expect(screen.getByRole("link", { name: "底部项目空间" })).toHaveAttribute("href", "/projects");
    fireEvent.click(screen.getByRole("button", { name: "打开我的与全部功能" }));
    expect(screen.getByRole("dialog", { name: "我的" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "我的项目" })).toHaveAttribute("href", "/projects");
    expect(screen.queryByRole("button", { name: "切换项目" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "原文访问审批" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "我的项目" }));
    expect(screen.queryByRole("dialog", { name: "我的" })).not.toBeInTheDocument();
  });

  it("hides project business entries for admin even when project membership remains assigned", () => {
    auth.capabilities.isBoss = false;
    auth.capabilities.isBusinessUser = false;
    auth.capabilities.isGovernance = false;
    renderLayout("/admin/ingest");
    fireEvent.click(screen.getByRole("button", { name: "切换管理模块" }));

    expect(screen.queryByRole("link", { name: "项目空间" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "项目知识库" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "项目设置" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "底部项目空间" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "入库管理" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "登录安全" })).toBeInTheDocument();
  });

  it("names project views while keeping their parent workspace active", () => {
    const overview = renderLayout("/project/project-real-64");
    expect(overview.container.querySelector(".deck-title")).toHaveTextContent("项目概览");
    expect(screen.getByRole("link", { name: "项目空间" })).toHaveClass("active");
    overview.unmount();

    const qa = renderLayout("/project/project-real-64?view=qa");
    expect(qa.container.querySelector(".deck-title")).toHaveTextContent("项目问答");
    qa.unmount();

    const knowledge = renderLayout("/project/project-real-64/knowledge");
    expect(knowledge.container.querySelector(".deck-title")).toHaveTextContent("项目资料");
    expect(screen.getByRole("link", { name: "项目空间" })).toHaveClass("active");
    knowledge.unmount();

    const settings = renderLayout("/project/project-real-64/settings");
    expect(settings.container.querySelector(".deck-title")).toHaveTextContent("项目设置");
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
    expect(screen.getByRole("link", { name: "工作台" })).toHaveAttribute("title", "工作台");
  });

  it("clears desktop collapse when crossing into tablet and mobile navigation", () => {
    const { container } = renderLayout();
    const shell = container.querySelector(".app-layout");
    fireEvent.click(screen.getByRole("button", { name: "折叠主导航" }));
    expect(shell).toHaveClass("is-rail-collapsed");

    window.innerWidth = 800;
    fireEvent.resize(window);
    expect(shell).not.toHaveClass("is-rail-collapsed");
    expect(screen.getByRole("link", { name: "工作台" })).not.toHaveAttribute("title");

    window.innerWidth = 929;
    fireEvent.resize(window);
    expect(shell).not.toHaveClass("is-rail-collapsed");
    fireEvent.click(screen.getByRole("button", { name: "折叠主导航" }));
    window.innerWidth = 390;
    fireEvent.resize(window);
    fireEvent.click(screen.getByRole("button", { name: "打开导航" }));
    expect(shell).toHaveClass("is-mobile-nav-open");
    expect(shell).not.toHaveClass("is-rail-collapsed");
    expect(screen.getByRole("dialog", { name: "我的" })).toBeInTheDocument();

    window.innerWidth = 701;
    fireEvent.resize(window);
    expect(shell).toHaveClass("is-mobile-nav-open");
    window.innerWidth = 860;
    fireEvent.resize(window);
    expect(shell).toHaveClass("is-mobile-nav-open");
    window.innerWidth = 861;
    fireEvent.resize(window);
    expect(shell).not.toHaveClass("is-mobile-nav-open");
    expect(document.body.style.overflow).not.toBe("hidden");
  });

  it("keeps the slim header with the shared task status and notification actions", () => {
    const { container } = renderLayout();
    const header = container.querySelector(".deck");
    expect(header).toHaveTextContent("我的工作");
    expect(
      screen.getByRole("button", { name: "通知中心，0 项待处理，0 条未读" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /打开任务中心/ })).toBeInTheDocument();
    expect(header).not.toHaveTextContent(/搜索|导出|新建项目/);
    expect(header?.querySelector("input")).toBeNull();
  });

  it("keeps pure admin out of people and project business navigation", () => {
    auth.capabilities.isAdmin = true;
    auth.capabilities.isBoss = false;
    auth.capabilities.isGovernance = false;
    auth.capabilities.isBusinessUser = false;
    auth.capabilities.hasProject = false;
    auth.capabilities.isProjectManager = false;
    renderLayout("/admin/ingest");
    fireEvent.click(screen.getByRole("button", { name: "切换管理模块" }));
    expect(screen.getByRole("link", { name: "审计日志" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "通知中心，0 项待处理，0 条未读" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "人员权限" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "项目设置" })).not.toBeInTheDocument();
  });
});
