import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { useEffect, useState } from "react";
import { MemoryRouter } from "react-router-dom";
import RouteGuard from "./RouteGuard";
import { can, type Capabilities } from "./permissions";

// 用可变的 mock 身份驱动守卫分支（守卫只消费 useAuth，不直接 fetch）。
const authState: {
  status: "loading" | "authenticated" | "anonymous" | "error";
  capabilities: Capabilities;
} = {
  status: "authenticated",
  capabilities: {
    isAdmin: false,
    isBoss: false,
    isConsultingDirector: false,
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
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
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

  it("provides a real recovery action when identity loading fails", () => {
    authState.status = "error";
    renderGuard(() => false);
    expect(screen.getByText("身份加载失败")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument();
  });

  it("clears project content when switching to admin and remounts after returning to business", () => {
    const loadProject = vi.fn();
    const clearProject = vi.fn();
    function ProjectSession() {
      const [question, setQuestion] = useState("");
      useEffect(() => {
        loadProject();
        return clearProject;
      }, []);
      return (
        <section>
          <h1>已加载的项目内容</h1>
          <input
            aria-label="项目问题草稿"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
          />
        </section>
      );
    }
    const page = () => (
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <RouteGuard cap={can.viewProject}>
          <ProjectSession />
        </RouteGuard>
      </MemoryRouter>
    );
    authState.capabilities = {
      isAdmin: false,
      isBoss: false,
      isConsultingDirector: false,
      isBusinessUser: true,
      isGovernance: false,
      hasProject: true,
      isProjectManager: true,
    };
    const { rerender } = render(page());
    fireEvent.change(screen.getByRole("textbox", { name: "项目问题草稿" }), {
      target: { value: "切换前的项目问题" },
    });
    expect(loadProject).toHaveBeenCalledTimes(1);

    authState.capabilities = {
      ...authState.capabilities,
      isAdmin: true,
      isBusinessUser: false,
    };
    rerender(page());
    expect(screen.getByText("当前账号无此入口")).toBeInTheDocument();
    expect(screen.queryByText("已加载的项目内容")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "项目问题草稿" })).not.toBeInTheDocument();
    expect(clearProject).toHaveBeenCalledTimes(1);
    expect(loadProject).toHaveBeenCalledTimes(1);

    authState.capabilities = {
      ...authState.capabilities,
      isAdmin: false,
      isBusinessUser: true,
    };
    rerender(page());
    expect(screen.getByText("已加载的项目内容")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "项目问题草稿" })).toHaveValue("");
    expect(loadProject).toHaveBeenCalledTimes(2);
  });
});
