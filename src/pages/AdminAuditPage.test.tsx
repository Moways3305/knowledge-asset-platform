import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchAudit, markAuditProcessed } from "../api/admin";
import { ApiError } from "../api/http";
import type { AuditEventDTO } from "../types/audit";
import AdminAuditPage from "./AdminAuditPage";

vi.mock("../api/admin", () => ({ fetchAudit: vi.fn(), markAuditProcessed: vi.fn() }));

const base: AuditEventDTO = {
  id: "event-secret-id",
  log_type: "operation",
  action: "project.created",
  actor_user_id: "user-secret-id",
  actor_name: "张经理",
  actor_company_role: "project_manager",
  actor_project_role: null,
  target_type: "project",
  target_id: "target-secret-id",
  severity: null,
  is_processed: false,
  processed_by: null,
  processed_at: null,
  trace_id: "trace-secret-id",
  denied_reason: null,
  risk_level: null,
  created_at: "2026-07-20T01:00:00Z",
  before_snapshot: { token: "before-secret" },
  after_snapshot: { storage_ref: "storage-secret" },
  extra: { download_url: "https://secret.invalid" },
};

describe("AdminAuditPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchAudit).mockResolvedValue({
      items: [
        base,
        {
          ...base,
          id: "exception-id",
          log_type: "exception",
          action: "preview.denied",
          severity: "critical",
          denied_reason: "raw_denial_secret",
        },
        {
          ...base,
          id: "login-id",
          log_type: "login",
          action: "login.failed",
          denied_reason: "raw_login_secret",
        },
      ],
      total: 3,
      page: 1,
      page_size: 200,
      view: "admin_metadata",
    });
    vi.mocked(markAuditProcessed).mockResolvedValue({
      event_id: "exception-id",
      is_processed: true,
      processed_by: null,
      processed_at: null,
    });
  });

  it("renders truthful summary and hides raw audit fields", async () => {
    const { container } = render(<AdminAuditPage />);
    expect(await screen.findByText("创建项目知识库")).toBeInTheDocument();
    const summary = screen.getByLabelText("审计摘要");
    expect(within(summary).getAllByText("1", { selector: ".secops-summary-value" })).toHaveLength(
      4,
    );
    const console = container.querySelector(".secops-console");
    expect(console?.children).toHaveLength(2);
    expect(container.querySelector(".secops-main-workspace")).toContainElement(
      container.querySelector(".secops-workspace"),
    );
    const html = container.innerHTML;
    for (const secret of [
      "event-secret-id",
      "user-secret-id",
      "target-secret-id",
      "trace-secret-id",
      "before-secret",
      "storage-secret",
      "secret.invalid",
      "project.created",
    ])
      expect(html).not.toContain(secret);
  });

  it("filters anomalies and marks an allowed event locally", async () => {
    render(<AdminAuditPage />);
    fireEvent.click(await screen.findByRole("tab", { name: "异常" }));
    fireEvent.change(screen.getByLabelText("异常级别"), { target: { value: "warning" } });
    expect(screen.getByText("暂无符合条件的异常记录")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("异常级别"), { target: { value: "critical" } });
    fireEvent.click(screen.getByRole("button", { name: "标记已处理" }));
    await waitFor(() => expect(markAuditProcessed).toHaveBeenCalledWith("exception-id"));
    expect(await screen.findByText("异常记录已标记为已处理。")).toBeInTheDocument();
  });

  it("keeps governance view read-only", async () => {
    vi.mocked(fetchAudit).mockResolvedValueOnce({
      items: [{ ...base, log_type: "exception" }],
      total: 1,
      page: 1,
      page_size: 200,
      view: "governance",
    });
    render(<AdminAuditPage />);
    expect(
      await screen.findByText("当前为只读审计视图，可核查记录但不能标记处理。"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "异常" }));
    expect(screen.queryByRole("button", { name: "标记已处理" })).not.toBeInTheDocument();
  });

  it.each([
    [[], "暂无操作记录"],
    [new ApiError(503, "raw server token"), "审计日志暂时无法加载，请稍后重试。"],
    [new ApiError(403, "raw forbidden", "raw_reason"), "当前身份没有审计日志查看权限。"],
  ])("handles empty and safe error states", async (result, expected) => {
    if (Array.isArray(result))
      vi.mocked(fetchAudit).mockResolvedValueOnce({
        items: result,
        total: 0,
        page: 1,
        page_size: 200,
        view: "admin_metadata",
      });
    else vi.mocked(fetchAudit).mockRejectedValueOnce(result);
    const { container } = render(<AdminAuditPage />);
    expect(await screen.findByText(expected)).toBeInTheDocument();
    expect(container.innerHTML).not.toMatch(/raw server token|raw forbidden|raw_reason/);
  });
});
