import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { approveReview, fetchReviews, rejectReview } from "../api/review";
import type { ReviewItemDTO } from "../types/review";
import ReviewPage from "./ReviewPage";

vi.mock("../api/review", () => ({
  approveReview: vi.fn(),
  fetchReviews: vi.fn(),
  rejectReview: vi.fn(),
}));

const pending: ReviewItemDTO = {
  id: "review-1",
  review_type: "project_ingest_approval",
  trigger_source: "upload",
  status: "pending_reviewer",
  target_asset_id: null,
  asset_title: "待审批项目知识",
  target_scope: "project",
  target_project_id: "project-alpha",
  project_name: "Alpha 项目",
  submitted_by: "consultant-1",
  reviewer_user_id: "manager-1",
  evidence_count: 0,
  review_comment: null,
  reviewed_at: null,
  created_at: "2026-07-14T00:00:00Z",
  can_decide: true,
};

describe("ReviewPage project ingest approvals", () => {
  beforeEach(() => {
    vi.mocked(fetchReviews).mockReset().mockResolvedValue([pending]);
    vi.mocked(approveReview).mockReset().mockResolvedValue();
    vi.mocked(rejectReview).mockReset().mockResolvedValue();
  });

  it("shows a real project pending task and lets an authorized manager decide", async () => {
    render(
      <MemoryRouter>
        <ReviewPage />
      </MemoryRouter>,
    );
    const row = (await screen.findByText("待审批项目知识")).closest("tr");
    expect(row).not.toBeNull();
    expect(within(row!).getByText("项目知识入库")).toBeInTheDocument();
    expect(within(row!).getByText("无需证据")).toBeInTheDocument();
    fireEvent.click(within(row!).getByRole("button", { name: "通过" }));
    await waitFor(() => expect(approveReview).toHaveBeenCalledWith("review-1", "确认通过"));
  });

  it("offers retry after a controlled approval failure and hides actions without permission", async () => {
    vi.mocked(fetchReviews).mockResolvedValue([
      {
        ...pending,
        id: "failed",
        asset_title: "入库失败项目知识",
        status: "approval_failed",
      },
      { ...pending, id: "other", asset_title: "其他项目待办", can_decide: false },
    ]);
    render(
      <MemoryRouter>
        <ReviewPage />
      </MemoryRouter>,
    );
    const failedRow = (await screen.findByText("入库失败项目知识")).closest("tr");
    expect(within(failedRow!).getByRole("button", { name: "重试入库" })).toBeInTheDocument();
    const otherRow = screen.getByText("其他项目待办").closest("tr");
    expect(within(otherRow!).queryByRole("button")).not.toBeInTheDocument();
  });
});
