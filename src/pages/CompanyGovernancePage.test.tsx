import { fireEvent, render, screen, waitFor, cleanup, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import CompanyGovernancePage from "./CompanyGovernancePage";
import { fetchGovernance, applyGovernance } from "../api/governance";

vi.mock("../api/governance", () => ({ fetchGovernance: vi.fn(), applyGovernance: vi.fn() }));
vi.mock("../api/http", () => ({ apiGet: vi.fn().mockResolvedValue({ items: [] }) }));
const item = {
  asset_id: "a",
  title: "历史研究报告",
  asset_status: "active",
  confidentiality_level: "L1",
  summary: "历史数据",
  updated_at: "2026-09-22T00:00:00Z",
  archived_at: null,
  archive_reason: null,
  signals: ["research_age"],
};
beforeEach(() => {
  vi.mocked(fetchGovernance).mockResolvedValue({
    items: [item],
    total: 1,
    page: 1,
    page_size: 25,
    counts: { all: 1, candidates: 1, archived: 0 },
  });
  vi.mocked(applyGovernance).mockResolvedValue({
    items: [{ asset_id: "a", success: true, message: "已归档" }],
  });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
it("requires selection, preview and reason before mutation", async () => {
  render(
    <MemoryRouter>
      <CompanyGovernancePage />
    </MemoryRouter>,
  );
  expect(await screen.findByRole("button", { name: "历史研究报告" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "预览归档" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByLabelText("选择 历史研究报告"));
  fireEvent.click(screen.getByRole("button", { name: "预览归档" }));
  expect(applyGovernance).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "确认归档" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("处理原因（必填）"), {
    target: { value: "已核验历史数据" },
  });
  fireEvent.click(screen.getByRole("button", { name: "确认归档" }));
  await waitFor(() =>
    expect(applyGovernance).toHaveBeenCalledWith(
      [item],
      "archive",
      "historical",
      "已核验历史数据",
      undefined,
    ),
  );
  expect(await screen.findByText(/本批完成 1 项/)).toBeInTheDocument();
});
it("clears selection when switching to archive centre", async () => {
  render(
    <MemoryRouter>
      <CompanyGovernancePage />
    </MemoryRouter>,
  );
  await screen.findByRole("button", { name: "历史研究报告" });
  fireEvent.click(screen.getByLabelText("选择 历史研究报告"));
  fireEvent.click(screen.getByRole("button", { name: "归档中心" }));
  await waitFor(() => expect(fetchGovernance).toHaveBeenCalledWith("archived", "", "", 1));
  expect(screen.queryByRole("button", { name: "预览恢复" })).not.toBeInTheDocument();
});

it("starts the existing preview from inspected detail and still requires a reason", async () => {
  render(
    <MemoryRouter>
      <CompanyGovernancePage />
    </MemoryRouter>,
  );
  fireEvent.click(await screen.findByRole("button", { name: "核验" }));
  const detail = screen.getByRole("dialog", { name: item.title });
  fireEvent.click(within(detail).getByRole("button", { name: "预览归档" }));
  expect(applyGovernance).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "确认归档" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("处理原因（必填）"), { target: { value: "核验后归档" } });
  fireEvent.click(screen.getByRole("button", { name: "确认归档" }));
  await waitFor(() =>
    expect(applyGovernance).toHaveBeenCalledWith(
      [item],
      "archive",
      "historical",
      "核验后归档",
      undefined,
    ),
  );
});
