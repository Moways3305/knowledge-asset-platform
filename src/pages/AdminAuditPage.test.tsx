import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchAudit, markAuditProcessed } from "../api/admin";
import { ApiError } from "../api/http";
import type { AuditEventDTO, AuditListResponseDTO } from "../types/audit";
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

const exceptionItem: AuditEventDTO = {
  ...base,
  id: "exception-id",
  log_type: "exception",
  action: "preview.denied",
  severity: "critical",
  denied_reason: "raw_denial_secret",
};

const loginItem: AuditEventDTO = {
  ...base,
  id: "login-id",
  log_type: "login",
  action: "login.failed",
  denied_reason: "raw_login_secret",
};

const ALL_ITEMS: AuditEventDTO[] = [base, exceptionItem, loginItem];

function makeResponse(
  items: AuditEventDTO[],
  overrides: Partial<AuditListResponseDTO> = {},
): AuditListResponseDTO {
  return {
    items,
    total: items.length,
    page: 1,
    page_size: 50,
    view: "admin_metadata",
    ...overrides,
  };
}

describe("AdminAuditPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // 参数感知的迷你服务端：按 log_type / severity / is_processed 过滤，模拟分页。
    vi.mocked(fetchAudit).mockImplementation(async (params = {}) => {
      if (!params.logType) {
        return makeResponse(ALL_ITEMS, { page_size: 200 });
      }
      let filtered = ALL_ITEMS.filter((item) => item.log_type === params.logType);
      if (params.severity) filtered = filtered.filter((item) => item.severity === params.severity);
      if (params.isProcessed !== undefined) {
        filtered = filtered.filter((item) => item.is_processed === params.isProcessed);
      }
      return makeResponse(filtered);
    });
    vi.mocked(markAuditProcessed).mockResolvedValue({
      event_id: "exception-id",
      is_processed: true,
      processed_by: null,
      processed_at: null,
    });
  });

  it("renders the unprocessed exception queue first and hides raw audit fields", async () => {
    const { container } = render(<AdminAuditPage />);
    expect(await screen.findByText("预览被拒")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "异常" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByLabelText("处理状态")).toHaveValue("unprocessed");
    const console = container.querySelector(".secops-console");
    expect(console?.children).toHaveLength(1);
    expect(container.querySelector(".secops-summary-panel")).not.toBeInTheDocument();
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

  it("filters anomalies server-side and marks an allowed event locally", async () => {
    render(<AdminAuditPage />);
    fireEvent.click(await screen.findByRole("tab", { name: "异常" }));
    await waitFor(() =>
      expect(fetchAudit).toHaveBeenCalledWith(
        expect.objectContaining({ logType: "exception", page: 1 }),
      ),
    );
    fireEvent.change(screen.getByLabelText("异常级别"), { target: { value: "warning" } });
    expect(await screen.findByText("暂无符合条件的异常记录")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("异常级别"), { target: { value: "critical" } });
    fireEvent.click(await screen.findByRole("button", { name: "标记已处理" }));
    await waitFor(() => expect(markAuditProcessed).toHaveBeenCalledWith("exception-id"));
    expect(await screen.findByText("异常记录已标记为已处理。")).toBeInTheDocument();
  });

  it("paginates and keeps page state when flipping", async () => {
    const pageOne = makeResponse([exceptionItem], { total: 60 });
    const pageTwo = makeResponse([{ ...exceptionItem, id: "exception-2" }], {
      total: 60,
      page: 2,
    });
    vi.mocked(fetchAudit).mockImplementation(async (params = {}) => {
      if (!params.logType) return makeResponse(ALL_ITEMS, { page_size: 200 });
      if (params.logType === "exception") {
        return (params.page ?? 1) === 1 ? pageOne : pageTwo;
      }
      return makeResponse([]);
    });
    render(<AdminAuditPage />);
    fireEvent.click(await screen.findByRole("tab", { name: "异常" }));
    await screen.findByText("第 1 / 2 页 · 共 60 条");
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    await waitFor(() =>
      expect(fetchAudit).toHaveBeenCalledWith(
        expect.objectContaining({ logType: "exception", page: 2 }),
      ),
    );
    expect(await screen.findByText("第 2 / 2 页 · 共 60 条")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
  });

  it("keeps governance view read-only", async () => {
    vi.mocked(fetchAudit).mockImplementation(async (params = {}) => {
      if (!params.logType) return makeResponse([exceptionItem], { view: "governance" });
      return makeResponse([exceptionItem], { view: "governance" });
    });
    render(<AdminAuditPage />);
    expect(
      await screen.findByText("当前为只读审计视图，可核查记录但不能标记处理。"),
    ).toBeInTheDocument();
    await waitFor(() => expect(fetchAudit).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("tab", { name: "异常" }));
    await waitFor(() =>
      expect(fetchAudit).toHaveBeenCalledWith(expect.objectContaining({ logType: "exception" })),
    );
    expect(screen.queryByRole("button", { name: "标记已处理" })).not.toBeInTheDocument();
  });

  it.each([
    [[], "暂无符合条件的异常记录"],
    [new ApiError(503, "raw server token"), "审计日志暂时无法加载，请稍后重试。"],
    [new ApiError(403, "raw forbidden", "raw_reason"), "当前身份没有审计日志查看权限。"],
  ])("handles empty and safe error states", async (result, expected) => {
    if (Array.isArray(result)) {
      vi.mocked(fetchAudit).mockResolvedValue(
        makeResponse(result as AuditEventDTO[], { page_size: 200 }),
      );
    } else {
      vi.mocked(fetchAudit).mockRejectedValue(result);
    }
    const { container } = render(<AdminAuditPage />);
    expect(await screen.findByText(expected)).toBeInTheDocument();
    expect(container.innerHTML).not.toMatch(/raw server token|raw forbidden|raw_reason/);
  });
});
