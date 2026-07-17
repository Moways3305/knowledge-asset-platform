import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/http";
import {
  approveReview,
  fetchReviews,
  rejectReview,
  withdrawReviewConfirmation,
} from "../api/review";
import type { ReviewItemDTO } from "../types/review";
import ReviewPage from "./ReviewPage";

vi.mock("../api/review", () => ({
  approveReview: vi.fn(),
  fetchReviews: vi.fn(),
  rejectReview: vi.fn(),
  withdrawReviewConfirmation: vi.fn(),
}));

const pending: ReviewItemDTO = {
  id: "secret-review-80",
  review_type: "project_ingest_approval",
  trigger_source: "secret-trigger",
  status: "pending_reviewer",
  target_asset_id: "secret-asset-80",
  asset_title: "客户交付复盘",
  target_scope: "project",
  target_project_id: "secret-project-80",
  project_name: "华东增长项目",
  submitted_by: "secret-submitter-80",
  reviewer_user_id: "secret-reviewer-80",
  evidence_count: 0,
  review_comment: null,
  reviewed_at: null,
  created_at: "2026-07-16T02:00:00Z",
  can_decide: true,
  can_withdraw: false,
  general_manager_confirmation_status: null,
  consulting_director_confirmation_status: null,
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/review"]}>
      <Routes>
        <Route path="/review" element={<ReviewPage />} />
        <Route path="/original-access" element={<div>原文访问正式路由</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ReviewPage governance workspace", () => {
  beforeEach(() => {
    vi.mocked(fetchReviews).mockReset().mockResolvedValue([pending]);
    vi.mocked(approveReview).mockReset().mockResolvedValue();
    vi.mocked(rejectReview).mockReset().mockResolvedValue();
    vi.mocked(withdrawReviewConfirmation).mockReset().mockResolvedValue();
  });

  it("uses the formal route workspace and sends real status and type filters", async () => {
    renderPage();
    expect(await screen.findByRole("table", { name: "知识审核队列" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "审核与原文访问" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "原文访问" })).toHaveAttribute(
      "href",
      "/original-access",
    );
    expect(fetchReviews).toHaveBeenCalledWith({ status: undefined, reviewType: undefined });

    fireEvent.change(screen.getByLabelText("审核状态"), {
      target: { value: "2" },
    });
    fireEvent.change(screen.getByLabelText("审核类型"), {
      target: { value: "1" },
    });
    await waitFor(() =>
      expect(fetchReviews).toHaveBeenLastCalledWith({
        status: "pending_reviewer",
        reviewType: "project_ingest_approval",
      }),
    );

    fireEvent.click(screen.getByRole("link", { name: "原文访问" }));
    expect(await screen.findByText("原文访问正式路由")).toBeInTheDocument();
  });

  it("shows safe fields and never renders ids, trigger sources or unknown enums", async () => {
    vi.mocked(fetchReviews).mockResolvedValue([
      pending,
      {
        ...pending,
        id: "secret-review-unknown",
        asset_title: null,
        project_name: null,
        review_type: "secret-review-type",
        status: "secret-review-status",
        can_decide: false,
      },
    ]);
    renderPage();

    const knownRow = (await screen.findByText("客户交付复盘")).closest("tr");
    expect(within(knownRow!).getByText("项目知识入库")).toBeInTheDocument();
    expect(within(knownRow!).getByText("无需证据")).toBeInTheDocument();
    expect(screen.getByText("待确认知识")).toBeInTheDocument();
    expect(screen.getAllByText("信息待确认")).toHaveLength(2);
    const visible = document.body.textContent ?? "";
    for (const secret of [
      "secret-review-80",
      "secret-asset-80",
      "secret-project-80",
      "secret-submitter-80",
      "secret-reviewer-80",
      "secret-trigger",
      "secret-review-type",
      "secret-review-status",
    ]) {
      expect(visible).not.toContain(secret);
    }
  });

  it("drives approve, retry and withdraw from capabilities and reloads the queue", async () => {
    vi.mocked(fetchReviews).mockResolvedValue([
      pending,
      {
        ...pending,
        id: "failed-review",
        asset_title: "索引失败知识",
        status: "approval_failed",
      },
      {
        ...pending,
        id: "withdraw-review",
        asset_title: "可撤回确认",
        status: "approved",
        can_decide: false,
        can_withdraw: true,
      },
      { ...pending, id: "readonly-review", asset_title: "只读审核", can_decide: false },
    ]);
    renderPage();

    const pendingRow = (await screen.findByText("客户交付复盘")).closest("tr");
    fireEvent.click(within(pendingRow!).getByRole("button", { name: "确认" }));
    await waitFor(() => expect(approveReview).toHaveBeenCalledWith(pending.id, "确认通过"));
    await waitFor(() => expect(fetchReviews).toHaveBeenCalledTimes(2));

    const failedRow = screen.getByText("索引失败知识").closest("tr");
    expect(within(failedRow!).queryByRole("button", { name: "拒绝" })).not.toBeInTheDocument();
    fireEvent.click(within(failedRow!).getByRole("button", { name: "重试" }));
    await waitFor(() => expect(approveReview).toHaveBeenCalledWith("failed-review", "重试入库"));

    const withdrawRow = screen.getByText("可撤回确认").closest("tr");
    fireEvent.click(within(withdrawRow!).getByRole("button", { name: "撤回" }));
    await waitFor(() =>
      expect(withdrawReviewConfirmation).toHaveBeenCalledWith("withdraw-review", "撤回本人确认"),
    );
    expect(within(screen.getByText("只读审核").closest("tr")!).queryByRole("button")).toBeNull();
  });

  it("requires a real rejection reason before calling the reject endpoint", async () => {
    renderPage();
    const row = (await screen.findByText("客户交付复盘")).closest("tr");
    fireEvent.click(within(row!).getByRole("button", { name: "拒绝" }));
    fireEvent.click(screen.getByRole("button", { name: "确认拒绝" }));
    expect(screen.getByText("请填写拒绝原因。")).toBeInTheDocument();
    expect(rejectReview).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("拒绝原因"), {
      target: { value: "缺少客户确认记录" },
    });
    fireEvent.click(screen.getByRole("button", { name: "确认拒绝" }));
    await waitFor(() => expect(rejectReview).toHaveBeenCalledWith(pending.id, "缺少客户确认记录"));
    await waitFor(() => expect(fetchReviews).toHaveBeenCalledTimes(2));
  });

  it("uses generic recoverable errors and a safe forbidden state", async () => {
    vi.mocked(fetchReviews)
      .mockRejectedValueOnce(
        new ApiError(503, "upstream storage_ref=s3://secret", "secret_denied_reason"),
      )
      .mockResolvedValueOnce([]);
    const first = renderPage();
    expect(await screen.findByText("审核队列加载失败")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/storage_ref|secret_denied_reason|503/);
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("暂无审核事项")).toBeInTheDocument();
    first.unmount();

    vi.mocked(fetchReviews).mockRejectedValueOnce(
      new ApiError(403, "manager-only secret", "role_secret"),
    );
    renderPage();
    expect(await screen.findByText("无审核权限")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/manager-only|role_secret|项目经理/);
  });
});
