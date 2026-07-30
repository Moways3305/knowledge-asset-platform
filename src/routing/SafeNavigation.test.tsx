import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SafeNavigationProvider, useSafeNavigation } from "./SafeNavigation";

const api = vi.hoisted(() => ({
  fetchKnowledgeDetail: vi.fn(),
  fetchProjectOverview: vi.fn(),
}));
vi.mock("../api/knowledge", () => ({ fetchKnowledgeDetail: api.fetchKnowledgeDetail }));
vi.mock("../api/project", () => ({ fetchProjectOverview: api.fetchProjectOverview }));

const auth = vi.hoisted(() => ({
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
  }),
}));

function Harness() {
  const { goBack } = useSafeNavigation();
  const location = useLocation();
  return (
    <>
      <button onClick={() => void goBack()} type="button">
        返回
      </button>
      <output>{`${location.pathname}${location.search}`}</output>
    </>
  );
}

function renderHistory(entries: Array<{ pathname: string; search?: string }>) {
  sessionStorage.setItem(
    "kap.safe-navigation.v1",
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
});
