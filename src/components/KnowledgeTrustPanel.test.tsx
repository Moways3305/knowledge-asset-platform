import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import KnowledgeTrustPanel from "./KnowledgeTrustPanel";
import {
  fetchTrust,
  fetchReplacementOptions,
  reportCorrection,
  replaceTrust,
  transitionCorrection,
  type TrustState,
} from "../api/knowledgeTrust";
import { ApiError } from "../api/http";

vi.mock("../api/knowledgeTrust", () => ({
  fetchTrust: vi.fn(),
  fetchReplacementOptions: vi.fn(),
  reportCorrection: vi.fn(),
  replaceTrust: vi.fn(),
  transitionCorrection: vi.fn(),
  saveTrustPolicy: vi.fn(),
  reviewTrust: vi.fn(),
}));
const initial: TrustState = {
  asset_id: "old",
  updated_at: "2026-10-08T01:00:00Z",
  maintainer_user_id: "manager",
  maintainer_name: "维护人",
  review_due_at: "2026-11-08T01:00:00Z",
  verified_at: null,
  freshness: "unreviewed",
  replacement_asset_id: null,
  can_manage: true,
  corrections: [],
  maintainers: [{ id: "manager", name: "维护人" }],
};
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(fetchTrust).mockResolvedValue(initial);
});
function open() {
  render(
    <MemoryRouter>
      <KnowledgeTrustPanel assetId="old" />
    </MemoryRouter>,
  );
}

it("does not expose governance controls to ordinary readers", async () => {
  vi.mocked(fetchTrust).mockResolvedValue({ ...initial, can_manage: false, maintainers: [] });
  open();
  await screen.findByText("尚未复核");
  expect(screen.queryByText("安排复核与处理旧版")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "提出纠错" })).toBeDisabled();
});

it("reports a correction with the loaded concurrency token", async () => {
  vi.mocked(reportCorrection).mockResolvedValue(initial);
  open();
  await screen.findByText("尚未复核");
  fireEvent.change(screen.getByLabelText("处理说明或纠错问题"), {
    target: { value: "第三段数据有误" },
  });
  fireEvent.click(screen.getByRole("button", { name: "提出纠错" }));
  await waitFor(() =>
    expect(reportCorrection).toHaveBeenCalledWith("old", {
      expected_updated_at: initial.updated_at,
      reason: "第三段数据有误",
    }),
  );
});

it("requires candidate verification and explicit old-version archive confirmation", async () => {
  vi.mocked(fetchReplacementOptions).mockResolvedValue([{ asset_id: "new", title: "新版资料" }]);
  vi.mocked(fetchTrust).mockImplementation(async (id) =>
    id === "new" ? { ...initial, asset_id: "new", freshness: "verified" } : initial,
  );
  vi.mocked(replaceTrust).mockResolvedValue({
    ...initial,
    freshness: "archived",
    replacement_asset_id: "new",
  });
  open();
  await screen.findByText("尚未复核");
  fireEvent.click(screen.getByText("安排复核与处理旧版"));
  fireEvent.change(screen.getByLabelText("处理说明或纠错问题"), { target: { value: "新版替代" } });
  fireEvent.click(screen.getByRole("button", { name: "查找可关联新版" }));
  await screen.findByRole("option", { name: "新版资料" });
  fireEvent.change(screen.getByLabelText("新版资料", { exact: true }), {
    target: { value: "new" },
  });
  expect(screen.getByRole("button", { name: "关联新版并归档旧版" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "核对新版" }));
  await screen.findByText(/新版状态/);
  expect(screen.getByRole("button", { name: "关联新版并归档旧版" })).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "关联新版并归档旧版" }));
  await waitFor(() =>
    expect(replaceTrust).toHaveBeenCalledWith(
      "old",
      expect.objectContaining({
        replacement_asset_id: "new",
        expected_replacement_updated_at: initial.updated_at,
        confirm_archive: true,
      }),
    ),
  );
});

it("keeps conflict errors visible and does not silently retry writes", async () => {
  vi.mocked(reportCorrection).mockRejectedValue(new ApiError(409, "记录已更新，请刷新后重试"));
  open();
  await screen.findByText("尚未复核");
  fireEvent.change(screen.getByLabelText("处理说明或纠错问题"), { target: { value: "有误" } });
  fireEvent.click(screen.getByRole("button", { name: "提出纠错" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("记录已更新");
  expect(reportCorrection).toHaveBeenCalledTimes(1);
});

it("allows the reporter to reopen a resolved correction", async () => {
  vi.mocked(fetchTrust).mockResolvedValue({
    ...initial,
    can_manage: false,
    corrections: [
      {
        id: "ticket",
        status: "resolved",
        description: "有误",
        resolution: "已改",
        updated_at: "stamp",
        can_resolve: false,
        can_verify: true,
      },
    ],
  });
  vi.mocked(transitionCorrection).mockResolvedValue(initial);
  open();
  await screen.findByText("待提出者验证");
  fireEvent.change(screen.getByLabelText("处理说明或纠错问题"), {
    target: { value: "还没有解决" },
  });
  fireEvent.click(screen.getByRole("button", { name: "仍有问题，重新处理" }));
  await waitFor(() =>
    expect(transitionCorrection).toHaveBeenCalledWith("old", "ticket", {
      expected_updated_at: "stamp",
      reason: "还没有解决",
      action: "reopen",
    }),
  );
});
