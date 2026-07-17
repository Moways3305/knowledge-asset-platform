import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchIndexingJobs,
  fetchOpsIndexing,
  triggerIndexingReparse,
  triggerIndexingRetry,
} from "../api/admin";
import { fetchAdminIngest } from "../api/ingest";
import type { IndexingJobSummaryDTO, OpsIndexingDTO } from "../types/ops";
import AdminIngestPage from "./AdminIngestPage";

vi.mock("../api/admin", () => ({
  fetchIndexingJobs: vi.fn(),
  fetchOpsIndexing: vi.fn(),
  triggerIndexingReparse: vi.fn(),
  triggerIndexingRetry: vi.fn(),
}));
vi.mock("../api/ingest", () => ({ fetchAdminIngest: vi.fn() }));

const ops: OpsIndexingDTO = {
  counts: {
    index_failed: 3,
    indexing: 2,
    not_indexed: 4,
    skipped: 1,
    parse_pending: 2,
    parse_processing: 1,
    kb_init_failed: 0,
  },
  recent_failed: [
    {
      asset_id: "asset-secret-84",
      title: "绝不能显示的业务标题",
      scope: "project",
      project_name: "绝不能显示的项目名称",
      owner_name: "绝不能显示的人员名称",
      index_status: "index_failed",
      index_error_code: "UPSTREAM_SECRET_CODE",
      index_error_message: "索引服务暂时不可用",
      operator_error_message: "连接检查未通过，请确认平台配置。",
      remediation_hint: "SECRET-REMEDIATION",
      severity: "critical",
      updated_at: "2026-07-17T02:30:00Z",
    },
  ],
  title_visible: true,
};

const completedJob: IndexingJobSummaryDTO = {
  job_id: "job-secret-84",
  operation_type: "retry_index",
  status: "completed",
  scope_filter: null,
  requested_by_name: "SECRET OPERATOR",
  requested_at: "2026-07-17T02:30:00Z",
  started_at: "2026-07-17T02:31:00Z",
  finished_at: "2026-07-17T02:32:00Z",
  total_count: 6,
  success_count: 5,
  failed_count: 1,
  skipped_count: 0,
  error_code: "SECRET_CODE",
  error_message: "SECRET MESSAGE",
  trace_id: "trace-secret-84",
};

function renderPage() {
  return render(
    <MemoryRouter>
      <AdminIngestPage />
    </MemoryRouter>,
  );
}

describe("AdminIngestPage operations reference", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchOpsIndexing).mockResolvedValue(ops);
    vi.mocked(fetchIndexingJobs).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(fetchAdminIngest).mockResolvedValue({
      items: [
        {
          id: "ingest-secret-84",
          source: "path_b_upload",
          source_file_name: "绝不能显示的原始文件名.docx",
          status: "processing",
          target_scope: "project",
          confidentiality_level: "L4",
          ai_access_level: "A1",
          confidence: null,
          naming_compliant: null,
          extraction_status: "success",
          error_type: null,
          error_message: null,
          result_asset_id: null,
          created_at: "2026-07-17T02:20:00Z",
        },
      ],
      total: 1,
    });
    vi.mocked(triggerIndexingRetry).mockResolvedValue(completedJob);
    vi.mocked(triggerIndexingReparse).mockResolvedValue({
      ...completedJob,
      job_id: "reparse-job-secret-84",
      operation_type: "reparse",
    });
  });

  it("renders the three operations tabs and only safe aggregate failure data", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "管理员运维" })).toBeInTheDocument();
    expect(screen.getByText("查看索引运行、扫描任务和安全审计状态。")).toBeInTheDocument();
    const tabs = screen.getByRole("navigation", { name: "管理员运维页面" });
    expect(within(tabs).getByRole("link", { name: "索引维护" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(tabs).getByRole("link", { name: "微盘扫描" })).toHaveAttribute(
      "href",
      "/admin/wecom-scan",
    );
    expect(within(tabs).getByRole("link", { name: "安全日志" })).toHaveAttribute(
      "href",
      "/admin/audit",
    );

    expect(await screen.findByText("连接检查未通过，请确认平台配置。")).toBeInTheDocument();
    expect(screen.getByText("3 项索引失败")).toBeInTheDocument();
    expect(screen.getByText("共 1 项")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("绝不能显示的业务标题");
    expect(document.body).not.toHaveTextContent("绝不能显示的项目名称");
    expect(document.body).not.toHaveTextContent("绝不能显示的人员名称");
    expect(document.body).not.toHaveTextContent("绝不能显示的原始文件名.docx");
    expect(document.body).not.toHaveTextContent("asset-secret-84");
    expect(document.body).not.toHaveTextContent("UPSTREAM_SECRET_CODE");
    expect(document.body).not.toHaveTextContent("critical");
  });

  it("submits the selected bounded batch retry and prevents duplicate actions", async () => {
    let resolveJob!: (job: IndexingJobSummaryDTO) => void;
    vi.mocked(triggerIndexingRetry).mockImplementation(
      () => new Promise((resolve) => (resolveJob = resolve)),
    );
    const user = userEvent.setup();
    renderPage();

    const retry = await screen.findByRole("button", { name: "批量重试索引" });
    await user.click(screen.getByRole("checkbox", { name: "包含已跳过" }));
    await user.click(screen.getByRole("checkbox", { name: "包含未索引" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "处理上限" }), "100");
    await user.click(retry);

    expect(triggerIndexingRetry).toHaveBeenCalledWith({
      scope: "all",
      statuses: ["index_failed", "skipped", "not_indexed"],
      limit: 100,
    });
    expect(screen.getByRole("button", { name: "提交中…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "重新解析" })).toBeDisabled();

    resolveJob({ ...completedJob, status: "running" });
    await waitFor(() => expect(screen.getByRole("button", { name: "作业执行中" })).toBeDisabled());
    expect(triggerIndexingRetry).toHaveBeenCalledTimes(1);
  });

  it("uses the real reparse contract and reports only safe result counts", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "重新解析" }));
    await waitFor(() =>
      expect(triggerIndexingReparse).toHaveBeenCalledWith({
        scope: "all",
        parse_statuses: ["failed", "pending"],
        limit: 50,
      }),
    );
    expect(await screen.findByText(/重新解析已提交：共 6 项/)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("reparse-job-secret-84");
    expect(document.body).not.toHaveTextContent("trace-secret-84");
    expect(document.body).not.toHaveTextContent("SECRET MESSAGE");
  });

  it("keeps the independently loaded ingest overview when indexing fails", async () => {
    vi.mocked(fetchOpsIndexing).mockRejectedValue(new Error("SECRET upstream failure"));
    renderPage();

    expect(await screen.findByText("索引状态暂时无法加载")).toBeInTheDocument();
    expect(screen.getByText("失败任务暂时无法加载")).toBeInTheDocument();
    expect(screen.getByText("共 1 项")).toBeInTheDocument();
    expect(screen.getByText("处理中")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("SECRET upstream failure");
  });

  it("keeps a stable explicit empty state", async () => {
    vi.mocked(fetchOpsIndexing).mockResolvedValue({
      ...ops,
      counts: { ...ops.counts, index_failed: 0 },
      recent_failed: [],
    });
    renderPage();

    expect(await screen.findByText("当前没有索引失败任务")).toBeInTheDocument();
    expect(screen.getByText("当前没有索引失败项")).toBeInTheDocument();
  });

  it("does not echo action errors returned by the service", async () => {
    vi.mocked(triggerIndexingRetry).mockRejectedValue(new Error("SECRET TOKEN IN ERROR"));
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "批量重试索引" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("批量重试未能发起，请稍后重试。");
    expect(document.body).not.toHaveTextContent("SECRET TOKEN IN ERROR");
  });
});
