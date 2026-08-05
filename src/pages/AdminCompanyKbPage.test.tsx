import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  createCompanyKnowledgeBase,
  deleteCompanyKnowledgeBase,
  fetchCompanyKnowledgeBase,
} from "../api/admin";
import AdminCompanyKbPage from "./AdminCompanyKbPage";

const capabilities = {
  isAdmin: false,
  isBoss: true,
  isConsultingDirector: false,
  isBusinessUser: true,
  isGovernance: true,
  hasProject: false,
  isProjectManager: false,
};

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ capabilities }),
}));

vi.mock("../api/admin", () => ({
  createCompanyKnowledgeBase: vi.fn(),
  deleteCompanyKnowledgeBase: vi.fn(),
  fetchCompanyKnowledgeBase: vi.fn(),
}));

const emptyState = {
  exists: false,
  display_name: null,
  status: null,
  created_at: null,
  available: false,
  availability_summary: "尚未创建公司知识库",
};

describe("AdminCompanyKbPage compact lifecycle state", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchCompanyKnowledgeBase).mockResolvedValue(emptyState);
  });

  it("renders a compact semantic empty card with a content-width create action", async () => {
    const { container } = render(<AdminCompanyKbPage />);
    expect(await screen.findByText("尚未创建")).toBeInTheDocument();
    expect(container.querySelector(".ckb-empty-card .ckb-empty-icon svg")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建公司知识库" })).toBeInTheDocument();
    expect(container.querySelector(".pp-support-section")).toHaveClass("is-empty");
    expect(container.querySelector(".ckb-actions")).not.toBeInTheDocument();
  });

  it("keeps creation connected to the real API and adopts its returned state", async () => {
    vi.mocked(createCompanyKnowledgeBase).mockResolvedValue({
      ...emptyState,
      exists: true,
      display_name: "公司知识库",
      status: "active",
      created_at: "2026-07-22T08:00:00Z",
      available: true,
      availability_summary: "公司知识库可用",
    });
    render(<AdminCompanyKbPage />);
    fireEvent.click(await screen.findByRole("button", { name: "创建公司知识库" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "创建公司知识库" }),
    );
    await waitFor(() => expect(createCompanyKnowledgeBase).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("公司知识库可用")).toBeInTheDocument();
    expect(deleteCompanyKnowledgeBase).not.toHaveBeenCalled();
  });
});
