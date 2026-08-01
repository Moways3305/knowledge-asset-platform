import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/http";
import {
  approveOriginalAccess,
  fetchOriginalAccessRequests,
  rejectOriginalAccess,
} from "../api/knowledge";
import type { OriginalAccessRequestDTO } from "../types/originalAccess";
import OriginalAccessPage from "./OriginalAccessPage";

vi.mock("../api/knowledge", () => ({
  approveOriginalAccess: vi.fn(),
  fetchOriginalAccessRequests: vi.fn(),
  rejectOriginalAccess: vi.fn(),
}));

const pending: OriginalAccessRequestDTO = {
  request_id: "secret-request-80",
  asset_id: "secret-asset-80",
  asset_title: "客户访谈原文",
  scope: "project",
  project_id: "secret-project-80",
  requester_user_id: "secret-requester-80",
  requester_name: "王顾问",
  reviewer_user_id: "secret-reviewer-80",
  reviewer_name: null,
  requested_access_layer: "secret-original-layer",
  status: "pending",
  reason: "核对客户原始反馈",
  review_note: null,
  created_at: "2026-07-16T02:00:00Z",
  reviewed_at: null,
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/original-access"]}>
      <Routes>
        <Route path="/original-access" element={<OriginalAccessPage />} />
        <Route path="/review" element={<div>知识审核正式路由</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("OriginalAccessPage governance workspace", () => {
  beforeEach(() => {
    vi.mocked(fetchOriginalAccessRequests)
      .mockReset()
      .mockResolvedValue({ items: [pending], total: 1 });
    vi.mocked(approveOriginalAccess)
      .mockReset()
      .mockResolvedValue({} as never);
    vi.mocked(rejectOriginalAccess)
      .mockReset()
      .mockResolvedValue({} as never);
  });

  it("uses the formal route workspace and only the backend-supported box switch", async () => {
    renderPage();
    expect(
      await screen.findByRole("table", { name: "待我审批的原文访问申请" }),
    ).toBeInTheDocument();
    expect(fetchOriginalAccessRequests).toHaveBeenCalledWith("inbox");
    expect(screen.queryByLabelText(/状态筛选|日期范围|分页/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "审核待办" })).toHaveAttribute("href", "/review");
    fireEvent.click(screen.getByRole("link", { name: "审核待办" }));
    expect(await screen.findByText("知识审核正式路由")).toBeInTheDocument();
  });

  it("shows safe request fields and hides ids, access layers and unknown enums", async () => {
    vi.mocked(fetchOriginalAccessRequests).mockResolvedValue({
      items: [
        pending,
        {
          ...pending,
          request_id: "secret-request-unknown",
          asset_id: "secret-asset-unknown",
          asset_title: null,
          scope: "secret-scope",
          status: "secret-status",
          requester_name: null,
          reason: null,
        },
      ],
      total: 2,
    });
    renderPage();

    expect(await screen.findByText("客户访谈原文")).toBeInTheDocument();
    expect(screen.getByText("项目知识")).toBeInTheDocument();
    expect(screen.getByText("待确认资产")).toBeInTheDocument();
    expect(screen.getAllByText("信息待确认")).toHaveLength(2);
    expect(screen.getByText("未提供")).toBeInTheDocument();
    expect(screen.getByText("未填写")).toBeInTheDocument();
    const visible = document.body.textContent ?? "";
    for (const secret of [
      "secret-request-80",
      "secret-asset-80",
      "secret-project-80",
      "secret-requester-80",
      "secret-reviewer-80",
      "secret-original-layer",
      "secret-scope",
      "secret-status",
    ]) {
      expect(visible).not.toContain(secret);
    }
  });

  it("offers inbox actions only for pending requests and reloads after decisions", async () => {
    vi.mocked(fetchOriginalAccessRequests).mockResolvedValue({
      items: [
        pending,
        { ...pending, request_id: "terminal", asset_title: "已完成申请", status: "approved" },
      ],
      total: 2,
    });
    renderPage();

    const pendingRow = (await screen.findByText("客户访谈原文")).closest("tr");
    fireEvent.click(within(pendingRow!).getByRole("button", { name: "通过" }));
    await waitFor(() => expect(approveOriginalAccess).toHaveBeenCalledWith(pending.request_id));
    await waitFor(() => expect(fetchOriginalAccessRequests).toHaveBeenCalledTimes(2));
    const terminalRow = screen.getByText("已完成申请").closest("tr");
    expect(within(terminalRow!).queryByRole("button")).toBeNull();

    const reloadedPendingRow = screen.getByText("客户访谈原文").closest("tr");
    fireEvent.click(within(reloadedPendingRow!).getByRole("button", { name: "拒绝" }));
    await waitFor(() => expect(rejectOriginalAccess).toHaveBeenCalledWith(pending.request_id));
  });

  it("switches to mine through a real request and shows reviewer records without actions", async () => {
    vi.mocked(fetchOriginalAccessRequests).mockImplementation((box) =>
      Promise.resolve(
        box === "inbox"
          ? { items: [pending], total: 1 }
          : {
              items: [
                {
                  ...pending,
                  request_id: "mine-secret",
                  asset_title: "本人申请记录",
                  status: "approved",
                  reviewer_name: "李经理",
                  reviewed_at: "2026-07-17T03:00:00Z",
                },
              ],
              total: 1,
            },
      ),
    );
    renderPage();
    await screen.findByText("客户访谈原文");
    fireEvent.click(screen.getByRole("button", { name: "我的申请" }));

    expect(await screen.findByText("本人申请记录")).toBeInTheDocument();
    expect(fetchOriginalAccessRequests).toHaveBeenLastCalledWith("mine");
    expect(screen.getByText(/李经理 · 2026-07-17/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "通过" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "拒绝" })).not.toBeInTheDocument();
  });

  it("uses generic recoverable errors and a role-neutral forbidden state", async () => {
    vi.mocked(fetchOriginalAccessRequests)
      .mockRejectedValueOnce(new ApiError(500, "signed_url=https://secret", "upstream_secret"))
      .mockResolvedValueOnce({ items: [], total: 0 });
    const first = renderPage();
    expect(await screen.findByText("原文访问申请加载失败")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/signed_url|upstream_secret|500/);
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("暂无待审批申请")).toBeInTheDocument();
    first.unmount();

    vi.mocked(fetchOriginalAccessRequests).mockRejectedValueOnce(
      new ApiError(403, "boss-only secret", "permission_secret"),
    );
    renderPage();
    expect(await screen.findByText("无原文访问权限")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/boss-only|permission_secret|项目经理|总经理/);
  });
});
