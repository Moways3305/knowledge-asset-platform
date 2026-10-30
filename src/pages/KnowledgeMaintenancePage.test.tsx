import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import KnowledgeMaintenancePage from "./KnowledgeMaintenancePage";
import { fetchMaintenance } from "../api/knowledgeTrust";
import { ApiError } from "../api/http";

vi.mock("../api/knowledgeTrust", () => ({ fetchMaintenance: vi.fn() }));
beforeEach(() => vi.resetAllMocks());

it("shows actionable maintenance records and bounded pagination", async () => {
  vi.mocked(fetchMaintenance).mockResolvedValue({
    total: 1,
    page: 1,
    page_size: 25,
    items: [
      {
        asset_id: "a",
        title: "公司制度",
        scope: "company",
        freshness: "due",
        review_due_at: null,
        needs_correction: true,
        awaiting_my_verification: false,
      },
    ],
  });
  render(
    <MemoryRouter>
      <KnowledgeMaintenancePage />
    </MemoryRouter>,
  );
  await screen.findByText("公司制度");
  expect(screen.getByRole("link", { name: "处理纠错" })).toHaveAttribute(
    "href",
    "/knowledge/a?maintenance=corrections",
  );
  expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
});

it("supports retry and a clear empty state", async () => {
  vi.mocked(fetchMaintenance)
    .mockRejectedValueOnce(new ApiError(503, "暂时不可用"))
    .mockResolvedValueOnce({ total: 0, page: 1, page_size: 25, items: [] });
  render(
    <MemoryRouter>
      <KnowledgeMaintenancePage />
    </MemoryRouter>,
  );
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "重试" }));
  expect(await screen.findByText(/暂无待办/)).toBeInTheDocument();
});
