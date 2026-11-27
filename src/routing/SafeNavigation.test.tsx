import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  BrowserRouter,
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { HistoryBackButton, SafeNavigationProvider, useSafeNavigation } from "./SafeNavigation";

const api = vi.hoisted(() => ({
  fetchKnowledgeDetail: vi.fn(),
  fetchProjectOverview: vi.fn(),
}));
vi.mock("../api/knowledge", () => ({ fetchKnowledgeDetail: api.fetchKnowledgeDetail }));
vi.mock("../api/project", () => ({ fetchProjectOverview: api.fetchProjectOverview }));

const auth = vi.hoisted(() => ({
  authMe: { userId: "nav-user", activeCompanyRole: "consultant" },
  capabilities: {
    isAdmin: true,
    isBoss: true,
    isConsultingDirector: true,
    isBusinessUser: true,
    isGovernance: true,
    hasProject: true,
    isProjectManager: true,
  },
}));
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({
    status: "authenticated",
    capabilities: auth.capabilities,
    authMe: auth.authMe,
  }),
}));

function Harness() {
  const { goBack } = useSafeNavigation();
  const navigate = useNavigate();
  const location = useLocation();
  return (
    <>
      <button onClick={() => navigate("/knowledge/asset", { replace: true })}>关闭维护弹窗</button>
      <button onClick={() => navigate("/projects")}>去项目</button>
      <button onClick={() => void goBack()} type="button">
        返回
      </button>
      <HistoryBackButton fallback="/knowledge">返回知识库</HistoryBackButton>
      <output>{`${location.pathname}${location.search}${location.hash}`}</output>
      <output data-testid="navigation-source">{JSON.stringify(location.state)}</output>
    </>
  );
}

function renderHistory(
  entries: Array<{ pathname: string; search?: string; hash?: string; state?: unknown }>,
) {
  sessionStorage.setItem(
    "kap.safe-navigation.v2:nav-user:consultant",
    JSON.stringify(entries.map((entry) => ({ search: "", ...entry }))),
  );
  render(
    <MemoryRouter initialEntries={["/missing"]}>
      <SafeNavigationProvider>
        <Routes>
          <Route path="*" element={<Harness />} />
        </Routes>
      </SafeNavigationProvider>
    </MemoryRouter>,
  );
}

describe("SafeNavigationProvider", () => {
  beforeEach(() => {
    sessionStorage.clear();
    auth.authMe = { userId: "nav-user", activeCompanyRole: "consultant" };
    api.fetchKnowledgeDetail.mockReset().mockResolvedValue({});
    api.fetchProjectOverview.mockReset().mockResolvedValue({});
    auth.capabilities = {
      isAdmin: true,
      isBoss: true,
      isConsultingDirector: true,
      isBusinessUser: true,
      isGovernance: true,
      hasProject: true,
      isProjectManager: true,
    };
  });

  it("returns to the most recent valid KAP page and preserves an allowed filter", async () => {
    renderHistory([{ pathname: "/knowledge", search: "?scope=project" }]);
    fireEvent.click(screen.getByRole("button", { name: "返回" }));
    await waitFor(() => expect(screen.getByText("/knowledge?scope=project")).toBeInTheDocument());
  });

  it("replaces a closed drawer entry instead of reopening it on Back", async () => {
    sessionStorage.setItem(
      "kap.safe-navigation.v2:nav-user:consultant",
      JSON.stringify([
        { pathname: "/help", search: "" },
        { pathname: "/knowledge-maintenance", search: "?type=review" },
      ]),
    );
    render(
      <MemoryRouter initialEntries={["/knowledge/asset?maintenance=review"]}>
        <SafeNavigationProvider>
          <Harness />
        </SafeNavigationProvider>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "关闭维护弹窗" }));
    await screen.findByText("/knowledge/asset");
    fireEvent.click(screen.getByRole("button", { name: "返回" }));
    await screen.findByText("/knowledge-maintenance?type=review");
    fireEvent.click(screen.getByRole("button", { name: "返回" }));
    await screen.findByText("/help");
  });

  it("recognizes the guarded completed review route", async () => {
    renderHistory([{ pathname: "/review/completed" }]);
    fireEvent.click(screen.getByRole("button", { name: "返回" }));
    await waitFor(() => expect(screen.getByText("/review/completed")).toBeInTheDocument());
  });

  it.each([
    "/knowledge-maintenance",
    "/company-governance",
    "/original-access/grants",
    "/admin/naming-rules",
    "/my/workbuddy",
    "/ai-workspace",
    "/ai-workspace/agents/knowledge-maintenance",
  ])("returns to the originating workspace %s with its filters", async (pathname) => {
    renderHistory([{ pathname: "/help" }, { pathname, search: "?page=2" }]);
    fireEvent.click(screen.getByRole("button", { name: "返回" }));
    await waitFor(() => expect(screen.getByText(`${pathname}?page=2`)).toBeInTheDocument());
  });

  it("does not return to directory governance after governance access is removed", async () => {
    auth.capabilities = {
      ...auth.capabilities,
      isBoss: false,
      isConsultingDirector: false,
      isGovernance: false,
    };
    renderHistory([{ pathname: "/help" }, { pathname: "/admin/naming-rules" }]);
    fireEvent.click(screen.getByRole("button", { name: "返回" }));
    await waitFor(() => expect(screen.getByText("/help")).toBeInTheDocument());
  });

  it("skips a deleted dynamic page and continues to an older valid page", async () => {
    api.fetchKnowledgeDetail.mockRejectedValueOnce(new Error("not found"));
    renderHistory([{ pathname: "/help" }, { pathname: "/knowledge/deleted-asset" }]);
    fireEvent.click(screen.getByRole("button", { name: "返回" }));
    await waitFor(() => expect(screen.getByText("/help")).toBeInTheDocument());
  });

  it("skips a page no longer allowed by current capabilities", async () => {
    auth.capabilities = {
      ...auth.capabilities,
      isAdmin: false,
      isBoss: false,
      isConsultingDirector: false,
      isGovernance: false,
    };
    renderHistory([{ pathname: "/help" }, { pathname: "/admin/audit" }]);
    fireEvent.click(screen.getByRole("button", { name: "返回" }));
    await waitFor(() => expect(screen.getByText("/help")).toBeInTheDocument());
  });

  it("never follows external or protocol-relative history entries", async () => {
    renderHistory([
      { pathname: "/help" },
      { pathname: "https://outside.example/path" },
      { pathname: "//outside.example/path" },
    ]);
    fireEvent.click(screen.getByRole("button", { name: "返回" }));
    await waitFor(() => expect(screen.getByText("/help")).toBeInTheDocument());
  });

  it("falls back to today's dashboard when no valid history exists", async () => {
    renderHistory([]);
    fireEvent.click(screen.getByRole("button", { name: "返回" }));
    await waitFor(() => expect(screen.getByText("/")).toBeInTheDocument());
  });

  it("returns to an article section without dropping its fragment", async () => {
    renderHistory([
      { pathname: "/help", search: "?article=maintenance-agent", hash: "#follow-up" },
    ]);
    fireEvent.click(screen.getByRole("button", { name: "返回" }));
    await screen.findByText("/help?article=maintenance-agent#follow-up");
  });

  it("restores an upload's original list source without persisting unrelated page data", async () => {
    const state = {
      backTo: "/my/knowledge?keyword=guide&page=3",
      backLabel: "返回我的知识",
      source: "personal",
    };
    renderHistory([
      {
        pathname: "/upload",
        search: "?source=local",
        state: { ...state, privateDraft: "must-not-persist" },
      },
    ]);
    fireEvent.click(screen.getByRole("button", { name: "返回" }));
    await screen.findByText("/upload?source=local");
    expect(JSON.parse(screen.getByTestId("navigation-source").textContent!)).toEqual(state);
    expect(sessionStorage.getItem("kap.safe-navigation.v2:nav-user:consultant")).not.toContain(
      "privateDraft",
    );
  });

  it("keeps a standalone Back control within the router", async () => {
    render(
      <MemoryRouter initialEntries={["/knowledge/item"]}>
        <Harness />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("link", { name: "返回知识库" }));
    await screen.findByText("/knowledge");
  });

  it.each(["ctrlKey", "metaKey", "shiftKey", "altKey"])(
    "does not hijack the browser's %s link action",
    async (modifier) => {
      renderHistory([{ pathname: "/help" }]);
      const link = screen.getByRole("link", { name: "返回知识库" });
      const click = new MouseEvent("click", { bubbles: true, cancelable: true, [modifier]: true });
      // Capture the router's decision while cancelling jsdom's later native navigation.
      let preventedByRouter = false;
      const preventNative = (event: MouseEvent) => {
        preventedByRouter = event.defaultPrevented;
        event.preventDefault();
      };
      document.addEventListener("click", preventNative, { once: true });
      fireEvent(link, click);
      expect(preventedByRouter).toBe(false);
      expect(screen.getByText("/missing")).toBeInTheDocument();
    },
  );

  it("can navigate even if browser storage becomes unavailable", async () => {
    renderHistory([{ pathname: "/help" }]);
    const storage = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("storage unavailable");
    });
    try {
      fireEvent.click(screen.getByRole("button", { name: "返回" }));
      await screen.findByText("/help");
    } finally {
      storage.mockRestore();
    }
  });

  it("does not reuse another account's workspace session history", async () => {
    auth.authMe = { userId: "another-user", activeCompanyRole: "consultant" };
    renderHistory([{ pathname: "/ai-workspace", search: "?session=old-account" }]);
    fireEvent.click(screen.getByRole("button", { name: "返回" }));
    await screen.findByText("/");
    expect(screen.queryByText(/old-account/)).not.toBeInTheDocument();
  });

  it("does not overwrite a newer navigation when a Back permission check finishes late", async () => {
    let finish!: (value: object) => void;
    api.fetchKnowledgeDetail.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    renderHistory([{ pathname: "/knowledge/asset" }]);
    fireEvent.click(screen.getByRole("button", { name: "返回" }));
    await waitFor(() => expect(api.fetchKnowledgeDetail).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "去项目" }));
    await screen.findByText("/projects");
    await act(async () => {
      finish({});
    });
    expect(screen.getByText("/projects")).toBeInTheDocument();
  });

  it("does not follow a mismatched native history entry in BrowserRouter", async () => {
    window.history.replaceState({ idx: 0, key: "safe" }, "", "/help");
    window.history.pushState({ idx: 1, key: "stale" }, "", "/admin/audit");
    window.history.pushState({ idx: 2, key: "current" }, "", "/knowledge");
    sessionStorage.setItem(
      "kap.safe-navigation.v2:nav-user:consultant",
      JSON.stringify([{ pathname: "/help", search: "", historyIndex: 0 }]),
    );

    render(
      <BrowserRouter>
        <SafeNavigationProvider>
          <Routes>
            <Route path="*" element={<Harness />} />
          </Routes>
        </SafeNavigationProvider>
      </BrowserRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "返回" }));

    await waitFor(() => expect(screen.getByText("/help")).toBeInTheDocument());
    expect(window.history.state.idx).toBe(2);
  });
});
